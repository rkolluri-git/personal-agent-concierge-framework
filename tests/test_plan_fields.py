from datetime import datetime
from concierge_workflow import extract_details
from schemas import ConciergeFieldEdits
from pydantic import ValidationError
import pytest


def test_weekday_overrides_incorrect_model_date():
    plan=extract_details({'normalized_text':'Speech Practice Example Child on Wednesday at 3:30 PM',
        'now':datetime(2026,9,14,17).isoformat(),'member_names':['Example Child'],
        'family_profiles':[{'name':'Example Child','role':'child','age':17}], 'request_type':'calendar',
        'llm_plan':{'date':'2026-09-13','primary_member':'Example Child'}})
    assert plan['date']=='2026-09-16'
    assert plan['repeat_interval']=='none'


def test_edit_fields_validate_date_and_clock():
    fields=dict(title='Speech practice',date='2026-09-16',time='15:30',end_time='16:00',primary_member='Example Child',notification_members=['Example Child','Child One'])
    assert ConciergeFieldEdits(**fields).end_time=='16:00'
    with pytest.raises(ValidationError):ConciergeFieldEdits(**dict(fields,date='2026-02-30'))
    with pytest.raises(ValidationError):ConciergeFieldEdits(**dict(fields,time='25:30'))
