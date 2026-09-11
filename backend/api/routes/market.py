from fastapi import APIRouter
from services import market_service

router = APIRouter(prefix="/market", tags=["Market"])

@router.get("/prices")
async def get_prices():
    """
    Fetch the latest APMC market prices for crops in Jharkhand.
    Uses data.gov.in API with a 4-hour server-side cache.
    """
    prices = await market_service.get_jharkhand_market_prices()
    return {"success": True, "data": prices}
