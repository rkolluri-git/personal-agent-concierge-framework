from datetime import datetime,timedelta,timezone
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from icalendar import Calendar,Event
import auth_service as auth
import icloud_editor as editor

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(auth,'CONFIG',tmp_path)
    auth.initialize_keys()
    app=FastAPI();app.add_middleware(auth.AuthenticationMiddleware);app.include_router(auth.router)
    @app.api_route('/calendar/icloud/events',methods=['POST'])
    @app.api_route('/calendar/archive',methods=['GET'])
    @app.api_route('/alerts/morning',methods=['PUT'])
    @app.api_route('/departure/traffic/wake-plan',methods=['GET'])
    def protected():return {'ok':True}
    return TestClient(app)

@pytest.mark.parametrize('method,path',[('post','/calendar/icloud/events'),('get','/calendar/archive'),('put','/alerts/morning'),('get','/departure/traffic/wake-plan')])
def test_auth_required(client,method,path):
    assert getattr(client,method)(path).status_code==401
    assert getattr(client,method)(path,headers={'Authorization':'Bearer '+auth.read_key()}).status_code==200

def test_session_csrf_and_host(client):
    assert client.post('/auth/session',json={'token':'wrong'},headers={'Origin':'http://testserver'}).status_code==401
    assert client.post('/auth/session',json={'token':auth.read_key()},headers={'Origin':'https://evil.example'}).status_code==403
    response=client.post('/auth/session',json={'token':auth.read_key()},headers={'Origin':'http://testserver'})
    assert response.status_code==200 and 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/calendar/archive').status_code==200
    assert client.post('/calendar/icloud/events').status_code==403
    assert client.post('/calendar/icloud/events',headers={'Origin':'http://testserver'}).status_code==200
    assert client.get('/calendar/archive',headers={'Host':'evil.example'}).status_code==400
    assert client.post('/calendar/icloud/events',headers={'X-Family-Request':'dashboard','Origin':'https://evil.example'}).status_code==403

@pytest.mark.parametrize('patches',[{'date':None},{'primary_member':None},{'driver':None},{'pickup_by':None},{'missing_fields':['location']}])
def test_incomplete_draft_blocked(patches):
    plan=dict(request_type='calendar',title='Practice',primary_member='Child',date='2026-09-15',time='15:30',subject_role='child',subject_age=17,requires_parent_driver=True,driver_options=['Parent'],driver='Parent',requires_pickup=True,pickup_by='Parent')
    with pytest.raises(HTTPException):editor.validate_request_plan(plan|patches)

def test_readback_mismatch_and_retry():
    p=editor.Edit(calendar_key='key',title='Practice',start=datetime.now(timezone.utc).replace(microsecond=0),end=(datetime.now(timezone.utc)+timedelta(hours=1)).replace(microsecond=0),request_id=uuid4())
    class Client:
        mismatch=False;status=201
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def put(self,url,body,headers):self.body=body;return SimpleNamespace(status=self.status)
        def request(self,url):
            c=Calendar.from_ical(self.body)
            if self.mismatch:c.walk('VEVENT')[0]['SUMMARY']='Wrong title'
            return SimpleNamespace(status=200,raw=c.to_ical())
    c=Client()
    with patch.object(editor,'selected',return_value=({'username':'x','password':'x'},{'id':'https://example.test/cal/'})),patch.object(editor,'icloud_client',return_value=c):
        assert editor.create(p)['status']=='saved'
        c.mismatch=True
        with pytest.raises(HTTPException):editor.create(p)
        c.status=412;c.mismatch=False
        assert editor.create(p)['status']=='saved'
        c.mismatch=True
        with pytest.raises(HTTPException):editor.create(p)

@pytest.mark.parametrize('key,value',[('UID','other'),('SUMMARY','other'),('LOCATION','other'),('DESCRIPTION','other'),('DTSTART',datetime(2026,9,16,tzinfo=timezone.utc)),('DTEND',datetime(2026,9,17,tzinfo=timezone.utc)),('RRULE',{'FREQ':'DAILY'})])
def test_saved_fields_compared(key,value):
    expected=Event();expected.add('UID','id');expected.add('SUMMARY','Title');expected.add('DTSTART',datetime(2026,9,15,tzinfo=timezone.utc));expected.add('DTEND',datetime(2026,9,15,1,tzinfo=timezone.utc))
    c=Calendar();actual=Event.from_ical(expected.to_ical());c.add_component(actual)
    if key in actual:del actual[key]
    actual.add(key,value)
    assert not editor.verify_saved(c.to_ical(),expected)

def test_incomplete_request_never_calls_provider():
    import json
    plan=dict(request_type='calendar',title='Practice',primary_member='Child',date=None,time='15:30',subject_role='child',subject_age=17)
    item=SimpleNamespace(encrypted_plan=json.dumps(plan))
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def scalar(self,*args):return item
    with patch('database.SessionLocal',return_value=Session()),patch('sensitive_crypto.decrypt_text',side_effect=lambda value:value),patch.object(editor,'write') as write:
        with pytest.raises(HTTPException):editor.save_request_event(1,0,None)
        write.assert_not_called()
