import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException

from main import save_departure_trip
from schemas import DepartureTripUpdate


class DeparturePreferenceTests(unittest.TestCase):
    def test_round_trip_preference_is_created(self):
        database = MagicMock()
        database.get.return_value = None
        event_id = "a" * 32

        result = save_departure_trip(
            event_id,
            DepartureTripUpdate(round_trip=True),
            database,
        )

        self.assertEqual(result.event_id, event_id)
        self.assertTrue(result.round_trip)
        database.add.assert_called_once_with(result)
        database.commit.assert_called_once()
        database.refresh.assert_called_once_with(result)

    def test_invalid_calendar_event_id_is_rejected(self):
        database = MagicMock()

        with self.assertRaises(HTTPException) as raised:
            save_departure_trip(
                "not-a-calendar-event",
                DepartureTripUpdate(round_trip=True),
                database,
            )

        self.assertEqual(raised.exception.status_code, 422)
        database.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
