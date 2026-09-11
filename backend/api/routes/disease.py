from fastapi import APIRouter, HTTPException, UploadFile

from db.schemas import DiseaseDetectionResponse
from services import ml_service

router = APIRouter(tags=["Disease Detection"])


@router.post("/analyze-disease", response_model=DiseaseDetectionResponse)
async def analyze_disease(file: UploadFile, model: str = "resnet50"):
    if model not in ("resnet9", "resnet50"):
        raise HTTPException(status_code=400, detail="model must be 'resnet9' or 'resnet50'")
    try:
        image_bytes = await file.read()
        result = ml_service.predict_disease(image_bytes, model_name=model)
        return result
    except RuntimeError as e:
        return DiseaseDetectionResponse(success=False, error=str(e))
    except Exception as e:
        return DiseaseDetectionResponse(success=False, error=f"Prediction failed: {e}")
