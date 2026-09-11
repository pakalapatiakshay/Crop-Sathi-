import httpx
import time
import logging
import asyncio
from core.config import DATAGOV_API_KEY

logger = logging.getLogger(__name__)

# Resource ID for APMC Mandi daily prices from data.gov.in
# Note: This resource ID might update occasionally, but this is the standard one for current daily prices.
MANDI_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
CACHE_TTL = 4 * 60 * 60  # 4 hours

# Simple in-memory cache
_market_cache = {
    "timestamp": 0,
    "data": None
}

FALLBACK_MARKET_PRICES = [
    { "crop": "Rice (Paddy)", "market": "Ranchi Mandi", "price": 2320, "prev": 2280, "unit": "₹/quintal" },
    { "crop": "Maize", "market": "Dhanbad APMC", "price": 2145, "prev": 2190, "unit": "₹/quintal" },
    { "crop": "Groundnut", "market": "Bokaro Mandi", "price": 6420, "prev": 6310, "unit": "₹/quintal" },
    { "crop": "Cotton", "market": "Jamshedpur Mandi", "price": 7480, "prev": 7395, "unit": "₹/quintal" },
    { "crop": "Wheat", "market": "Hazaribagh Mandi", "price": 2610, "prev": 2600, "unit": "₹/quintal" },
    { "crop": "Soybean", "market": "Deoghar Mandi", "price": 4890, "prev": 4960, "unit": "₹/quintal" },
]

async def fetch_and_cache_market_data():
    """
    Fetches real-time APMC Mandi prices from data.gov.in for Jharkhand
    and updates the in-memory cache.
    """
    global _market_cache
    current_time = time.time()
    
    if not DATAGOV_API_KEY:
        logger.warning("DATAGOV_API_KEY is not set. Falling back to default data.")
        _market_cache["data"] = FALLBACK_MARKET_PRICES
        _market_cache["timestamp"] = current_time
        return FALLBACK_MARKET_PRICES
        
    url = f"https://api.data.gov.in/resource/{MANDI_RESOURCE_ID}"
    params = {
        "api-key": DATAGOV_API_KEY,
        "format": "json",
        "filters[state]": "Jharkhand",
        "limit": 50
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            records = data.get("records", [])
            if not records:
                logger.warning("No records found for Jharkhand. Using fallback.")
                if not _market_cache["data"]:
                    _market_cache["data"] = FALLBACK_MARKET_PRICES
                return _market_cache["data"]
                
            formatted_prices = []
            seen_crops = set()
            
            # Map API fields to frontend structure
            for record in records:
                crop = record.get("commodity", "").title()
                if crop in seen_crops:
                    continue  # Keep unique crops for display variety
                    
                market = record.get("market", "").title() + " Mandi"
                try:
                    price = float(record.get("modal_price", 0))
                    min_price = float(record.get("min_price", price))
                except ValueError:
                    price = 0
                    min_price = 0
                    
                if price <= 0:
                    continue
                    
                formatted_prices.append({
                    "crop": crop,
                    "market": market,
                    "price": price,
                    "prev": min_price, # Using min_price as 'prev' just to show trend
                    "unit": "₹/quintal"
                })
                seen_crops.add(crop)
                
                if len(formatted_prices) >= 10:
                    break
                    
            if not formatted_prices:
                if not _market_cache["data"]:
                    _market_cache["data"] = FALLBACK_MARKET_PRICES
                return _market_cache["data"]
                
            _market_cache["data"] = formatted_prices
            _market_cache["timestamp"] = current_time
            logger.info("Successfully fetched and cached market data.")
            return formatted_prices
            
    except Exception as e:
        logger.error(f"Failed to fetch market data: {e}")
        if not _market_cache["data"]:
            _market_cache["data"] = FALLBACK_MARKET_PRICES
        return _market_cache["data"]


async def start_periodic_market_fetcher():
    """
    Background task to periodically fetch market prices.
    """
    while True:
        try:
            await fetch_and_cache_market_data()
        except Exception as e:
            logger.error(f"Error in periodic market fetcher: {e}")
        await asyncio.sleep(CACHE_TTL)


async def get_jharkhand_market_prices():
    """
    Returns the cached market prices.
    """
    if not _market_cache["data"]:
        await fetch_and_cache_market_data()
    return _market_cache["data"]
