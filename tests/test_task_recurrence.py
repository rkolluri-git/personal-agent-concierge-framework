from datetime import datetime, timezone

from task_recurrence import next_weekly_due


def test_weekly_task_advances_exactly_one_week_when_completed_early():
    current = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    assert next_weekly_due(current, now) == datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc)


def test_weekly_task_skips_missed_occurrences():
    current = datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    assert next_weekly_due(current, now) == datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
