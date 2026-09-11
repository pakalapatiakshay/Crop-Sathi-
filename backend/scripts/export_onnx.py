"""
Export a trained EfficientNet-B4 (or other timm model) to ONNX format for
inference with onnxruntime in the Crop-Sathi backend.

Usage:
    python export_onnx.py \
        --model_path models/jharkhand_efficientnet_b4_best.pth \
        --output_path ../ml_models/plant-disease/efficientnet_b4_jharkhand.onnx
"""

import argparse
import json
import os
import shutil
from pathlib import Path

import timm
import torch
import torch.nn as nn


def export_to_onnx(
    model_path: str,
    output_path: str,
    num_classes: int,
    img_size: int = 380,
    model_name: str = "efficientnet_b4",
):
    print(f"Loading {model_name} from {model_path}...")

    # Build the same architecture used during training
    model = timm.create_model(
        model_name,
        pretrained=False,
        num_classes=num_classes,
        drop_rate=0.0,       # Disable dropout for inference
        drop_path_rate=0.0,
    )

    # Load trained weights
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
        loaded_classes = checkpoint.get("num_classes", num_classes)
        loaded_img_size = checkpoint.get("img_size", img_size)
        class_names = checkpoint.get("class_names", [])
        print(f"  Checkpoint info: {loaded_classes} classes, {loaded_img_size}px input")
        if loaded_img_size != img_size:
            print(f"  ⚠ Using checkpoint img_size={loaded_img_size} instead of --img_size={img_size}")
            img_size = loaded_img_size
    else:
        state_dict = checkpoint
        class_names = []

    model.load_state_dict(state_dict)
    model.eval()

    # Create dummy input
    dummy_input = torch.randn(1, 3, img_size, img_size)

    # Quick sanity check
    with torch.no_grad():
        output = model(dummy_input)
    print(f"  Model output shape: {output.shape} (expected: [1, {num_classes}])")
    assert output.shape == (1, num_classes), \
        f"Output shape mismatch: {output.shape} vs expected (1, {num_classes})"

    # Export
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    print(f"Exporting to ONNX at {output_path}...")

    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size"},
            "output": {0: "batch_size"},
        },
    )

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✅ Export successful! ({file_size_mb:.1f} MB)")

    # Also copy the disease_classes.json to the ml_models directory
    classes_src = os.path.join(os.path.dirname(model_path), "disease_classes.json")
    ml_models_dir = Path(output_path).parent
    classes_dst = ml_models_dir / "disease_classes.json"
    if os.path.exists(classes_src):
        shutil.copy2(classes_src, classes_dst)
        print(f"  📋 Copied class mapping to {classes_dst}")

    # Save model metadata for the backend to discover
    metadata = {
        "model_name": model_name,
        "num_classes": num_classes,
        "img_size": img_size,
        "class_names": class_names,
        "onnx_file": os.path.basename(output_path),
    }
    metadata_path = ml_models_dir / "model_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  📋 Saved model metadata to {metadata_path}")

    print(f"\n✅ Done! Deploy by copying to the ml_models/plant-disease/ directory:")
    print(f"   {output_path}")
    print(f"   {classes_dst}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export trained EfficientNet-B4 to ONNX"
    )
    parser.add_argument(
        "--model_path", type=str,
        default="models/jharkhand_efficientnet_b4_best.pth",
        help="Path to the .pth checkpoint"
    )
    parser.add_argument(
        "--output_path", type=str,
        default="../ml_models/plant-disease/efficientnet_b4_jharkhand.onnx",
        help="Path to save the .onnx model"
    )
    parser.add_argument(
        "--num_classes", type=int, default=None,
        help="Number of classes (auto-detected from checkpoint if not specified)"
    )
    parser.add_argument(
        "--img_size", type=int, default=380,
        help="Input image size (380 for EfficientNet-B4)"
    )
    parser.add_argument(
        "--model_name", type=str, default="efficientnet_b4",
        help="timm model architecture name"
    )
    args = parser.parse_args()

    if not os.path.exists(args.model_path):
        raise FileNotFoundError(f"Could not find model weights at {args.model_path}")

    # Auto-detect num_classes from checkpoint
    num_classes = args.num_classes
    if num_classes is None:
        checkpoint = torch.load(args.model_path, map_location="cpu", weights_only=False)
        if isinstance(checkpoint, dict) and "num_classes" in checkpoint:
            num_classes = checkpoint["num_classes"]
            print(f"Auto-detected {num_classes} classes from checkpoint")
        else:
            # Try to detect from disease_classes.json
            classes_json = os.path.join(os.path.dirname(args.model_path), "disease_classes.json")
            if os.path.exists(classes_json):
                with open(classes_json) as f:
                    num_classes = len(json.load(f))
                print(f"Auto-detected {num_classes} classes from {classes_json}")
            else:
                raise ValueError(
                    "Cannot auto-detect num_classes. "
                    "Specify --num_classes or ensure the checkpoint contains 'num_classes'."
                )

    export_to_onnx(
        args.model_path,
        args.output_path,
        num_classes,
        args.img_size,
        args.model_name,
    )
