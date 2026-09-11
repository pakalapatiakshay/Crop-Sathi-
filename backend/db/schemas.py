from typing import Any, Optional

from pydantic import BaseModel, Field


class CropRecommendationRequest(BaseModel):
    N: int = Field(..., ge=0, le=1000, description="Nitrogen content in soil (kg/ha)")
    P: int = Field(..., ge=0, le=1000, description="Phosphorus content in soil (kg/ha)")
    K: int = Field(..., ge=0, le=1000, description="Potassium content in soil (kg/ha)")
    ph: float = Field(..., ge=0, le=14, description="Soil pH")
    rainfall: float = Field(..., ge=0, le=5000, description="Rainfall (mm)")
    lat: Optional[float] = Field(None, description="Latitude, used to fetch live weather")
    lon: Optional[float] = Field(None, description="Longitude, used to fetch live weather")
    temperature: Optional[float] = Field(None, description="Override temperature (°C) if known")
    humidity: Optional[float] = Field(None, description="Override humidity (%) if known")


class CropRecommendationResponse(BaseModel):
    success: bool
    prediction: Optional[str] = None
    confidence: Optional[float] = None
    top_3: Optional[list[str]] = None
    top_3_confidence: Optional[list[float]] = None
    inputs: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class SoilCoverageResponse(BaseModel):
    success: bool
    districts: int
    blocks: int
    villages: int


class SoilDistrictListResponse(BaseModel):
    success: bool
    districts: list[str]


class SoilBlockListResponse(BaseModel):
    success: bool
    district: str
    blocks: list[str]


class SoilVillage(BaseModel):
    village_name: str
    village_code: int


class SoilVillageListResponse(BaseModel):
    success: bool
    district: str
    block: str
    villages: list[SoilVillage]


class SoilProfile(BaseModel):
    village_name: str
    village_code: int
    district_name: str
    block_name: str
    year: str = Field(..., description="Survey year the profile was taken from")
    N: int = Field(..., description="Nitrogen, on the crop model's feature scale")
    P: int = Field(..., description="Phosphorus, on the crop model's feature scale")
    K: int = Field(..., description="Potassium, on the crop model's feature scale")
    ph: float
    organic_carbon: Optional[float] = Field(None, description="Organic carbon (%)")
    ph_acidic_pct: Optional[float] = Field(None, description="% of samples testing acidic")
    n_low_pct: Optional[float] = Field(None, description="% of samples low in nitrogen")
    p_low_pct: Optional[float] = Field(None, description="% of samples low in phosphorus")
    k_low_pct: Optional[float] = Field(None, description="% of samples low in potassium")
    deficient_micronutrients: list[str] = []
    samples: int = Field(..., description="Number of soil samples behind this profile")


class SoilProfileResponse(BaseModel):
    success: bool
    profile: Optional[SoilProfile] = None
    error: Optional[str] = None


class DiseaseDetectionResponse(BaseModel):
    success: bool
    predicted_class: Optional[str] = None
    plant_name: Optional[str] = None
    disease_status: Optional[str] = None
    confidence: Optional[float] = None
    is_confident: Optional[bool] = None
    model_used: Optional[str] = None
    error: Optional[str] = None


class VoiceStartRequest(BaseModel):
    lang: str = Field("hi", description="Conversation language: 'hi' or 'en'")


class VoiceReply(BaseModel):
    success: bool
    session_id: str
    text: str = Field(..., description="The line the agent should speak")
    action: str = Field(..., description="'listen', 'capture_photo', or 'end'")
    state: str = Field(..., description="Dialogue state after this turn")
    slots: dict[str, Any] = Field(default_factory=dict, description="Filled slots so far")
    data: Optional[dict[str, Any]] = Field(None, description="Raw model output, if any")
    options: list[str] = Field(default_factory=list, description="Choices to offer on screen")
    transcript: Optional[str] = Field(None, description="What the farmer was heard to say")


class VoiceLanguageStatus(BaseModel):
    asr_ready: bool
    tts_ready: bool


class VoiceStatusResponse(BaseModel):
    success: bool
    asr_provider: str
    tts_provider: str
    models_dir: str
    languages: dict[str, VoiceLanguageStatus]


class SyncAction(BaseModel):
    type: str = Field(..., description="'crop_recommendation' or 'disease_detection'")
    payload: dict[str, Any]
    client_id: Optional[str] = Field(None, description="Client-generated id to correlate results")


class SyncRequest(BaseModel):
    actions: list[SyncAction]


class SyncResultItem(BaseModel):
    client_id: Optional[str]
    type: str
    success: bool
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class SyncResponse(BaseModel):
    results: list[SyncResultItem]
