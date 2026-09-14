import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pydantic import ValidationError

from main import sync_task_alert
from models import Task
from schemas import TaskCreate


class TaskReminderTests(unittest.TestCase):
    def test_reminder_requires_due_date_and_assignee(self):
        with self.assertRaises(ValidationError):
            TaskCreate(title="Take bins out", assigned_to=1, reminder_minutes_before=30)
        with self.assertRaises(ValidationError):
            TaskCreate(
                title="Take bins out",
                due_at=datetime(2026, 9, 12, 19, 0, tzinfo=timezone.utc),
                reminder_minutes_before=30,
            )

    def test_due_date_must_include_timezone(self):
        with self.assertRaises(ValidationError):
            TaskCreate(title="Homework", due_at=datetime(2026, 9, 12, 19, 0))

    def test_task_reminder_creates_an_alert_for_assignee(self):
        database = MagicMock()
        database.scalar.return_value = None
        task = Task(
            id=7,
            title="Take bins out",
            assigned_to=2,
            status="pending",
            due_at=datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc),
            reminder_minutes_before=30,
        )

        sync_task_alert(task, database)

        alert = database.add.call_args.args[0]
        self.assertEqual(alert.task_id, 7)
        self.assertEqual(alert.member_id, 2)
        self.assertEqual(alert.scheduled_for, datetime(2026, 9, 12, 23, 30, tzinfo=timezone.utc))
        self.assertIn("Take bins out", alert.message)


if __name__ == "__main__":
    unittest.main()
