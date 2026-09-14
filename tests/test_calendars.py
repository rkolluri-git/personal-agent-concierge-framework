import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from icalendar import Event
import calendar_service as service


class CalendarTests(unittest.TestCase):
    def test_google_dates_cancellation_and_recurrence_ids(self):
        calendar = {"id": "family", "name": "Family"}
        raw = {"id": "event", "start": {"date": "2026-09-11"}, "end": {"date": "2026-09-13"}}
        event = service.google_event(raw, calendar)
        self.assertTrue(event.all_day)
        self.assertEqual(event.end, "2026-09-13")
        self.assertEqual(event.title, "Untitled event")
        self.assertIsNone(service.google_event({"status": "cancelled"}, calendar))
        second = service.google_event({**raw, "start": {"date": "2026-09-18"}}, calendar)
        self.assertNotEqual(event.id, second.id)

    def test_icloud_dates_timezone_and_duration(self):
        calendar = {"id": "family", "name": "Family"}
        event = Event.from_ical(b'BEGIN:VEVENT\r\nUID:a\r\nDTSTART;VALUE=DATE:20260911\r\nSUMMARY:School\r\nEND:VEVENT\r\n')
        normalized = service.icloud_event(event, calendar)
        self.assertTrue(normalized.all_day)
        self.assertEqual(normalized.end, "2026-09-12")
        event = Event.from_ical(b'BEGIN:VEVENT\r\nUID:b\r\nDTSTART:20260911T100000\r\nDURATION:PT1H\r\nEND:VEVENT\r\n')
        normalized = service.icloud_event(event, calendar)
        self.assertEqual(normalized.start, "2026-09-11T10:00:00-04:00")
        self.assertEqual(normalized.end, "2026-09-11T11:00:00-04:00")
        event.add('status', 'CANCELLED')
        self.assertIsNone(service.icloud_event(event, calendar))

    def test_departure_readiness_requires_time_and_location(self):
        calendar = {"id": "family", "name": "Family"}
        timed = {
            "id": "trip",
            "start": {"dateTime": "2026-09-12T19:00:00-04:00"},
            "end": {"dateTime": "2026-09-12T20:00:00-04:00"},
            "location": "Community Center",
        }
        self.assertTrue(service.google_event(timed, calendar).departure_ready)
        self.assertFalse(service.google_event({**timed, "location": "   "}, calendar).departure_ready)
        all_day = {
            "id": "day",
            "start": {"date": "2026-09-12"},
            "end": {"date": "2026-09-13"},
            "location": "Community Center",
        }
        self.assertFalse(service.google_event(all_day, calendar).departure_ready)

    def test_missing_connections_and_private_storage(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service, 'CONFIG', Path(folder)):
            result = service.upcoming_events()
            self.assertEqual(result['events'], [])
            self.assertEqual(result['departure_ready_count'], 0)
            self.assertEqual(result['missing_location_count'], 0)
            self.assertEqual([s['status'] for s in result['sources']], ['not_connected', 'not_connected'])
            service.save_config('test.json', {'token': 'test-only'})
            self.assertEqual((Path(folder) / 'test.json').stat().st_mode & 0o777, 0o600)

    def test_error_redaction_and_partial_results(self):
        event = service.CalendarEvent(id='a', source='google', calendar='Family', title='Test', start='2026-09-11', end='2026-09-12', all_day=True)
        with patch.object(service, 'read_google', return_value=([event], {'source': 'google', 'status': 'connected'})), patch.object(service, 'read_icloud', side_effect=RuntimeError('PRIVATE TOKEN')):
            result = service.upcoming_events()
            self.assertEqual(len(result['events']), 1)
            self.assertEqual(result['sources'][1]['status'], 'error')
            self.assertNotIn('PRIVATE TOKEN', str(result))

    def test_google_pagination_and_readonly_requests(self):
        credentials = MagicMock()
        credentials.to_json.return_value = '{}'
        session = MagicMock()
        session.__enter__.return_value = session
        first, second = MagicMock(), MagicMock()
        first.json.return_value = {'items': [], 'nextPageToken': 'page-2'}
        second.json.return_value = {'items': [{'id': 'one', 'start': {'date': '2026-09-11'}, 'end': {'date': '2026-09-12'}}]}
        session.get.side_effect = [first, second]
        with patch.object(service, 'read_config', side_effect=[{'token': 'test'}, [{'id': 'a/b', 'name': 'Family'}]]), patch.object(service.Credentials, 'from_authorized_user_info', return_value=credentials), patch.object(service, 'AuthorizedSession', return_value=session), patch.object(service, 'save_config'):
            events, status = service.read_google(datetime.now(timezone.utc), datetime.now(timezone.utc))
            self.assertEqual(len(events), 1)
            self.assertEqual(status['status'], 'connected')
            self.assertIn('a%2Fb', session.get.call_args_list[0].args[0])
            self.assertEqual(session.get.call_args_list[1].kwargs['params']['pageToken'], 'page-2')
            session.post.assert_not_called()

    def test_icloud_adapter_expands_recurring_events(self):
        client = MagicMock()
        client.__enter__.return_value = client
        obj = MagicMock()
        obj.get_icalendar_component.return_value = Event.from_ical(b'BEGIN:VEVENT\r\nUID:a\r\nDTSTART;VALUE=DATE:20260911\r\nEND:VEVENT\r\n')
        client.calendar.return_value.search.return_value = [obj]
        config = {'username': 'test', 'password': 'test', 'calendars': [{'id': 'https://caldav.icloud.com/test/', 'name': 'Family'}]}
        with patch.object(service, 'read_config', return_value=config), patch.object(service.caldav, 'DAVClient', return_value=client):
            events, status = service.read_icloud(datetime.now(timezone.utc), datetime.now(timezone.utc))
            self.assertEqual(len(events), 1)
            self.assertTrue(client.calendar.return_value.search.call_args.kwargs['expand'])
            self.assertEqual(status['status'], 'connected')

    def test_short_cache_avoids_duplicate_provider_fetches(self):
        service._calendar_cache.clear()
        connected = lambda source: ([], {'source': source, 'status': 'connected', 'message': 'Up to date'})
        with patch.object(service, 'fetch_source', side_effect=lambda source, *_: connected(source)) as fetch:
            first = service.upcoming_events(refresh=True)
            second = service.upcoming_events()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(first['checked_at'], second['checked_at'])


if __name__ == '__main__':
    unittest.main()
