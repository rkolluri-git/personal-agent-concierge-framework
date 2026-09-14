import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from schemas import AlertCreate, AlertContactUpdate, CalendarAlertRuleUpdate
from main import calendar_reminders_for_event, claim_due_alert


class AlertSchemaTests(unittest.TestCase):
    def test_alert_time_must_include_timezone(self):
        with self.assertRaises(ValidationError):
            AlertCreate(
                member_id=1,
                message="Time to leave",
                scheduled_for=datetime(2026, 9, 12, 19, 0),
            )

    def test_valid_alert_and_contact(self):
        alert = AlertCreate(
            member_id=1,
            message="  Time to leave  ",
            scheduled_for=datetime(2026, 9, 12, 19, 0, tzinfo=timezone.utc),
        )
        contact = AlertContactUpdate(imessage_handle="  family@example.com  ")

        self.assertEqual(alert.message, "Time to leave")
        self.assertEqual(contact.imessage_handle, "family@example.com")
        self.assertTrue(contact.enabled)

    def test_calendar_reminder_limits(self):
        rule = CalendarAlertRuleUpdate(
            member_id=1,
            appointment_reminder_minutes=30,
            leave_reminder_minutes=60,
        )
        self.assertTrue(rule.enabled)
        with self.assertRaises(ValidationError):
            CalendarAlertRuleUpdate(
                member_id=1, appointment_reminder_minutes=10081, leave_reminder_minutes=60,
            )

    def test_leave_reminder_requires_an_event_location(self):
        rule = SimpleNamespace(appointment_reminder_minutes=30, leave_reminder_minutes=60)
        without_location = calendar_reminders_for_event(SimpleNamespace(departure_ready=False), rule)
        with_location = calendar_reminders_for_event(SimpleNamespace(departure_ready=True), rule)
        self.assertEqual(without_location, [("appointment", 30)])
        self.assertEqual(with_location, [("leave", 60), ("appointment", 30)])

    def test_abandoned_message_claim_becomes_uncertain(self):
        abandoned = SimpleNamespace(status="sending")
        database = SimpleNamespace(
            scalars=lambda statement: SimpleNamespace(all=lambda: [abandoned]),
            scalar=lambda statement: None,
            commit=lambda: None,
        )
        self.assertIsNone(claim_due_alert(database))
        self.assertEqual(abandoned.status, "uncertain")

    def test_alert_claim_locks_only_alert_rows_on_postgresql(self):
        statements = []
        database = SimpleNamespace(
            scalars=lambda statement: SimpleNamespace(all=lambda: []),
            scalar=lambda statement: statements.append(statement),
            commit=lambda: None,
        )

        self.assertIsNone(claim_due_alert(database))
        sql = str(statements[0].compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE OF alerts SKIP LOCKED", sql)


if __name__ == "__main__":
    unittest.main()
