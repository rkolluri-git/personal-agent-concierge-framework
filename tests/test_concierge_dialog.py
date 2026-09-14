from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from database import Base
from models import FamilyMember, AlertContact, Alert, ConciergeInboxItem, ConciergeReplyReceipt, Task
from concierge_dialog import finish, advance
from concierge_workflow import preview_request
from main import receive_concierge_imessage, reply_to_concierge, update_concierge_plan
from schemas import ConciergeInboxRequest, ConciergeReplyRequest, ConciergePlanUpdate

NOW = datetime(2026, 9, 14, 10, tzinfo=ZoneInfo('America/New_York'))
PROFILES = [{'name':'Jordan','role':'parent','age':40},{'name':'Taylor','role':'parent','age':39}, {'name':'Alex','role':'child','age':17}]
NAMES = [p['name'] for p in PROFILES]

@pytest.fixture(autouse=True)
def offline():
    with patch('concierge_llm.interpret', return_value=None):
        yield

@pytest.mark.parametrize('text,kind', [
 ('Remind Jordan to take out the bins tomorrow at 7 pm','task'),
 ('Alex homework submission due tomorrow at 7 pm','task'),
 ('Buy milk for Jordan tomorrow at 5 pm','task'),
 ('Schedule a dentist appointment for Jordan tomorrow at 3 pm','calendar'),
 ('Remind Alex about the therapy appointment tomorrow at 3 pm','calendar'),
 ('Alex has a meeting tomorrow at 4 pm','calendar'),
])
def test_classification(text,kind):
    assert preview_request(text,NAMES,NOW,PROFILES)['request_type']==kind


def test_task_not_overridden_by_llm_calendar_guess():
    with patch('concierge_llm.interpret',return_value={'request_type':'calendar'}):
        assert preview_request('Remind Jordan to take out bins tomorrow at 7 pm',NAMES,NOW,PROFILES)['request_type']=='task'


def test_calendar_multiple_turns_preserve_date_across_midnight():
    plan=finish(preview_request('Schedule a dentist appointment for Jordan',NAMES,NOW,PROFILES))
    assert plan['question_field']=='date'
    plan=advance(plan,'tomorrow',NAMES,PROFILES,NOW,'Jordan')
    assert plan['date']=='2026-09-15'
    assert plan['question_field']=='time'
    plan=advance(plan,'3:30 pm',NAMES,PROFILES,NOW+timedelta(days=1),'Jordan')
    assert plan['date']=='2026-09-15'
    assert plan['time']=='15:30'
    assert plan['dialog_state']=='ready_for_review'
    assert 'nothing has been booked' in plan['reply_text']


def test_irrelevant_reply_does_not_complete_calendar():
    plan=finish(preview_request('Schedule appointment for Jordan',NAMES,NOW,PROFILES))
    plan=advance(plan,'thanks',NAMES,PROFILES,NOW,'Jordan')
    assert plan['question_field']=='date'


def test_parent_answer_does_not_change_child_subject():
    plan=finish(preview_request('Alex appointment tomorrow at 3 pm',NAMES,NOW,PROFILES))
    assert plan['question_field']=='which parent will drive'
    plan=advance(plan,'Taylor',NAMES,PROFILES,NOW,'Jordan')
    assert plan['primary_member']=='Alex'
    assert plan['driver']=='Taylor'
    assert plan['dialog_state']=='ready_for_review'

@pytest.fixture
def db(tmp_path):
    import sensitive_crypto
    from functools import partial
    enc,dec=sensitive_crypto.encrypt_text,sensitive_crypto.decrypt_text
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[m.__table__ for m in (FamilyMember, AlertContact, Task, Alert, ConciergeInboxItem, ConciergeReplyReceipt)])
    with patch('sensitive_crypto.encrypt_text',lambda value, path=None: enc(value,tmp_path/'key')), patch('sensitive_crypto.decrypt_text',lambda value, path=None: dec(value,tmp_path/'key')):
        with Session(engine) as session:
            session.add_all([FamilyMember(id=1,name='Jordan',role='parent'),FamilyMember(id=2,name='Taylor',role='parent')])
            session.flush()
            session.add_all([AlertContact(member_id=1,encrypted_imessage_handle=enc('+15555550101',tmp_path/'key'),enabled=True),AlertContact(member_id=2,encrypted_imessage_handle=enc('+15555550102',tmp_path/'key'),enabled=True)])
            session.commit()
            yield session


def incoming(db,text,guid='1',sender='+15555550101'):
    return receive_concierge_imessage(ConciergeInboxRequest(text=text,message_guid=guid,sender_handle=sender),db)


