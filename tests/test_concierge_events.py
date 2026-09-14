from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
from concierge_events import is_events_search, search_plan
from concierge_chain import run_request
from concierge_dialog import finish, reply_message

NOW = datetime(2026, 9, 14, tzinfo=ZoneInfo('America/New_York'))
DATA = {'sources': [{'status': 'ok'}], 'events': [dict(title='Test Band', genre='Rock', venue='Roxy', start='2026-11-14T20:00:00-05:00', url='https://example.com', status='Scheduled')]}


def test_route_does_not_capture_bookings():
    assert is_events_search('FA find rock concerts  in November')
    assert not is_events_search('Schedule a concert for Example Child')
    assert not is_events_search('Find my therapy appointment')


def test_search_uses_graph_and_preserves_inbox_reply():
    with patch('concierge_events.refresh', return_value=DATA):
        plan = run_request('FA find rock concerts  in November', [], NOW)
    assert plan['request_type'] == 'events'
    assert plan['result_count'] == 1
    assert finish(plan) == plan
    assert 'Found 1' in reply_message(1, plan)
    assert len(reply_message(1, plan)) <= 500


def test_filters_and_unsupported_year():
    with patch('concierge_events.refresh', return_value=DATA) as fetch:
        assert search_plan('find jazz concerts in November', NOW)['result_count'] == 0
        assert search_plan('find rock concerts in October', NOW)['result_count'] == 0
        plan = search_plan('find concerts in 2027', NOW)
        assert 'December 2026' in plan['reply_text']
        assert fetch.call_count == 2
