from fastapi import APIRouter, Query

from services.weather_service import fetch_weather_full

router = APIRouter(tags=["Weather"])


@router.get("/weather")
def get_weather(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """
    Proxy endpoint for OpenWeatherMap, keeping the API key server-side.
    Returns current weather + basic forecast data.
    """
    try:
        result = fetch_weather_full(lat, lon)
        if result is None:
            return {
                "success": False,
                "error": "Weather data unavailable. Check API key or try again.",
            }
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e)}
