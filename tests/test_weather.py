import unittest
from types import SimpleNamespace
from unittest.mock import patch

import weather_service


SETTINGS = SimpleNamespace(
    location_name="Example City, Example Region, US",
    latitude=0.0,
    longitude=0.0,
    timezone_name="America/New_York",
    rain_probability_percent=50,
    jacket_below_fahrenheit=55,
    dress_light_above_fahrenheit=80,
)


class WeatherTests(unittest.TestCase):
    def test_geocode_uses_zip_from_a_friendly_us_location(self):
        response = {
            "results": [{
                "name": "Example City",
                "admin1": "Example Region",
                "country_code": "US",
                "latitude": 0.0,
                "longitude": 0.0,
                "timezone": "America/New_York",
            }]
        }
        with patch.object(weather_service, "get_json", return_value=response) as get_json:
            result = weather_service.geocode_location("Example City 00000")
        self.assertEqual(get_json.call_args.args[1]["name"], "00000")
        self.assertEqual(get_json.call_args.args[1]["countryCode"], "US")
        self.assertEqual(result["location_name"], "Example City, Example Region, US")

    def test_family_rules_cover_layers_rain_uv_and_wind(self):
        advice = weather_service.family_recommendations(
            {
                "apparent_temperature_min": 45,
                "apparent_temperature_max": 84,
                "precipitation_probability": 70,
                "uv_index": 6,
                "wind_gusts_max": 35,
                "weather_code": 61,
            },
            SETTINGS,
        )
        self.assertIn("Wear light layers and keep a jacket for the cooler hours.", advice)
        self.assertIn("Carry a rain jacket or umbrella.", advice)
        self.assertTrue(any("sunscreen" in item for item in advice))
        self.assertTrue(any("gusty" in item for item in advice))

    def test_forecast_is_reduced_to_family_safe_fields(self):
        response = {
            "current": {"temperature_2m": 72, "apparent_temperature": 74, "weather_code": 1},
            "daily": {
                "time": ["2026-09-12"],
                "weather_code": [61],
                "temperature_2m_max": [82],
                "temperature_2m_min": [64],
                "apparent_temperature_max": [84],
                "apparent_temperature_min": [63],
                "precipitation_probability_max": [70],
                "uv_index_max": [5],
                "wind_gusts_10m_max": [20],
            },
        }
        with patch.object(weather_service, "get_json", return_value=response):
            forecast = weather_service.weather_forecast(SETTINGS)
        self.assertEqual(forecast["location"], SETTINGS.location_name)
        self.assertEqual(forecast["current"]["condition"], "Partly cloudy")
        self.assertEqual(forecast["days"][0]["condition"], "Rain")
        self.assertIn("Carry a rain jacket or umbrella.", forecast["days"][0]["recommendations"])

    def test_unknown_weather_code_has_a_safe_label(self):
        self.assertEqual(weather_service.condition_label(999), "Mixed conditions")


if __name__ == "__main__":
    unittest.main()
