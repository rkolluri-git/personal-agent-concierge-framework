import unittest
from datetime import date

from pydantic import ValidationError

from schemas import CommuteScheduleUpdate
from school_calendar_service import parse_school_calendar_text, school_year_for


SAMPLE = """
AUGUST
3* Monday FIRST DAY OF SCHOOL
17 Monday Digital Learning Day
SEPTEMBER
7 Monday Labor Day Holiday – Schools Closed
21-25 Monday – Friday Fall Break – Student/Teacher Holidays
NOVEMBER
3* Tuesday Election Day (Student Holiday; Local School Professional Learning Day)
23-27 Monday – Friday Thanksgiving Holidays – Student/Teacher Holidays
DECEMBER
21-31 Inclusive Winter Holidays – Student/Teacher Holidays
JANUARY
1 Friday Winter Holidays – Student/Teacher Holidays
4* Monday Student Holiday; Teacher Workdays
18 Monday MLK, Jr. Holiday – Schools Closed
FEBRUARY
15-19 Monday – Friday Winter Break – Student/Teacher Holidays
MARCH
1 Monday Digital Learning Day
APRIL
5-9 Monday-Friday Spring Break – Student/Teacher Holidays
MAY
19* Wednesday LAST DAY OF SCHOOL
"""


class CommuteTests(unittest.TestCase):
    def test_schedule_supports_selected_weekdays(self):
        value = CommuteScheduleUpdate(
            member_id=1, label="Jordan work", kind="work",
            destination_address="100 Main Street", send_time="07:15",
            weekdays=[4, 0, 2], enabled=True,
        )
        self.assertEqual(value.weekdays, [0, 2, 4])
        with self.assertRaises(ValidationError):
            CommuteScheduleUpdate(
                member_id=1, label="Work", kind="work", destination_address="100 Main Street",
                send_time="07:15", weekdays=[0, 0],
            )

    def test_school_calendar_parses_regular_day_boundaries_and_breaks(self):
        result = parse_school_calendar_text(SAMPLE, "2026-2027")
        self.assertEqual(result["first_day"], "2026-08-03")
        self.assertEqual(result["last_day"], "2027-05-19")
        self.assertIn("2026-09-23", result["excluded_dates"])
        self.assertIn("2027-03-01", result["excluded_dates"])
        self.assertNotIn("2026-09-14", result["excluded_dates"])

    def test_school_year_changes_in_july(self):
        self.assertEqual(school_year_for(date(2027, 6, 30)), "2026-2027")
        self.assertEqual(school_year_for(date(2027, 7, 1)), "2027-2028")


if __name__ == "__main__":
    unittest.main()
