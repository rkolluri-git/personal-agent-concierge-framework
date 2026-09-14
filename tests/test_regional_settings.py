import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from regional_settings import RegionalSettings
import school_calendar_service as school
import weather_service as weather
from briefing_service import weather_summary
from test_weather import SETTINGS


class RegionalTests(unittest.TestCase):
    def region(self, locale='en-IN', **values):
        return RegionalSettings.from_env(dict(FAMILY_LOCALE=locale, FAMILY_TIMEZONE='Asia/Kolkata', **values))

    def test_country_and_units_follow_locale(self):
        india = self.region()
        self.assertEqual((india.country, india.units, india.school_calendar), ('IN', 'metric', 'none'))
        self.assertEqual(india.temperature(32), 0)
        self.assertEqual(india.distance(1500), '1.5 km')
        us = RegionalSettings.from_env({})
        self.assertEqual(us.distance(1609.344), '1.0 mi')
        self.assertEqual(us.temperature(32), 32)
        self.assertIsNone(india.temperature(None))

    def test_invalid_configuration_fails(self):
        for key, value in [('FAMILY_LOCALE', 'invalid'), ('FAMILY_COUNTRY', 'USA'),
                           ('FAMILY_UNITS', 'unknown'), ('FAMILY_SCHOOL_CALENDAR', 'unknown')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                RegionalSettings.from_env({key: value})
        with self.assertRaises(ZoneInfoNotFoundError):
            RegionalSettings.from_env({'FAMILY_TIMEZONE': 'Mars/Olympus'})

    def test_non_us_postal_codes_are_not_truncated_or_sent_to_us(self):
        for locale, query, country in [('en-IN', '560001', 'IN'), ('de-DE', '10115', 'DE'), ('en-GB', 'SW1A 1AA', 'GB')]:
            with patch.object(weather, 'REGIONAL', self.region(locale)), patch.object(weather, 'get_json', return_value={'results': []}) as fetch:
                with self.assertRaises(ValueError):
                    weather.geocode_location(query)
                self.assertEqual(fetch.call_args.args[1]['name'], query)
                self.assertEqual(fetch.call_args.args[1]['countryCode'], country)

    def test_metric_forecast_preserves_clothing_rules_and_briefing_units(self):
        raw = {'current': {'temperature_2m': 68}, 'daily': {
            'time': ['2026-09-13'], 'temperature_2m_min': [32], 'temperature_2m_max': [68],
            'apparent_temperature_min': [40], 'apparent_temperature_max': [68],
            'wind_gusts_10m_max': [35]}}
        with patch.object(weather, 'REGIONAL', self.region()), patch.object(weather, 'get_json', return_value=raw):
            forecast = weather.weather_forecast(SETTINGS)
        self.assertEqual(forecast['current']['temperature'], 20)
        self.assertEqual(forecast['days'][0]['temperature_min'], 0)
        self.assertEqual(forecast['units']['temperature'], '°C')
        self.assertIn('Wear or carry a jacket.', forecast['days'][0]['recommendations'])
        self.assertTrue(any('gusty' in text for text in forecast['days'][0]['recommendations']))
        self.assertIn('0–20°C', weather_summary(forecast))

    def test_custom_calendar_supports_non_monday_school_week_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            value = {'first_day': '2026-04-01', 'last_day': '2027-03-31',
                     'weekdays': [6, 0, 1, 2, 3], 'excluded_dates': ['2026-09-14']}
            (path / 'school-calendar.json').write_text(json.dumps(value))
            with patch.object(school, 'CONFIG', path), patch.object(school, 'REGIONAL', self.region(FAMILY_SCHOOL_CALENDAR='custom')):
                self.assertTrue(school.school_day_status(date(2026, 9, 13))['is_school_day'])
                self.assertFalse(school.school_day_status(date(2026, 9, 14))['is_school_day'])
                self.assertFalse(school.school_day_status(date(2026, 9, 18))['is_school_day'])
                with self.assertRaises(ValueError):
                    school.school_day_status(date(2027, 4, 1))
                value['weekdays'] = [7]
                (path / 'school-calendar.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    school.school_day_status(date(2026, 9, 13))

    def test_disabled_calendar_does_not_fetch_cobb(self):
        with patch.object(school, 'REGIONAL', self.region()), patch.object(school, 'fetch_school_calendar') as fetch:
            with self.assertRaises(ValueError):
                school.school_day_status(date(2026, 9, 13))
            fetch.assert_not_called()

    def test_household_timezone_handles_half_hour_offsets_and_dst(self):
        instant = datetime.fromisoformat('2026-09-13T20:00:00+00:00')
        self.assertEqual(instant.astimezone(ZoneInfo(self.region().timezone)).isoformat(), '2026-09-14T01:30:00+05:30')
        london = ZoneInfo('Europe/London')
        self.assertEqual(datetime(2026, 7, 1, tzinfo=london).utcoffset().total_seconds(), 3600)
        self.assertEqual(datetime(2026, 12, 1, tzinfo=london).utcoffset().total_seconds(), 0)
