"""Explicit create/update of individual iCloud events with conditional writes."""
from datetime import date,datetime,time,timezone
from regional_settings import REGIONAL
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,model_validator
from icalendar import Calendar,Event
import hashlib
from calendar_service import read_config,icloud_client,calendar_key,upcoming_events,_calendar_cache,_calendar_cache_lock

router=APIRouter(prefix='/calendar/icloud',tags=['iCloud editor'])
class Edit(BaseModel):
    calendar_key:str
    title:str=Field(min_length=1,max_length=200)
    start:datetime
    end:datetime
    location:str=Field(default='',max_length=500)
    description:str=Field(default='',max_length=4000)
    request_id:UUID
    etag:str|None=None
    repeat:Literal["none","daily","weekly","monthly","yearly"]="none"
    repeat_until:date|None=None
    timezone_name:str=REGIONAL.timezone
    @model_validator(mode='after')
    def times(self):
        self.title=self.title.strip()
        if not self.title: raise ValueError('Supply an appointment title')
        if self.start.utcoffset() is None or self.end.utcoffset() is None or self.end<=self.start:raise ValueError('Supply start/end timezones, with end after start')
        try: zone=ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError("Choose a valid timezone")
        if self.repeat_until and (self.repeat=="none" or self.repeat_until<self.start.astimezone(zone).date()):
            raise ValueError("Repeat end date must be on or after the first event date")
        return self

def selected(key):
    cfg=read_config('icloud.json')
    if not cfg:raise HTTPException(409,'Connect iCloud first')
    cal=next((c for c in cfg['calendars'] if calendar_key('icloud',c['id'])==key),None)
    if not cal:raise HTTPException(422,'Select a connected iCloud calendar')
    return cfg,cal

@router.get('/calendars')
def calendars():
    cfg=read_config('icloud.json') or {}
    return [dict(key=calendar_key('icloud',c['id']),name=c['name'],label=f"{c['name']} (connected calendar {i+1})") for i,c in enumerate(cfg.get('calendars',[]))]

def editable(data):
    calendar=Calendar.from_ical(data)
    events=calendar.walk('VEVENT')
    if len(events)!=1 or any(k in events[0] for k in ('RRULE','RECURRENCE-ID','ATTENDEE','ORGANIZER')):
        raise HTTPException(409,'Edit recurring or invited events in Apple Calendar')
    if not isinstance(events[0].decoded('DTSTART'),datetime):raise HTTPException(409,'Edit all-day events in Apple Calendar')
    return calendar,events[0]

def lookup(event_id):
    data=upcoming_events(refresh=True)
    return next((e for e in data['events'] if e.id==event_id and e.source=='icloud'),None)

def read_resource(client,calendar,event):
    # iCloud may reject the library's UID-only REPORT. Find the resource in
    # the known occurrence window, then require an exact UID match.
    objects=client.calendar(url=calendar['id']).search(
        start=datetime.fromisoformat(event.start),end=datetime.fromisoformat(event.end),event=True,expand=False)
    matches=[obj for obj in objects if str(obj.get_icalendar_component().get('UID',''))==event.uid]
    if len(matches)!=1:raise HTTPException(409,'Appointment changed or could not be identified. Refresh and try again.')
    obj=matches[0]
    response=client.request(str(obj.url))
    if response.status!=200:raise HTTPException(502,'Could not read iCloud event')
    return str(obj.url),response

@router.get('/events/{event_id}')
def read_event(event_id:str):
    event=lookup(event_id)
    if not event:raise HTTPException(404,'Refresh Calendar; event is no longer available')
    cfg,cal=selected(event.calendar_key)
    try:
        with icloud_client(cfg['username'],cfg['password']) as client:
            url,response=read_resource(client,cal,event)
            _,component=editable(response.raw)
            etag=response.headers.get('ETag')
            if not etag:raise HTTPException(409,'iCloud did not provide a version; edit in Apple Calendar')
            return dict(calendar_key=event.calendar_key,title=str(component.get('SUMMARY','')),start=component.decoded('DTSTART').isoformat(),end=component.decoded('DTEND').isoformat(),location=str(component.get('LOCATION','')),description=str(component.get('DESCRIPTION','')),etag=etag)
    except HTTPException:raise
    except Exception:raise HTTPException(502,'Could not load iCloud event') from None

def verify_saved(raw, expected):
    """Compare calendar semantics, allowing provider timezone/serialization normalization."""
    try:
        expected=Event.from_ical(expected.to_ical())
        events=Calendar.from_ical(raw).walk('VEVENT')
        if len(events)!=1: return False
        actual=events[0]
        for key in ('UID','SUMMARY','LOCATION','DESCRIPTION'):
            if str(actual.get(key,'')) != str(expected.get(key,'')): return False
        for key in ('DTSTART','DTEND'):
            value=actual.decoded(key)
            if not isinstance(value,datetime) or value.utcoffset() is None or value != expected.decoded(key): return False
        def rule(component):
            return {k:sorted(str(v) for v in values) for k,values in component.get('RRULE',{}).items()}
        if rule(actual)!=rule(expected): return False
        for key in ('RECURRENCE-ID','RDATE','EXDATE','ATTENDEE','ORGANIZER'):
            if actual.get(key)!=expected.get(key): return False
        return True
    except Exception: return False


