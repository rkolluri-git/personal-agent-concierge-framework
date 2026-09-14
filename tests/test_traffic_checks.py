from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from fastapi import HTTPException
from database import Base
from models import FamilyMember,AlertContact,Alert,Task
from traffic_checks import TrafficCheck,TrafficCreate,TrafficResult,create_check,claim_check,complete_check

@pytest.fixture
def db(tmp_path):
    import sensitive_crypto,traffic_checks
    enc,dec=sensitive_crypto.encrypt_text,sensitive_crypto.decrypt_text
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[m.__table__ for m in (FamilyMember,AlertContact,Task,Alert,TrafficCheck)])
    with Session(engine) as db, patch.object(traffic_checks,'encrypt_text',lambda s:enc(s,tmp_path/'key')),patch.object(traffic_checks,'decrypt_text',lambda s:dec(s,tmp_path/'key')):
        db.add(FamilyMember(id=1,name='Parent',role='parent'));db.flush()
        db.add(AlertContact(member_id=1,encrypted_imessage_handle='test@example.com',enabled=True));db.commit()
        yield db

def payload():
    return TrafficCreate(request_key='one-return',member_id=1,label='Therapy: return home',origin_address='Therapy address',destination_address='Home address',scheduled_for=datetime.now(timezone.utc)+timedelta(hours=1))

def test_direction_schedule_and_idempotent_delivery(db):
    data=payload();one=create_check(data,db);two=create_check(data,db)
    assert one['id']==two['id']
    assert claim_check(db) is None
    row=db.get(TrafficCheck,one['id'])
    assert row.encrypted_origin.startswith('enc:v1:')
    row.scheduled_for=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    claim=claim_check(db)
    assert claim['origin_address']=='Therapy address'
    assert claim['destination_address']=='Home address'
    assert claim_check(db) is None
    result=TrafficResult(claim_token=claim['claim_token'],duration_seconds=900,distance_meters=10000)
    complete_check(row.id,result,db);complete_check(row.id,result,db)
    assert db.scalar(select(func.count()).select_from(Alert))==1
    assert claim_check(db) is None
    assert '15 min' in db.scalar(select(Alert.message))

def test_expired_check_and_stale_claim(db):
    row_id=create_check(payload(),db)['id'];row=db.get(TrafficCheck,row_id)
    row.scheduled_for=datetime.now(timezone.utc)-timedelta(minutes=20)
    row.claimed_at=datetime.now(timezone.utc)-timedelta(minutes=11)
    row.status='claimed';row.claim_token='old';db.commit()
    claim=claim_check(db)
    assert claim['claim_token']!='old'
    with pytest.raises(HTTPException):complete_check(row_id,TrafficResult(claim_token='old',duration_seconds=60),db)
    row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert claim_check(db) is None
    assert row.status=='expired'
    assert db.scalar(select(func.count()).select_from(Alert))==0

def test_conflicting_key_rejected_and_routing_failure_is_truthful(db):
    data=payload();row_id=create_check(data,db)['id']
    with pytest.raises(HTTPException):create_check(data.model_copy(update={'origin_address':'Different address'}),db)
    row=db.get(TrafficCheck,row_id);row.scheduled_for=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    claim=claim_check(db)
    complete_check(row_id,TrafficResult(claim_token=claim['claim_token'],error='routing unavailable'),db)
    assert 'unavailable' in db.scalar(select(Alert.message))
    assert 'Directions:' in db.scalar(select(Alert.message))


def test_bridge_routes_one_time_result_to_correct_endpoint(tmp_path,monkeypatch):
    from macos import imessage_worker as worker
    from types import SimpleNamespace
    mac=tmp_path/'macos';mac.mkdir();config=tmp_path/'config';config.mkdir()
    (mac/'traffic_eta.m').write_text('source')
    (config/'traffic_eta').write_text('binary')
    monkeypatch.setattr(worker,'__file__',str(mac/'imessage_worker.py'))
    answers=iter([None,{'run_id':7,'claim_token':'token','origin_address':'Therapy address','destination_address':'Home address'},None,None,None])
    monkeypatch.setattr(worker,'post',lambda *a,**kw:next(answers))
    captured=[]
    monkeypatch.setattr(worker,'post_json',lambda path,payload,**kw:captured.append((path,payload)))
    commands=[]
    def execute(args,**kw):
        commands.append(args)
        return SimpleNamespace(returncode=0,stdout='{"duration_seconds":900,"distance_meters":10000}')
    monkeypatch.setattr(worker.subprocess,'run',execute)
    worker.sync_commute_reports()
    assert commands[-1][-2:]==['Therapy address','Home address']
    assert captured==[('/traffic/checks/7/complete',{'duration_seconds':900,'distance_meters':10000,'claim_token':'token'})]
