"""
Loads the Jharkhand-fine-tuned crop model and disease detection models
(EfficientNet-B4 Jharkhand-tuned + legacy ResNet fallbacks) once at startup,
and exposes prediction functions consumed by the API routes.
"""

import io
import json
from typing import Optional

import joblib
import numpy as np
import onnxruntime as ort
from PIL import Image

from core.config import (
    CROP_LABEL_MAPPING_PATH,
    CROP_MODEL_PATH,
    DEFAULT_HUMIDITY_PCT,
    DEFAULT_TEMPERATURE_C,
    DISEASE_MODEL_DIR,
    DISEASE_LABEL_MAPPING_PATH
)
from services.weather_service import fetch_weather

# Will be populated from disease_classes.json at startup.
# Falls back to empty list if no mapping file is found.
DISEASE_CLASSES: list[str] = []

# ImageNet normalisation constants (must match training transforms)
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

# Model paths — the new Jharkhand EfficientNet-B4 is preferred;
# legacy ResNet models are kept as fallbacks.
DISEASE_MODEL_PATHS = {
    "efficientnet_b4": DISEASE_MODEL_DIR / "efficientnet_b4_jharkhand.onnx",
    "resnet50": DISEASE_MODEL_DIR / "resnet50_plant_disease.onnx",
    "resnet9": DISEASE_MODEL_DIR / "resnet9_plant_disease.onnx",
}

# Input resolution per model architecture.
# EfficientNet-B4 was trained at 380; legacy ResNet models used 256.
_MODEL_INPUT_SIZE: dict[str, int] = {
    "efficientnet_b4": 380,
    "resnet50": 256,
    "resnet9": 256,
}

_crop_model = None
_crop_label_mapping: dict[int, str] = {}
_disease_sessions: dict[str, ort.InferenceSession] = {}


def load_models():
    """Call once on FastAPI startup (see main.py lifespan)."""
    global _crop_model, _crop_label_mapping

    if CROP_MODEL_PATH.exists():
        _crop_model = joblib.load(CROP_MODEL_PATH)
        print(f"Loaded crop recommendation model from {CROP_MODEL_PATH}")
    else:
        print(f"WARNING: crop model not found at {CROP_MODEL_PATH}")

    if CROP_LABEL_MAPPING_PATH.exists():
        with open(CROP_LABEL_MAPPING_PATH) as f:
            _crop_label_mapping = {int(k): v for k, v in json.load(f).items()}

    global DISEASE_CLASSES
    if DISEASE_LABEL_MAPPING_PATH.exists():
        with open(DISEASE_LABEL_MAPPING_PATH) as f:
            mapping = json.load(f)
            # Reconstruct list assuming keys are "0", "1", ...
            max_idx = max(int(k) for k in mapping.keys())
            new_classes = ["Unknown"] * (max_idx + 1)
            for k, v in mapping.items():
                new_classes[int(k)] = v
            DISEASE_CLASSES = new_classes
            print(f"Loaded {len(DISEASE_CLASSES)} disease classes from {DISEASE_LABEL_MAPPING_PATH}")

    # Load model metadata (written by export_onnx.py) to detect input size
    metadata_path = DISEASE_MODEL_DIR / "model_metadata.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
            model_key = metadata.get("model_name", "efficientnet_b4")
            if "img_size" in metadata:
                _MODEL_INPUT_SIZE[model_key] = metadata["img_size"]
                print(f"Model metadata: {model_key} input size = {metadata['img_size']}px")

    for name, path in DISEASE_MODEL_PATHS.items():
        if path.exists():
            # Prefer CUDA if available, fall back to CPU
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            try:
                _disease_sessions[name] = ort.InferenceSession(str(path), providers=providers)
            except Exception:
                _disease_sessions[name] = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            print(f"Loaded disease model '{name}' from {path}")
        else:
            print(f"WARNING: disease model '{name}' not found at {path}")


