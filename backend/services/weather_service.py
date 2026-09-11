from typing import Any, Optional, Tuple

import requests

from core.config import OPENWEATHER_API_KEY

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def fetch_weather(lat: float, lon: float) -> Optional[Tuple[float, float]]:
    """Returns (temperature_celsius, humidity_pct), or None if unavailable."""
    if not OPENWEATHER_API_KEY:
        return None
    try:
        response = requests.get(
            OPENWEATHER_URL,
            params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=5,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        main = data.get("main", {})
        return main.get("temp"), main.get("humidity")
    except requests.exceptions.RequestException:
        return None


def fetch_weather_full(lat: float, lon: float) -> Optional[dict[str, Any]]:
    """
    Returns comprehensive weather data for the frontend weather page.
    Includes current conditions and a 5-day/3-hour forecast collapsed to daily.
    Returns None if the API key is missing or the request fails.
    """
    if not OPENWEATHER_API_KEY:
        return None
    try:
        # Current weather
        current_resp = requests.get(
            OPENWEATHER_URL,
            params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=5,
        )
        if current_resp.status_code != 200:
            return None
        current = current_resp.json()

        main = current.get("main", {})
        wind = current.get("wind", {})
        weather_desc = current.get("weather", [{}])[0]
        clouds = current.get("clouds", {})

        result: dict[str, Any] = {
            "current": {
                "temp": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "humidity": main.get("humidity"),
                "pressure": main.get("pressure"),
                "wind_speed": wind.get("speed"),
                "wind_deg": wind.get("deg"),
                "description": weather_desc.get("description", ""),
                "icon": weather_desc.get("icon", ""),
                "clouds": clouds.get("all", 0),
                "city": current.get("name", ""),
            },
            "forecast": [],
        }

        # 5-day forecast
        forecast_resp = requests.get(
            OPENWEATHER_FORECAST_URL,
            params={"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=5,
        )
        if forecast_resp.status_code == 200:
            forecast_data = forecast_resp.json()
            # Collapse 3-hour intervals to daily summaries
            daily: dict[str, dict[str, Any]] = {}
            for item in forecast_data.get("list", []):
                date = item["dt_txt"].split(" ")[0]
                if date not in daily:
                    daily[date] = {
                        "date": date,
                        "temps": [],
                        "humidity": [],
                        "rain_chance": 0,
                        "description": "",
                        "icon": "",
                    }
                day = daily[date]
                day["temps"].append(item["main"]["temp"])
                day["humidity"].append(item["main"]["humidity"])
                pop = item.get("pop", 0)
                if pop > day["rain_chance"]:
                    day["rain_chance"] = pop
                # Use noon weather description if available
                if "12:00:00" in item["dt_txt"]:
                    day["description"] = item["weather"][0].get("description", "")
                    day["icon"] = item["weather"][0].get("icon", "")
                elif not day["description"]:
                    day["description"] = item["weather"][0].get("description", "")
                    day["icon"] = item["weather"][0].get("icon", "")

            for date in sorted(daily.keys())[:7]:
                d = daily[date]
                temps = d["temps"]
                result["forecast"].append({
                    "date": d["date"],
                    "temp_max": round(max(temps), 1),
                    "temp_min": round(min(temps), 1),
                    "humidity": round(sum(d["humidity"]) / len(d["humidity"])),
                    "rain_chance": round(d["rain_chance"] * 100),
                    "description": d["description"],
                    "icon": d["icon"],
                })

        return result
    except requests.exceptions.RequestException:
        return None

