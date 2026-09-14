"""Possible overlaps among timed, busy events; never edits calendar data."""
from datetime import datetime, timezone


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timed calendar events must include a timezone")
    return parsed.astimezone(timezone.utc)


def find_conflicts(events, window_start, window_end):
    lower, upper = window_start.astimezone(timezone.utc), window_end.astimezone(timezone.utc)
    intervals = []
    seen = set()
    for event in events:
        if event.id in seen or event.all_day or not event.busy:
            continue
        seen.add(event.id)
        start, end = max(instant(event.start), lower), min(instant(event.end), upper)
        if start < end:
            intervals.append((start, end, event))
    intervals.sort(key=lambda row: (row[0], row[2].id))
    active, conflicts = [], []
    for start, end, event in intervals:
        active = [row for row in active if row[1] > start]
        for other_start, other_end, other in active:
            # A shared event can be returned by more than one calendar/provider.
            if event.uid and event.uid == other.uid and event.start == other.start and event.end == other.end:
                continue
            if event.uid and event.uid == other.uid and instant(event.start) == instant(other.start) and instant(event.end) == instant(other.end):
                continue
            overlap_end = min(end, other_end)
            conflicts.append({"event_ids": [other.id, event.id],
                              "start": start.isoformat(), "end": overlap_end.isoformat(),
                              "minutes": round((overlap_end - start).total_seconds() / 60, 2)})
        active.append((start, end, event))
    return conflicts
