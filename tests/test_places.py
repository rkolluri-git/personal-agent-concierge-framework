import io
import json
import os
import unittest
from unittest.mock import patch

from places_service import address_suggestions, configured


class PlacesTests(unittest.TestCase):
    def test_configuration_requires_nonempty_key(self):
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": ""}):
            self.assertFalse(configured())
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "secret"}):
            self.assertTrue(configured())

    def test_autocomplete_returns_address_text_without_exposing_key(self):
        response = io.BytesIO(json.dumps({"suggestions": [
            {"placePrediction": {"placeId": "one", "text": {"text": "100 Main St, Example City, GA"}}},
            {"queryPrediction": {"text": {"text": "ignored query"}}},
        ]}).encode())
        captured = []

        def fake_open(request, timeout):
            captured.append(request)
            return response

        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "secret", "FAMILY_COUNTRY": "US"}), \
             patch("places_service.urlopen", side_effect=fake_open):
            result = address_suggestions("100 Main")
        self.assertEqual(result, [{"place_id": "one", "address": "100 Main St, Example City, GA"}])
        self.assertNotIn("secret", captured[0].full_url)
        self.assertEqual(captured[0].headers["X-goog-api-key"], "secret")


if __name__ == "__main__":
    unittest.main()