def validate_request_plan(plan):
    # Never trust client-side disabled buttons or a stale missing_fields list.
    from concierge_workflow import prepare_preview
    missing=prepare_preview(dict(plan))['missing_fields']
    missing=list(dict.fromkeys([*missing,*(plan.get('missing_fields') or [])]))
    if missing: raise HTTPException(409,'Complete the request before saving: '+', '.join(missing))


def write(payload,event_id=None):
    if event_id and payload.repeat!="none":
        raise HTTPException(409,"Create a new repeating event; edit existing series in Apple Calendar")
    cfg,cal=selected(payload.calendar_key)
    try:
        with icloud_client(cfg['username'],cfg['password']) as client:
            if event_id:
                event=lookup(event_id)
                if not event or event.calendar_key!=payload.calendar_key:raise HTTPException(409,'Refresh the event before editing')
                url,response=read_resource(client,cal,event)
                if not payload.etag or response.headers.get('ETag')!=payload.etag:raise HTTPException(409,'Event changed in iCloud. Reload before saving.')
                container,component=editable(response.raw)
                headers={'If-Match':payload.etag}
            else:
                uid=f'family-agent-{payload.request_id}'
                url=cal['id'].rstrip('/')+'/'+uid+'.ics'
                component=Event();component.add('uid',uid);container=Calendar();container.add('version','2.0');container.add('prodid','-//Family Agent//EN');container.add_component(component)
                headers={'If-None-Match':'*'}
            zone=ZoneInfo(payload.timezone_name)
            if payload.repeat!='none':
                rule={'FREQ':payload.repeat.upper()}
                if payload.repeat_until:
                    rule['UNTIL']=datetime.combine(payload.repeat_until,time(23,59,59),zone).astimezone(timezone.utc)
                component.add('rrule',rule)
            for key,value in [('SUMMARY',payload.title),('DTSTART',payload.start.astimezone(zone)),('DTEND',payload.end.astimezone(zone)),('LOCATION',payload.location),('DESCRIPTION',payload.description),('DTSTAMP',datetime.now(timezone.utc))]:
                if key in component:del component[key]
                component.add(key,value)
            if 'DURATION' in component:del component['DURATION']
            headers['Content-Type']='text/calendar; charset=utf-8'
            result=client.put(url,container.to_ical().decode(),headers=headers)
            if result.status==412:
                # A retry after a lost response must verify the stable resource, never duplicate it.
                if not event_id:
                    prior=client.request(url)
                    if prior.status==200 and verify_saved(getattr(prior,'raw',b''),component):
                        with _calendar_cache_lock:_calendar_cache.clear()
                        return {'status':'saved'}
                raise HTTPException(409,'Event already exists or changed. Refresh Calendar before retrying.')
            if result.status not in (200,201,204):raise HTTPException(502,'iCloud did not accept the change')
            check=client.request(url)
            if check.status!=200 or not verify_saved(getattr(check,'raw',b''),component):raise HTTPException(502,'Save submitted but saved content could not be verified. Refresh before retrying; do not create another copy.')
        with _calendar_cache_lock:_calendar_cache.clear()
        return {'status':'saved'}
    except HTTPException:raise
    except Exception:raise HTTPException(502,'Could not verify iCloud save. Refresh Calendar before retrying.') from None

@router.post('/events')
def create(payload:Edit):return write(payload)
@router.put('/events/{event_id}')
def update(event_id:str,payload:Edit):return write(payload,event_id)


def save_request_event(item_id, event_index, payload):
    """Stable provider identity links an explicitly saved event to its request."""
    import json
    from uuid import uuid5, NAMESPACE_URL
    from database import SessionLocal
    from models import ConciergeInboxItem
    from sensitive_crypto import decrypt_text, encrypt_text
    with SessionLocal() as db:
        from sqlalchemy import select
        item=db.scalar(select(ConciergeInboxItem).where(ConciergeInboxItem.id==item_id).with_for_update())
        if item is None: raise HTTPException(404,'Request not found')
        plan=json.loads(decrypt_text(item.encrypted_plan))
        if plan.get('request_type')!='calendar':raise HTTPException(409,'This request is not an appointment')
        validate_request_plan(plan)
        count=max(1,len(plan.get('calendar_events') or []))
        if event_index<0 or event_index>=count:raise HTTPException(422,'Invalid appointment selection')
        receipt=(plan.get('calendar_receipts') or {}).get(str(event_index))
        if receipt:return {'status':'saved','uid':receipt['uid']}
        payload.request_id=uuid5(NAMESPACE_URL,f'family-agent-request:{item.message_guid}:{event_index}')
        write(payload)
        # Reload before attaching the receipt so concurrent edits are preserved.
        db.refresh(item)
        plan=json.loads(decrypt_text(item.encrypted_plan))
        uid=f'family-agent-{payload.request_id}'
        plan.setdefault('calendar_receipts',{})[str(event_index)]={'uid':uid,'calendar_key':payload.calendar_key}
        plan['saved_calendar_uid']=uid
        item.encrypted_plan=encrypt_text(json.dumps(plan))
        if len(plan['calendar_receipts'])>=count:
            item.status='handled';item.processed_at=datetime.now(timezone.utc)
        db.commit()
        return {'status':'saved','uid':uid}

@router.post('/requests/{item_id}/events/{event_index}')
def create_from_request(item_id:int,event_index:int,payload:Edit):
    return save_request_event(item_id,event_index,payload)
