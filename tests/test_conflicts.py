import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from calendar_service import CalendarEvent, _calendar_cache, google_event, icloud_event, upcoming_events
from calendar_conflicts import find_conflicts
from icalendar import Event

START = datetime(2026, 9, 12, tzinfo=timezone.utc)
END = datetime(2026, 9, 14, tzinfo=timezone.utc)


def event(id, start='2026-09-12T19:00:00-04:00', end='2026-09-12T20:00:00-04:00', **kwargs):
    return CalendarEvent(id=id, title=id, source='google', calendar='Family', start=start, end=end, all_day=kwargs.pop('all_day', False), **kwargs)


class ConflictTests(unittest.TestCase):
    def test_overlap_across_timezones_and_midnight(self):
        a = event('a')
        b = event('b', '2026-09-12T23:30:00Z', '2026-09-13T00:30:00Z')
        result = find_conflicts([b, a], START, END)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['minutes'], 30)
        self.assertEqual(result[0]['event_ids'], ['a', 'b'])

    def test_touching_empty_and_outside_window(self):
        a = event('a')
        b = event('b', '2026-09-12T20:00:00-04:00', '2026-09-12T21:00:00-04:00')
        zero = event('zero', a.start, a.start)
        self.assertEqual(find_conflicts([a, b, zero], START, END), [])
        self.assertEqual(find_conflicts([a, event('same')], END, END), [])

    def test_nested_and_multiple_overlaps(self):
        rows = [event('a'), event('b', '2026-09-12T23:15:00Z', '2026-09-12T23:45:00Z'), event('c', '2026-09-12T23:20:00Z', '2026-09-12T23:25:00Z')]
        self.assertEqual(sorted(c['minutes'] for c in find_conflicts(rows, START, END)), [5, 5, 30])

    def test_shared_uid_and_repeated_ids(self):
        a = event('a', uid='shared')
        b = event('b', '2026-09-12T23:00:00Z', '2026-09-13T00:00:00Z', uid='shared')
        self.assertEqual(find_conflicts([a, a, b], START, END), [])
        self.assertEqual(len(find_conflicts([a, event('other', uid='different')], START, END)), 1)

    def test_free_and_all_day_excluded(self):
        self.assertEqual(find_conflicts([event('a'), event('free', busy=False), event('day', '2026-09-12', '2026-09-14', all_day=True)], START, END), [])
        raw = {'id': 'x', 'start': {'dateTime': '2026-09-12T19:00:00-04:00'}, 'end': {'dateTime': '2026-09-12T20:00:00-04:00'}, 'transparency': 'transparent'}
        self.assertFalse(google_event(raw, {'id':'c','name':'Family'}).busy)
        raw.pop('transparency');raw['attendees']=[{'self':True,'responseStatus':'declined'}]
        self.assertFalse(google_event(raw, {'id':'c','name':'Family'}).busy)
        component = Event.from_ical(b'BEGIN:VEVENT\r\nUID:a\r\nDTSTART:20260912T190000Z\r\nDTEND:20260912T200000Z\r\nTRANSP:TRANSPARENT\r\nEND:VEVENT\r\n')
        self.assertFalse(icloud_event(component, {'id':'c','name':'Family'}).busy)

    def test_dst_offset_comparison(self):
        a = event('a', '2026-11-01T01:00:00-04:00', '2026-11-01T01:45:00-04:00')
        b = event('b', '2026-11-01T01:00:00-05:00', '2026-11-01T01:45:00-05:00')
        self.assertEqual(find_conflicts([a,b], datetime(2026,11,1,tzinfo=timezone.utc), datetime(2026,11,2,tzinfo=timezone.utc)), [])

    def test_partial_sources_are_not_all_clear(self):
        _calendar_cache.clear()
        with patch('calendar_service.fetch_source', side_effect=lambda source, *_: ([], {'source':source, 'status':'connected' if source=='google' else 'error'})):
            result=upcoming_events(refresh=True)
        _calendar_cache.clear()
        self.assertFalse(result['conflict_check_complete'])
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['departure_ready_count'], 0)
        self.assertEqual(result['missing_location_count'], 0)


if __name__ == '__main__': unittest.main()
