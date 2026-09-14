"""Minimal server-side Google Places autocomplete adapter."""
import json
import os
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_PLACES_API_KEY", "").strip())


@lru_cache(maxsize=256)
def address_suggestions(query: str) -> list[dict]:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not key:
        raise ValueError("Google Places is not configured")
    request = Request(
        AUTOCOMPLETE_URL,
        data=json.dumps({
            "input": query,
            "includedRegionCodes": [os.environ.get("FAMILY_COUNTRY", "US").lower()],
            "languageCode": "en",
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "suggestions.placePrediction.placeId,suggestions.placePrediction.text",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Google Places is unavailable") from error
    results = []
    for suggestion in data.get("suggestions", [])[:5]:
        prediction = suggestion.get("placePrediction") or {}
        text = (prediction.get("text") or {}).get("text", "").strip()
        if text:
            results.append({"place_id": prediction.get("placeId", ""), "address": text})
    return results
