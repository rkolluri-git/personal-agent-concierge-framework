from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from icalendar import Calendar,Event
import calendar_archive as archive
import icloud_editor as editor
from calendar_service import CalendarEvent


def test_archive_expiry_and_partial_refresh():
    engine=create_engine('sqlite://');archive.CalendarHistory.__table__.create(engine)
    sessions=sessionmaker(bind=engine)
    now=datetime.now(timezone.utc)
    def event(id,end):return CalendarEvent(id=id,source='icloud',calendar='Family',title='Test',start=(end-timedelta(hours=1)).isoformat(),end=end.isoformat(),all_day=False)
    with patch.object(archive,'SessionLocal',sessions):
        archive.maintain([event('old',now-timedelta(hours=2)),event('recent',now-timedelta(minutes=30))],True,timezone.utc)
        assert [e['id'] for e in archive.archive()]==['old']
        archive.maintain([event('ignored',now-timedelta(hours=2))],False,timezone.utc)
        assert len(archive.archive())==1
        with sessions() as db:
            db.get(archive.CalendarHistory,'old').ends_at=now-timedelta(days=91);db.commit()
        archive.maintain([],True,timezone.utc)
        assert not archive.archive()
    missing=event('missing',now);missing.end_known=False
    assert archive.end_time(missing,timezone.utc) is None


def payload():
    start=datetime.now(timezone.utc)+timedelta(days=1)
    return editor.Edit(calendar_key='key',title='Test',start=start,end=start+timedelta(hours=1),request_id=uuid4())


def test_create_uses_conditional_put():
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def put(self,url,body,headers):
            assert headers['If-None-Match']=='*';assert url.startswith('https://cal.example/family/')
            self.body=body
            return SimpleNamespace(status=201)
        def request(self,url):return SimpleNamespace(status=200,raw=self.body)
    client=Client()
    with patch.object(editor,'selected',return_value=({'username':'x','password':'x'},{'id':'https://cal.example/family/'})),patch.object(editor,'icloud_client',return_value=client):
        assert editor.create(payload())=={'status':'saved'}


def test_invited_event_cannot_be_edited():
    c=Calendar();e=Event();e.add('dtstart',datetime.now(timezone.utc));e.add('attendee','mailto:test@example.com');c.add_component(e)
    with pytest.raises(HTTPException):editor.editable(c.to_ical())


def test_stale_edit_never_writes():
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def put(self,*args,**kwargs):raise AssertionError('Must not overwrite')
    p=payload();p.etag='old'
    with patch.object(editor,'selected',return_value=({'username':'x','password':'x'},{'id':'https://cal.example/family/'})),patch.object(editor,'icloud_client',return_value=Client()),patch.object(editor,'lookup',return_value=SimpleNamespace(calendar_key='key')),patch.object(editor,'read_resource',return_value=('https://cal.example/family/a',SimpleNamespace(headers={'ETag':'new'}))):
        with pytest.raises(HTTPException) as err:editor.update('event',p)
    assert err.value.status_code==409

@pytest.mark.parametrize('repeat',['none','daily','weekly','monthly','yearly'])
def test_past_event_and_repeat_timezone(repeat):
    from zoneinfo import ZoneInfo
    from datetime import date
    p=editor.Edit(calendar_key='key',title='Past practice',start='2026-03-01T20:30:00Z',end='2026-03-01T21:00:00Z',request_id=uuid4(),repeat=repeat,repeat_until=date(2026,4,1) if repeat!='none' else None,timezone_name='America/New_York')
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def put(self,url,body,headers):
            self.body=body
            e=Calendar.from_ical(body).walk('VEVENT')[0]
            assert e.decoded('DTSTART').hour==15
            assert e['DTSTART'].params['TZID']=='America/New_York'
            if repeat=='none':assert 'RRULE' not in e
            else:
                assert e['RRULE']['FREQ']==[repeat.upper()]
                assert e['RRULE']['UNTIL'][0]==datetime(2026,4,2,3,59,59,tzinfo=timezone.utc)
                if repeat=='weekly':
                    import recurring_ical_events
                    occurrences=recurring_ical_events.of(Calendar.from_ical(body)).between(datetime(2026,3,1,tzinfo=ZoneInfo('America/New_York')),datetime(2026,3,20,tzinfo=ZoneInfo('America/New_York')))
                    assert len(occurrences)==3
                    assert all(x.decoded('DTSTART').hour==15 for x in occurrences)
            return SimpleNamespace(status=201)
        def request(self,url):return SimpleNamespace(status=200,raw=self.body)
    with patch.object(editor,'selected',return_value=({'username':'x','password':'x'},{'id':'https://cal.example/family/'})),patch.object(editor,'icloud_client',return_value=Client()):
        assert editor.create(p)=={'status':'saved'}


def test_repeat_validation():
    from pydantic import ValidationError
    data=payload().model_dump()
    for extra in ({'repeat':'invalid'},{'timezone_name':'Unknown/Nowhere'},{'repeat':'weekly','repeat_until':'2000-01-01'},{'repeat_until':'2099-01-01'}):
        with pytest.raises(ValidationError):editor.Edit(**(data|extra))


def test_resource_lookup_matches_exact_uid_in_window():
    from unittest.mock import Mock
    event=SimpleNamespace(uid='target',start='2026-09-15T07:40:00-04:00',end='2026-09-15T08:00:00-04:00')
    wrong=SimpleNamespace(url='https://cal.example/wrong',get_icalendar_component=lambda:{'UID':'other'})
    right=SimpleNamespace(url='https://cal.example/right',get_icalendar_component=lambda:{'UID':'target'})
    client=Mock();client.calendar.return_value.search.return_value=[wrong,right]
    client.request.return_value=SimpleNamespace(status=200)
    url,_=editor.read_resource(client,{'id':'https://cal.example/'},event)
    assert url==right.url
    assert client.calendar.return_value.search.call_args.kwargs['expand'] is False
    client.request.assert_called_once_with(right.url)
    client.calendar.return_value.search.return_value=[wrong]
    with pytest.raises(HTTPException):editor.read_resource(client,{'id':'https://cal.example/'},event)
    assert client.request.call_count==1
