"""Deterministic scheduling helpers for recurring family tasks."""
from datetime import datetime, timedelta


def next_weekly_due(current_due: datetime, now: datetime) -> datetime:
    next_due = current_due + timedelta(days=7)
    while next_due <= now:
        next_due += timedelta(days=7)
    return next_due
