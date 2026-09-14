from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from concierge_chain import run_request
from concierge_dialog import advance
from main import preview_concierge_request
from schemas import ConciergePreviewRequest

NOW=datetime(2026,9,14,10,tzinfo=ZoneInfo('America/New_York'))
PROFILES=[{'name':'Jordan','role':'parent','age':40}]


def test_chain_routes_incomplete_request_to_question_then_ack():
    extracted={'request_type':'calendar','title':'Dentist','primary_member':'Jordan',
               'date':None,'time':None,'notification_members':[],'calendar_events':[]}
    with patch('concierge_llm.interpret', side_effect=[extracted, {**extracted,'date':'2026-09-15'},
              {**extracted,'date':'2026-09-15','time':'15:30'}]) as model:
        initial=run_request('Schedule a dentist appointment for Jordan',['Jordan'],NOW,PROFILES)
        snapshot=deepcopy(initial)
        second=advance(initial,'tomorrow',['Jordan'],PROFILES,NOW,'Jordan')
        last=advance(second,'3:30 pm',['Jordan'],PROFILES,NOW+timedelta(days=1),'Jordan')
    assert model.call_count==3
    assert initial==snapshot
    assert initial['workflow_steps']==['llm_interpret','classify','extract','merge_confirmed_details','validate_required_details','ask_for_details']
    assert second['question_field']=='time'
    assert last['workflow_steps'][-1]=='acknowledge_ready_for_review'
    assert last['date']=='2026-09-15' and last['time']=='15:30'
    assert last['missing_fields']==[]
    assert 'nothing has been booked' in last['reply_text']
    assert model.call_args_list[2].kwargs['dialog_context']['date']=='2026-09-15'


def test_missing_model_follows_safe_fallback_branch():
    with patch('concierge_llm.interpret',return_value=None):
        p=run_request('Schedule a dentist appointment for Jordan',['Jordan'],NOW,PROFILES)
    assert p['workflow_steps'][0]=='local_fallback'
    assert p['interpreter_this_turn']=='local_fallback'
    assert p['workflow_steps'][-1]=='ask_for_details'
    assert p['question_field']=='date'


def test_fallback_current_turn_is_not_hidden_by_previous_llm_success():
    with patch('concierge_llm.interpret',return_value={'request_type':'calendar'}):
        p=run_request('Schedule a dentist appointment for Jordan',['Jordan'],NOW,PROFILES)
    with patch('concierge_llm.interpret',return_value=None):
        p=advance(p,'tomorrow',['Jordan'],PROFILES,NOW,'Jordan')
    assert p['llm_used'] is True
    assert p['interpreter_this_turn']=='local_fallback'
    assert p['workflow_steps'][0]=='local_fallback'


def test_task_chain_reaches_review_without_calendar_requirements():
    with patch('concierge_llm.interpret',return_value=None):
        p=run_request('Add a task for Jordan to buy milk',['Jordan'],NOW,PROFILES)
    assert p['request_type']=='task'
    assert p['dialog_state']=='ready_for_review'
    assert p['workflow_steps'][-1]=='acknowledge_ready_for_review'


def test_dashboard_preview_uses_same_chain_without_writes():
    members=[SimpleNamespace(**p) for p in PROFILES]
    db=SimpleNamespace(scalars=lambda stmt: SimpleNamespace(all=lambda:members))
    with patch('concierge_llm.interpret',return_value=None):
        result=preview_concierge_request(ConciergePreviewRequest(text='Schedule dentist for Jordan'),db)
    assert result['workflow_version']==1
    assert result['question_field']=='date'
