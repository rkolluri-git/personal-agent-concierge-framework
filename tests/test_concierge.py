import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from concierge_workflow import preview_request
from main import update_concierge_plan
from schemas import ConciergePlanUpdate


class ConciergeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 12, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        self.members = ["Jordan", "Taylor", "Alex", "Sam"]
        self.profiles = [
            {"name": "Jordan", "role": "parent", "age": None},
            {"name": "Taylor", "role": "parent", "age": None},
            {"name": "Alex", "role": "child", "age": 15},
            {"name": "Sam", "role": "child", "age": 12},
        ]

    def test_calendar_request_extracts_people_date_and_time(self):
        plan = preview_request(
            "Schedule Alex’s dentist appointment tomorrow at 3:30 PM and notify Jordan and Taylor.",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["request_type"], "calendar")
        self.assertEqual(plan["date"], "2026-09-13")
        self.assertEqual(plan["time"], "15:30")
        self.assertEqual(plan["title"], "Alex’s dentist appointment")
        self.assertEqual(plan["mentioned_members"], ["Alex", "Jordan", "Taylor"])
        self.assertEqual(plan["primary_member"], "Alex")
        self.assertEqual(plan["notification_members"], ["Jordan", "Taylor"])
        self.assertIn("which parent will drive", plan["missing_fields"])

    def test_three_named_time_ranges_become_three_calendar_events(self):
        plan = preview_request(
            "For tomorrow Alex has speech and debate 3:30 to 4 and 4 to 4:30 is therapy "
            "and Scout meeting from 7 to 7:30",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["request_type"], "calendar")
        self.assertEqual(plan["date"], "2026-09-13")
        self.assertEqual(plan["title"], "3 calendar events for Alex")
        self.assertEqual(plan["calendar_events"], [
            {"title": "Speech and debate", "start_time": "15:30", "end_time": "16:00", "time_assumed": True},
            {"title": "Therapy", "start_time": "16:00", "end_time": "16:30", "time_assumed": True},
            {"title": "Scout meeting", "start_time": "19:00", "end_time": "19:30", "time_assumed": True},
        ])
        self.assertIn("Prepare 3 calendar events for review", plan["proposed_actions"])
        self.assertNotIn("time", plan["missing_fields"])

    def test_iso_date_is_not_mistaken_for_a_time_range(self):
        plan = preview_request(
            "Schedule Alex's dentist appointment 2026-09-14 at 3 PM",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["date"], "2026-09-14")
        self.assertEqual(plan["time"], "15:00")
        self.assertEqual(plan["calendar_events"], [])

    def test_back_to_back_events_can_be_combined(self):
        plan = preview_request(
            "For tomorrow Alex has speech and debate 3:30 to 4 and 4 to 4:30 is therapy "
            "and Scout meeting from 7 to 7:30",
            self.members,
            self.now,
            self.profiles,
            combine_adjacent_events=True,
        )
        self.assertEqual(plan["source_event_count"], 3)
        self.assertTrue(plan["combine_adjacent_events"])
        self.assertEqual(len(plan["calendar_events"]), 2)
        self.assertEqual(plan["calendar_events"][0]["title"], "Speech and debate + Therapy")
        self.assertEqual(plan["calendar_events"][0]["start_time"], "15:30")
        self.assertEqual(plan["calendar_events"][0]["end_time"], "16:30")
        self.assertEqual(len(plan["calendar_events"][0]["segments"]), 2)
        self.assertEqual(plan["calendar_events"][1]["title"], "Scout meeting")

    def test_llm_interpretation_flows_through_langgraph_and_local_rules(self):
        llm_plan = {
            "request_type": "calendar",
            "title": "Two calendar events",
            "primary_member": "Alex",
            "notification_members": ["Jordan"],
            "date": "2026-09-13",
            "time": "15:30",
            "calendar_events": [
                {"title": "Speech", "start_time": "15:30", "end_time": "16:00", "time_assumed": False},
                {"title": "Therapy", "start_time": "16:00", "end_time": "16:30", "time_assumed": False},
            ],
            "repeat_interval": "none",
        }
        with patch("concierge_llm.interpret", return_value=llm_plan):
            plan = preview_request("Please organize this for Alex tomorrow", self.members, self.now, self.profiles)

        self.assertTrue(plan["llm_used"])
        self.assertEqual(plan["request_type"], "calendar")
        self.assertEqual(plan["primary_member"], "Alex")
        self.assertEqual(plan["notification_members"], ["Jordan"])
        self.assertEqual(len(plan["calendar_events"]), 2)
        self.assertTrue(plan["requires_parent_driver"])

    def test_parent_alias_and_minor_transport_rule(self):
        plan = preview_request(
            "Schedule appointment for tomorrow at 3:30pm for Alex and notify parents",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["title"], "Appointment for Alex")
        self.assertEqual(plan["primary_member"], "Alex")
        self.assertEqual(plan["notification_members"], ["Jordan", "Taylor"])
        self.assertEqual(plan["subject_age"], 15)
        self.assertTrue(plan["requires_parent_driver"])
        self.assertEqual(plan["driver_options"], ["Jordan", "Taylor"])
        self.assertIn("which parent will drive", plan["missing_fields"])

    def test_unknown_child_age_is_not_guessed(self):
        profiles = [*self.profiles]
        profiles[2] = {"name": "Alex", "role": "child", "age": None}
        plan = preview_request(
            "Schedule appointment for tomorrow at 3:30pm for Alex and notify parents",
            self.members,
            self.now,
            profiles,
        )
        self.assertIsNone(plan["requires_parent_driver"])
        self.assertIn("Alex’s age in the private family profile", plan["missing_fields"])

    def test_named_parent_driver_completes_minor_transport_plan(self):
        plan = preview_request(
            "Schedule appointment for Alex tomorrow at 3:30pm, Jordan will drive, and notify parents",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["primary_member"], "Alex")
        self.assertEqual(plan["driver"], "Jordan")
        self.assertNotIn("which parent will drive", plan["missing_fields"])

    def test_reviewed_parent_driver_completes_minor_transport_plan(self):
        plan = preview_request(
            "Schedule appointment for tomorrow at 3:30pm for Alex and notify parents",
            self.members,
            self.now,
            self.profiles,
            "Taylor",
        )
        self.assertEqual(plan["driver"], "Taylor")
        self.assertNotIn("which parent will drive", plan["missing_fields"])
        self.assertIn("Plan for Taylor to drive Alex", plan["proposed_actions"])

    def test_school_appointment_can_require_pickup_without_dropoff(self):
        plan = preview_request(
            "Schedule Alex's appointment tomorrow at 3:30 PM; Alex continues at school and Taylor will pick up",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["transportation_mode"], "pickup_only")
        self.assertFalse(plan["requires_parent_driver"])
        self.assertIsNone(plan["driver"])
        self.assertTrue(plan["requires_pickup"])
        self.assertEqual(plan["pickup_by"], "Taylor")
        self.assertNotIn("which parent will drive", plan["missing_fields"])
        self.assertNotIn("who will pick up", plan["missing_fields"])
        self.assertIn("No drop-off needed because Alex is already at school", plan["proposed_actions"])

    def test_review_can_assign_uber_for_school_pickup(self):
        plan = preview_request(
            "Schedule appointment for Alex tomorrow at 3:30 PM",
            self.members,
            self.now,
            self.profiles,
            transportation_mode="pickup_only",
            pickup_by="Uber",
        )
        self.assertEqual(plan["pickup_options"], ["Jordan", "Taylor", "Uber", "Undecided"])
        self.assertEqual(plan["pickup_by"], "Uber")
        self.assertEqual(plan["missing_fields"], [])
        self.assertIn("Plan for Uber to pick up Alex", plan["proposed_actions"])

    def test_undecided_is_a_recorded_pickup_choice(self):
        plan = preview_request(
            "Schedule appointment for Alex tomorrow at 3:30 PM",
            self.members,
            self.now,
            self.profiles,
            transportation_mode="pickup_only",
            pickup_by="Undecided",
        )
        self.assertEqual(plan["pickup_by"], "Undecided")
        self.assertEqual(plan["missing_fields"], [])
        self.assertIn("Keep Alex’s pickup assignment undecided", plan["proposed_actions"])

    def test_review_can_mark_no_transportation_needed(self):
        plan = preview_request(
            "Schedule appointment for Alex tomorrow at 3:30 PM",
            self.members,
            self.now,
            self.profiles,
            transportation_mode="none",
        )
        self.assertEqual(plan["transportation_mode"], "none")
        self.assertFalse(plan["requires_pickup"])
        self.assertIsNone(plan["driver"])
        self.assertIsNone(plan["pickup_by"])
        self.assertEqual(plan["missing_fields"], [])

    def test_ordinary_child_task_does_not_require_transportation(self):
        plan = preview_request(
            "Task Alex to take out recycling",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertFalse(plan["requires_parent_driver"])
        self.assertIsNone(plan["transportation_mode"])
        self.assertFalse(plan["requires_pickup"])

    def test_revised_inbox_plan_and_request_text_are_saved(self):
        members = [SimpleNamespace(**profile) for profile in self.profiles]
        item = SimpleNamespace(
            id=7,
            status="pending",
            member_name="Jordan",
            encrypted_request="Schedule appointment for Alex tomorrow at 3:30 PM",
            encrypted_plan="{}",
            received_at=self.now,
            processed_at=None,
        )
        database = SimpleNamespace(
            get=lambda model, item_id: item if item_id == 7 else None,
            scalars=lambda statement: SimpleNamespace(all=lambda: members),
            commit=lambda: None,
            refresh=lambda value: None,
        )
        revised_text = (
            "Schedule appointment for Alex tomorrow at 3:30 PM; "
            "Alex continues at school and Taylor will pick up"
        )
        payload = ConciergePlanUpdate(
            text=revised_text,
            transportation_mode="pickup_only",
            pickup_by="Taylor",
        )

        with patch("sensitive_crypto.encrypt_text", side_effect=lambda value: value):
            saved = update_concierge_plan(7, payload, database)

        self.assertEqual(item.encrypted_request, revised_text)
        persisted = json.loads(item.encrypted_plan)
        self.assertEqual(persisted["transportation_mode"], "pickup_only")
        self.assertEqual(persisted["pickup_by"], "Taylor")
        self.assertEqual(saved["request_text"], revised_text)
        self.assertEqual(saved["plan"]["pickup_by"], "Taylor")
        self.assertEqual(item.status, "handled")
        self.assertIsNotNone(item.processed_at)

    def test_task_request_is_ready_for_reviewed_creation(self):
        plan = preview_request("Task Alex to take out recycling tomorrow at 6 PM", self.members, self.now)
        self.assertEqual(plan["request_type"], "task")
        self.assertEqual(plan["title"], "Take out recycling")
        self.assertEqual(plan["primary_member"], "Alex")
        self.assertEqual(plan["notification_members"], [])
        self.assertEqual(plan["date"], "2026-09-13")
        self.assertEqual(plan["time"], "18:00")
        self.assertEqual(plan["missing_fields"], [])

    def test_task_with_a_date_waits_for_a_time(self):
        plan = preview_request("Task Alex to take out recycling tomorrow", self.members, self.now)
        self.assertEqual(plan["missing_fields"], ["time"])

    def test_weekly_task_uses_the_next_named_weekday_and_time(self):
        plan = preview_request(
            "Remind Alex to take the bins out every Monday at 7 PM",
            self.members,
            self.now,
            self.profiles,
        )
        self.assertEqual(plan["request_type"], "task")
        self.assertEqual(plan["primary_member"], "Alex")
        self.assertEqual(plan["date"], "2026-09-14")
        self.assertEqual(plan["time"], "19:00")
        self.assertEqual(plan["repeat_interval"], "weekly")
        self.assertIn("weekly task", plan["proposed_actions"][0])

    def test_incoming_request_resolves_me_to_the_sender(self):
        plan = preview_request(
            "Remind me tomorrow for meal prep at 9 AM",
            self.members,
            self.now,
            self.profiles,
            requester_name="Taylor",
        )
        self.assertEqual(plan["request_type"], "task")
        self.assertEqual(plan["primary_member"], "Taylor")
        self.assertEqual(plan["title"], "Meal prep")
        self.assertEqual(plan["date"], "2026-09-13")
        self.assertEqual(plan["time"], "09:00")
        self.assertEqual(plan["missing_fields"], [])

    def test_repeated_name_can_be_both_requester_and_notification_recipient(self):
        plan = preview_request(
            "Schedule Jordan's meeting tomorrow at 9 AM and notify Jordan and Taylor",
            self.members,
            self.now,
        )
        self.assertEqual(plan["primary_member"], "Jordan")
        self.assertEqual(plan["notification_members"], ["Jordan", "Taylor"])

    def test_unclear_request_stays_in_review(self):
        plan = preview_request("Please handle this for the family", self.members, self.now)
        self.assertEqual(plan["request_type"], "needs_review")
        self.assertIn("whether this should be a task or calendar event", plan["missing_fields"])
        self.assertIn("family member", plan["missing_fields"])


if __name__ == "__main__":
    unittest.main()
