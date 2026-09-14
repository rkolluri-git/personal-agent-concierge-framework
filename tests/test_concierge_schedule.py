from datetime import datetime,date
from unittest.mock import patch
from zoneinfo import ZoneInfo
from calendar_service import CalendarEvent
from concierge_schedule import is_schedule_query, schedule_plan, overlaps_day
from concierge_chain import run_request
from concierge_dialog import finish

NOW = datetime(2026,9,14,17,tzinfo=ZoneInfo('America/New_York'))
def event(**kwargs):
    return CalendarEvent(id='a',source='icloud',calendar='Family',title='Practice',start='2026-09-15T16:00:00-04:00',end='2026-09-15T17:00:00-04:00',all_day=False,calendar_key='family',**kwargs)

def test_query_route_not_appointment():
    assert is_schedule_query('provide activity or calendar list for tomorrow')
    assert not is_schedule_query('create calendar appointment tomorrow')
    with patch('concierge_schedule.scope_for',return_value=None), patch('concierge_schedule.upcoming_events',return_value={'events':[event()],'conflict_check_complete':True}), patch('concierge_chain.preview_request',side_effect=AssertionError('no LLM')):
        plan=run_request('provide activity or calendar list for tomorrow',[],NOW)
    assert plan['request_type']=='schedule_query'
    assert '4:00 PM: Practice' in plan['reply_text']
    assert finish(plan)==plan

def test_scope_and_partial_results():
    with patch('concierge_schedule.scope_for',return_value={'other'}),patch('concierge_schedule.upcoming_events',return_value={'events':[event()],'conflict_check_complete':False}):
        plan=schedule_plan('show calendar tomorrow',NOW,'Child')
    assert not plan['schedule_events']
    assert 'incomplete' in plan['reply_text']

def test_missing_day_and_overnight():
    assert schedule_plan('show calendar',NOW)['missing_fields']==['schedule day']
    e=event();e.start='2026-09-14T23:00:00-04:00';e.end='2026-09-15T01:00:00-04:00'
    assert overlaps_day(e,date(2026,9,15))