def predict_crop(
    n: int, p: int, k: int, ph: float, rainfall: float,
    lat: Optional[float] = None, lon: Optional[float] = None,
    temperature: Optional[float] = None, humidity: Optional[float] = None,
):
    if _crop_model is None:
        raise RuntimeError("Crop recommendation model is not loaded.")

    if temperature is None or humidity is None:
        weather = fetch_weather(lat, lon) if lat is not None and lon is not None else None
        if weather and weather[0] is not None:
            temperature = temperature if temperature is not None else weather[0]
            humidity = humidity if humidity is not None else weather[1]
        else:
            temperature = temperature if temperature is not None else DEFAULT_TEMPERATURE_C
            humidity = humidity if humidity is not None else DEFAULT_HUMIDITY_PCT

    features = np.array([[n, p, k, temperature, humidity, ph, rainfall]])

    if hasattr(_crop_model, "predict_proba"):
        probs = _crop_model.predict_proba(features)[0]
        top_idx = np.argsort(probs)[::-1][:3]
        top_3 = [_crop_label_mapping.get(int(i), str(i)) for i in top_idx]
        top_3_confidence = [round(float(probs[i]), 4) for i in top_idx]
        prediction = top_3[0]
        confidence = top_3_confidence[0]
    else:
        pred_idx = int(_crop_model.predict(features)[0])
        prediction = _crop_label_mapping.get(pred_idx, str(pred_idx))
        top_3 = [prediction]
        top_3_confidence = [1.0]
        confidence = 1.0

    return {
        "success": True,
        "prediction": prediction,
        "confidence": confidence,
        "top_3": top_3,
        "top_3_confidence": top_3_confidence,
        "inputs": {
            "N": n, "P": p, "K": k, "ph": ph, "rainfall": rainfall,
            "temperature": temperature, "humidity": humidity,
        },
    }


def predict_disease(image_bytes: bytes, model_name: str = "efficientnet_b4", confidence_threshold: float = 0.5):
    # Fall back to any available model if the requested one isn't loaded
    session = _disease_sessions.get(model_name)
    if session is None:
        # Try the preferred model first, then any available
        for fallback in ["efficientnet_b4", "resnet50", "resnet9"]:
            if fallback in _disease_sessions:
                session = _disease_sessions[fallback]
                model_name = fallback
                break
    if session is None:
        raise RuntimeError("No disease detection model is loaded.")

    # Determine input size for this model
    input_size = _MODEL_INPUT_SIZE.get(model_name, 380)

    # ── Preprocess: match training transforms exactly ──────────────────
    # 1. Resize with slight over-size + center crop (matches val transforms)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    resize_size = int(input_size * 1.15)
    img = img.resize((resize_size, resize_size), Image.LANCZOS)
    # Center crop to input_size
    left = (resize_size - input_size) // 2
    top = (resize_size - input_size) // 2
    img = img.crop((left, top, left + input_size, top + input_size))

    # 2. To float32, scale to [0, 1]
    arr = np.asarray(img, dtype=np.float32) / 255.0
    # 3. HWC → CHW
    arr = np.transpose(arr, (2, 0, 1))
    # 4. ImageNet normalisation (CRITICAL: must match training)
    arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
    # 5. Add batch dimension → NCHW
    arr = arr[np.newaxis, ...]

    # ── Inference ──────────────────────────────────────────────────────
    input_name = session.get_inputs()[0].name
    logits = session.run(None, {input_name: arr})[0]

    # Softmax
    probabilities = np.exp(logits - np.max(logits, axis=1, keepdims=True))
    probabilities = probabilities / np.sum(probabilities, axis=1, keepdims=True)
    confidence = float(np.max(probabilities))
    predicted_idx = int(np.argmax(probabilities))

    predicted_class = DISEASE_CLASSES[predicted_idx] if predicted_idx < len(DISEASE_CLASSES) else f"class_{predicted_idx}"
    parts = predicted_class.split("___")
    plant_name = parts[0].replace("_", " ").title() if parts else "Unknown"
    disease_status = parts[1].replace("_", " ").title() if len(parts) > 1 else "Unknown"

    return {
        "success": True,
        "predicted_class": predicted_class,
        "plant_name": plant_name,
        "disease_status": disease_status,
        "confidence": confidence,
        "is_confident": confidence >= confidence_threshold,
        "model_used": model_name,
    }