def test_inbox_questions_ack_and_idempotency(db):
    first=incoming(db,'FA Schedule dentist for Jordan')
    item=first['item'];id=item['id']
    assert item['plan']['question_field']=='date'
    assert db.scalar(select(func.count()).select_from(Alert))==1
    incoming(db,'FA Schedule dentist for Jordan')
    assert db.scalar(select(func.count()).select_from(Alert))==1
    answer=f'FA #{id} 2026-09-20'
    second=incoming(db,answer,'2')
    assert second['item']['plan']['question_field']=='time'
    incoming(db,answer,'2')
    assert db.scalar(select(func.count()).select_from(Alert))==2
    last=incoming(db,f'FA #{id} 3 pm','3')
    assert last['item']['plan']['dialog_state']=='ready_for_review'
    assert db.scalar(select(func.count()).select_from(ConciergeInboxItem))==1
    alerts=db.scalars(select(Alert).order_by(Alert.id)).all()
    assert len(alerts)==3
    assert 'ready for review' in alerts[-1].message
    assert db.get(ConciergeInboxItem,id).encrypted_plan.startswith('enc:v1:')
    # Saving retains replies instead of reparsing the incomplete initial text.
    result=update_concierge_plan(id,ConciergePlanUpdate(text='Schedule dentist for Jordan'),db)
    assert result['plan']['date']=='2026-09-20'
    assert result['plan']['time']=='15:00'
    assert result['status']=='handled'


def test_other_sender_and_personal_replies_ignored(db):
    item=incoming(db,'FA Schedule appointment for Jordan')['item']
    assert incoming(db,f"FA #{item['id']} tomorrow",'2',sender='+15555550102')['status']=='ignored'
    assert incoming(db,'tomorrow','3')['status']=='ignored'
    assert db.scalar(select(func.count()).select_from(Alert))==1


def test_dashboard_reply_does_not_send_text_and_is_idempotent(db):
    id=incoming(db,'FA Schedule appointment for Jordan')['item']['id']
    payload=ConciergeReplyRequest(text='2026-09-20',message_guid='ui-one')
    reply_to_concierge(id,payload,db)
    reply_to_concierge(id,payload,db)
    assert len(db.get(ConciergeInboxItem,id).encrypted_plan)>0
    assert db.scalar(select(func.count()).select_from(Alert))==1


def test_calendar_not_overridden_by_llm_task_guess():
    with patch('concierge_llm.interpret',return_value={'request_type':'task'}):
        assert preview_request('Remind Jordan about the meeting tomorrow at 4 pm',NAMES,NOW,PROFILES)['request_type']=='calendar'


def test_self_echo_never_creates_another_draft_or_alert(db):
    item=incoming(db,'FA Schedule appointment for Jordan')['item']
    echo=db.scalar(select(Alert.message))
    assert incoming(db,echo,'echo1')['status']=='ignored'
    old_echo=echo.replace('Family Agent request','FA request')
    assert incoming(db,old_echo,'echo2')['status']=='ignored'
    assert db.scalar(select(func.count()).select_from(ConciergeInboxItem))==1
    assert db.scalar(select(func.count()).select_from(Alert))==1
    result=incoming(db,f"2026-09-20 FA #{item['id']}",'date-reply')
    assert result['item']['id']==item['id']
    assert result['item']['plan']['question_field']=='time'


def test_web_request_persists_once_without_sending(db):
    from uuid import uuid4
    from main import create_web_request
    from schemas import ConciergeWebRequest
    member=db.scalars(select(FamilyMember)).first()
    payload=ConciergeWebRequest(text=f'Schedule an appointment for {member.name}',member_id=member.id,request_id=str(uuid4()))
    first=create_web_request(payload,db)
    again=create_web_request(payload,db)
    assert first['id']==again['id']
    assert first['plan']['dialog_state']=='awaiting_details'
    assert db.scalar(select(func.count()).select_from(Alert))==0
    reply=reply_to_concierge(first['id'],ConciergeReplyRequest(text='tomorrow',message_guid=str(uuid4())),db)
    assert reply['item']['id']==first['id']
    assert reply['item']['plan']['date']
    assert db.scalar(select(func.count()).select_from(ConciergeInboxItem))==1


def test_request_task_creation_is_linked_and_idempotent(db):
    from main import create_request_task,edit_task
    from schemas import TaskCreate
    item=incoming(db,'FA Buy milk for Jordan tomorrow at 5 pm')['item']
    payload=TaskCreate(title='Buy milk',assigned_to='Jordan')
    first=create_request_task(item['id'],payload,db)
    again=create_request_task(item['id'],payload,db)
    assert first.id==again.id
    assert db.scalar(select(func.count()).select_from(Task))==1
    edited=edit_task(first.id,TaskCreate(title='Buy bread',assigned_to='Taylor'),db)
    assert edited.title=='Buy bread'
    assert edited.assigned_to_name=='Taylor'


def test_calendar_receipt_prevents_duplicate_save(db):
    from uuid import uuid4
    from icloud_editor import Edit,create_from_request
    item=incoming(db,'FA Schedule dentist for Jordan tomorrow at 3 pm')['item']
    p=Edit(calendar_key='key',title='Dentist',start='2026-09-15T15:00:00-04:00',end='2026-09-15T16:00:00-04:00',request_id=uuid4())
    with patch('database.SessionLocal',return_value=db),patch('icloud_editor.write') as writer:
        first=create_from_request(item['id'],0,p)
        second=create_from_request(item['id'],0,p)
        assert first==second
        assert writer.call_count==1


def test_autosave_keeps_ready_draft_pending(db):
    item=incoming(db,'FA Buy milk for Jordan tomorrow at 5 pm')['item']
    saved=update_concierge_plan(item['id'],ConciergePlanUpdate(text=item['request_text'],keep_in_inbox=True),db)
    assert saved['status']=='pending'
    assert saved['processed_at'] is None
    assert db.scalar(select(func.count()).select_from(Task))==0
