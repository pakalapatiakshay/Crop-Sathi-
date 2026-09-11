from fastapi import APIRouter

from db.schemas import CropRecommendationRequest, CropRecommendationResponse
from services import ml_service

router = APIRouter(tags=["Crop Recommendation"])


@router.post("/predict-crop", response_model=CropRecommendationResponse)
def predict_crop(data: CropRecommendationRequest):
    try:
        result = ml_service.predict_crop(
            n=data.N, p=data.P, k=data.K, ph=data.ph, rainfall=data.rainfall,
            lat=data.lat, lon=data.lon,
            temperature=data.temperature, humidity=data.humidity,
        )
        return result
    except RuntimeError as e:
        return CropRecommendationResponse(success=False, error=str(e))
    except Exception as e:
        return CropRecommendationResponse(success=False, error=f"Prediction failed: {e}")
