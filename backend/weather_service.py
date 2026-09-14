"""Weather data and deterministic family guidance."""
import json
import re
from regional_settings import REGIONAL
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


OPENER = build_opener(ProxyHandler({}))
USER_AGENT = "FamilyAgent/0.1 (self-hosted family weather briefing)"


def get_json(url, params):
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
    with OPENER.open(request, timeout=20) as response:
        return json.load(response)


def geocode_location(query):
    postal_code = re.search(r"\b\d{5}(?:-\d{4})?\b", query) if REGIONAL.country == "US" else None
    search_name = postal_code.group(0)[:5] if postal_code else query
    params = {"name": search_name, "count": 5, "language": "en", "format": "json"}
    params["countryCode"] = REGIONAL.country
    data = get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params,
    )
    results = data.get("results") or []
    if not results:
        raise ValueError("Location not found")
    place = results[0]
    label_parts = [place.get("name"), place.get("admin1"), place.get("country_code")]
    return {
        "location_name": ", ".join(part for part in label_parts if part),
        "latitude": float(place["latitude"]),
        "longitude": float(place["longitude"]),
        "timezone_name": place.get("timezone") or REGIONAL.timezone,
    }


def condition_label(code):
    if code == 0:
        return "Clear"
    if code in {1, 2, 3}:
        return "Partly cloudy" if code < 3 else "Cloudy"
    if code in {45, 48}:
        return "Foggy"
    if code in {51, 53, 55, 56, 57}:
        return "Drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "Snow"
    if code in {95, 96, 99}:
        return "Thunderstorms"
    return "Mixed conditions"


def family_recommendations(day, settings):
    rain = day.get("precipitation_probability") or 0
    low = day.get("apparent_temperature_min")
    high = day.get("apparent_temperature_max")
    uv = day.get("uv_index") or 0
    gusts = day.get("wind_gusts_max") or 0
    recommendations = []

    cold = low is not None and low <= settings.jacket_below_fahrenheit
    hot = high is not None and high >= settings.dress_light_above_fahrenheit
    if cold and hot:
        recommendations.append("Wear light layers and keep a jacket for the cooler hours.")
    elif cold:
        recommendations.append("Wear or carry a jacket.")
    elif hot:
        recommendations.append("Dress light and carry water.")
    if rain >= settings.rain_probability_percent:
        recommendations.append("Carry a rain jacket or umbrella.")
    if uv >= 3:
        recommendations.append("Use sunscreen and consider sunglasses for outdoor time.")
    if gusts >= 30:
        recommendations.append("Expect gusty wind and secure loose outdoor items.")
    if day.get("weather_code") in {95, 96, 99}:
        recommendations.append("Check official weather alerts before outdoor plans.")
    if not recommendations:
        recommendations.append("No special weather gear is suggested.")
    return recommendations


def weather_forecast(settings):
    data = get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "timezone": settings.timezone_name,
            "forecast_days": 3,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "current": "temperature_2m,apparent_temperature,weather_code",
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "apparent_temperature_max,apparent_temperature_min,"
                "precipitation_probability_max,uv_index_max,wind_gusts_10m_max"
            ),
        },
    )
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    days = []
    for index, value in enumerate(dates):
        def at(key, default=None):
            values = daily.get(key) or []
            return values[index] if index < len(values) else default

        day = {
            "date": value,
            "weather_code": at("weather_code", -1),
            "temperature_max": at("temperature_2m_max"),
            "temperature_min": at("temperature_2m_min"),
            "apparent_temperature_max": at("apparent_temperature_max"),
            "apparent_temperature_min": at("apparent_temperature_min"),
            "precipitation_probability": at("precipitation_probability_max", 0),
            "uv_index": at("uv_index_max", 0),
            "wind_gusts_max": at("wind_gusts_10m_max", 0),
        }
        day["condition"] = condition_label(day["weather_code"])
        day["recommendations"] = family_recommendations(day, settings)
        for key in ("temperature_max", "temperature_min", "apparent_temperature_max", "apparent_temperature_min"):
            day[key] = REGIONAL.temperature(day[key])
        if REGIONAL.units == "metric":
            day["wind_gusts_max"] = round(day["wind_gusts_max"] * 1.609344, 1) if day["wind_gusts_max"] is not None else None
        days.append(day)
    current = data.get("current") or {}
    return {
        "units": {"temperature": "°C" if REGIONAL.units == "metric" else "°F", "wind_speed": "km/h" if REGIONAL.units == "metric" else "mph"},
        "location": settings.location_name,
        "timezone": settings.timezone_name,
        "current": {
            "temperature": REGIONAL.temperature(current.get("temperature_2m")),
            "apparent_temperature": REGIONAL.temperature(current.get("apparent_temperature")),
            "condition": condition_label(current.get("weather_code", -1)),
        },
        "days": days,
        "provider": "Open-Meteo",
        "attribution_url": "https://open-meteo.com/",
    }
