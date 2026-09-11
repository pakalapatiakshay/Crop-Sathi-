from fastapi import APIRouter, HTTPException

from db.schemas import (
    SoilBlockListResponse,
    SoilCoverageResponse,
    SoilDistrictListResponse,
    SoilProfileResponse,
    SoilVillageListResponse,
)
from services import soil_service

router = APIRouter(prefix="/soil", tags=["Soil Profiles"])


def _require_loaded() -> None:
    if not soil_service.is_loaded():
        raise HTTPException(
            status_code=503,
            detail="Soil profiles are not loaded. Run `python scripts/build_soil_profiles.py`.",
        )


@router.get("/coverage", response_model=SoilCoverageResponse)
def coverage():
    """How many districts / blocks / villages have a measured soil profile."""
    _require_loaded()
    return SoilCoverageResponse(success=True, **soil_service.summary())


@router.get("/districts", response_model=SoilDistrictListResponse)
def districts():
    _require_loaded()
    return SoilDistrictListResponse(success=True, districts=soil_service.list_districts())


@router.get("/districts/{district}/blocks", response_model=SoilBlockListResponse)
def blocks(district: str):
    _require_loaded()
    found = soil_service.list_blocks(district)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Unknown district '{district}'")
    return SoilBlockListResponse(success=True, district=district, blocks=found)


@router.get("/districts/{district}/blocks/{block}/villages", response_model=SoilVillageListResponse)
def villages(district: str, block: str):
    _require_loaded()
    found = soil_service.list_villages(district, block)
    if found is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown district/block '{district}/{block}'"
        )
    return SoilVillageListResponse(
        success=True, district=district, block=block, villages=found
    )


@router.get("/village/{village_code}", response_model=SoilProfileResponse)
def village_profile(village_code: int):
    """Measured N/P/K/pH for one village, used to pre-fill the recommendation form."""
    _require_loaded()
    profile = soil_service.get_profile(village_code)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No soil profile for village {village_code}")
    return SoilProfileResponse(success=True, profile=profile)
