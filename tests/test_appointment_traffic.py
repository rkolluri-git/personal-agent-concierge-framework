from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from database import Base
from appointment_traffic import AppointmentTraffic, notification_time, finish, Result
from models import FamilyMember,Alert,AlertContact
from sensitive_crypto import encrypt_text


def test_notification_deadline():
    start=datetime(2026,9,15,16,30,tzinfo=timezone.utc)
    assert notification_time(start,1800,10)==start-timedelta(minutes=45)
    assert notification_time(start,1800,20)==start-timedelta(minutes=50)
    assert notification_time(start,5400,20)==start-timedelta(minutes=110)


def test_rechecks_then_notifies_once(monkeypatch):
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine,tables=[FamilyMember.__table__,AlertContact.__table__,Alert.__table__,AppointmentTraffic.__table__])
    now=datetime.now(timezone.utc)
    with Session(engine) as db:
        member=FamilyMember(name='Driver',role='parent');db.add(member);db.flush()
        db.add(AlertContact(member_id=member.id,encrypted_imessage_handle=encrypt_text('test@example.com'),enabled=True))
        row=AppointmentTraffic(event_id='test',encrypted_context=encrypt_text(json.dumps(dict(title='Appointment',origin='Home address',destination='Venue address',buffer=10,default_recipient=member.id))),starts_at=now+timedelta(hours=2),next_check=now,status='checking',token='token')
        db.add(row);db.commit()
        result=finish('test',Result(claim_token='token',duration_seconds=1800),db)
        assert result['status']=='waiting'
        assert db.query(Alert).count()==0
        row.starts_at=now+timedelta(minutes=44);row.status='checking';row.token='new';db.commit()
        assert finish('test',Result(claim_token='new',duration_seconds=1800),db)['status']=='notified'
        assert finish('test',Result(claim_token='new',duration_seconds=1800),db)['status']=='notified'
        assert db.query(Alert).count()==1
        assert '30 min if you leave now' in db.query(Alert).one().message


def test_failed_eta_is_not_invented_and_cancelled_claim_rejected():
    import pytest
    from fastapi import HTTPException
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine,tables=[FamilyMember.__table__,AlertContact.__table__,Alert.__table__,AppointmentTraffic.__table__])
    with Session(engine) as db:
        m=FamilyMember(name='Parent',role='parent');db.add(m);db.flush()
        db.add(AlertContact(member_id=m.id,encrypted_imessage_handle=encrypt_text('test@example.com'),enabled=True))
        now=datetime.now(timezone.utc)
        r=AppointmentTraffic(event_id='x',encrypted_context=encrypt_text(json.dumps(dict(title='Test',origin='Home',destination='Venue',buffer=20,default_recipient=m.id))),starts_at=now+timedelta(minutes=44),next_check=now,status='checking',token='t')
        db.add(r);db.commit()
        finish('x',Result(claim_token='t',error='unavailable'),db)
        assert 'Live traffic is unavailable' in db.query(Alert).one().message
        r.status='cancelled';r.token=None;db.commit()
        with pytest.raises(HTTPException):finish('x',Result(claim_token='t',duration_seconds=100),db)
        assert db.query(Alert).count()==1


def test_missing_contact_does_not_claim_notification():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine,tables=[FamilyMember.__table__,AlertContact.__table__,Alert.__table__,AppointmentTraffic.__table__])
    now=datetime.now(timezone.utc)
    with Session(engine) as db:
        m=FamilyMember(name='No contact',role='parent');db.add(m);db.flush()
        r=AppointmentTraffic(event_id='missing',encrypted_context=encrypt_text(json.dumps(dict(title='Test',origin='Home',destination='Venue',buffer=10,default_recipient=m.id))),starts_at=now+timedelta(minutes=40),next_check=now,status='checking',token='t')
        db.add(r);db.commit()
        assert finish('missing',Result(claim_token='t',duration_seconds=1800),db)['status']=='no_contact'
        assert db.query(Alert).count()==0


def test_unchanged_calendar_context_does_not_reencrypt():
    from types import SimpleNamespace
    import appointment_traffic as service
    start=datetime.now(timezone.utc)+timedelta(days=1)
    context=dict(title='Test',origin='Home',destination='Venue',buffer=20,default_recipient=1)
    row=SimpleNamespace(event_id='event',starts_at=start,encrypted_context=encrypt_text(json.dumps(context)),status='waiting')
    class DB:
        def get(self, model, id):
            if model is service.DepartureSettings: return SimpleNamespace(home_address='Home',arrival_buffer_minutes=10,parking_walk_minutes=10)
            return SimpleNamespace(enabled=True,member_id=1)
        def scalars(self, query):return [row]
        def flush(self):pass
    event=SimpleNamespace(id='event',title='Test',location='Venue',start=start.isoformat(),all_day=False,busy=True,departure_ready=True)
    with patch.object(service,'upcoming_events',return_value={'events':[event],'conflict_check_complete':True}), patch.object(service,'encrypt_text',side_effect=AssertionError('Unnecessary write')):
        assert service.reconcile(DB())
