import unittest
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from briefing_service import (
    build_briefing, build_weekend_schedule, delivery_state, next_weekend_range, quote_for_day, joke_for_day,
)


class MorningBriefingTests(unittest.TestCase):
    def test_parent_briefing_includes_family_events_tasks_weather_and_quote(self):
        event = SimpleNamespace(
            title="Soccer practice", start="2026-09-12T17:30:00-04:00", all_day=False,
        )
        task = SimpleNamespace(title="Confirm school form")
        forecast = {"days": [{
            "condition": "Rain", "temperature_min": 60, "temperature_max": 78,
            "recommendations": ["Carry a rain jacket or umbrella."],
        }]}
        message = build_briefing(
            3, "Jordan", [event], [task], forecast, True, date(2026, 9, 12),
            ZoneInfo("America/New_York"),
        )
        self.assertIn("Good morning Jordan!", message)
        self.assertIn("Family activities: 5:30 PM Soccer practice", message)
        self.assertIn("Your tasks: Confirm school form", message)
        self.assertIn("Weather: Rain, 60–78°F", message)
        self.assertIn("Today’s thought:", message)
        self.assertLessEqual(len(message), 500)

    def test_quote_is_stable_for_the_day(self):
        day = date(2026, 9, 12)
        self.assertEqual(quote_for_day(day, 3), quote_for_day(day, 3))
        self.assertEqual(len({quote_for_day(day, member_id) for member_id in (3, 4, 5, 6)}), 4)

    def test_joke_follows_quote_and_rotates_by_member_and_day(self):
        day = date(2026, 9, 14)
        for member in (3, 4, 5, 6):
            message = build_briefing(member, "Alex", [], [], {}, False, day, ZoneInfo("America/New_York"))
            self.assertTrue(message.endswith("A little smile: " + joke_for_day(day, member)))
            self.assertLess(message.index(quote_for_day(day, member)), message.index(joke_for_day(day, member)))
        self.assertEqual(len({joke_for_day(day, member) for member in (3, 4, 5, 6)}), 4)
        self.assertEqual(joke_for_day(day, 3), joke_for_day(day, 3))
        self.assertNotEqual(joke_for_day(day, 3), joke_for_day(date(2026, 9, 15), 3))

    def test_busy_briefing_preserves_complete_quote_and_joke(self):
        day = date(2026, 9, 14)
        event = SimpleNamespace(title="Very long activity " * 20, start="2026-09-14T15:00:00-04:00", all_day=False)
        forecast = {"days": [{"condition": "Rain", "recommendations": ["Bring a rain jacket. " * 30]}]}
        for member in range(3, 17):
            message = build_briefing(member, "A" * 100, [event] * 5,
                [SimpleNamespace(title="Long task " * 30)] * 5, forecast, True, day, ZoneInfo("America/New_York"))
            self.assertLessEqual(len(message), 500)
            self.assertIn(quote_for_day(day, member), message)
            self.assertTrue(message.endswith(joke_for_day(day, member)))
            for label in ("Family activities:", "Your tasks:", "Weather:"):
                self.assertIn(label, message)

    def test_delivery_recovers_later_the_same_day(self):
        zone = ZoneInfo("America/New_York")
        self.assertEqual(delivery_state(datetime(2026, 9, 12, 6, 59, tzinfo=zone), "07:00"), "scheduled")
        self.assertEqual(delivery_state(datetime(2026, 9, 12, 7, 30, tzinfo=zone), "07:00"), "ready")
        self.assertEqual(delivery_state(datetime(2026, 9, 12, 13, 0, tzinfo=zone), "07:00"), "ready")

    def test_next_weekend_skips_the_current_weekend(self):
        self.assertEqual(
            next_weekend_range(date(2026, 9, 12)),
            (date(2026, 9, 19), date(2026, 9, 20)),
        )
        self.assertEqual(
            next_weekend_range(date(2026, 9, 14)),
            (date(2026, 9, 19), date(2026, 9, 20)),
        )

    def test_weekend_schedule_is_personalized_and_compact(self):
        zone = ZoneInfo("America/New_York")
        events = [SimpleNamespace(
            title="Soccer practice", start="2026-09-19T10:00:00-04:00", all_day=False,
        )]
        message = build_weekend_schedule(
            "Alex", events, date(2026, 9, 19), date(2026, 9, 20), zone,
        )
        self.assertIn("Hi Alex", message)
        self.assertIn("Sep 19–20", message)
        self.assertIn("Sat 10:00 AM Soccer practice", message)
        self.assertLessEqual(len(message), 500)


if __name__ == "__main__":
    unittest.main()
