"""Calendar-driven traffic checks, distinct from fixed calendar reminders."""
from datetime import datetime, timedelta, timezone
from math import ceil
import json
from uuid import uuid4
from urllib.parse import urlencode
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, Text, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from database import Base, get_db
from models import DepartureSettings, CalendarAlertRule, AlertContact, Alert
from schemas import CommuteResult
from sensitive_crypto import encrypt_text, decrypt_text
from calendar_service import upcoming_events, LOCAL_ZONE

router = APIRouter(prefix='/departure/traffic', tags=['Appointment traffic'])
DB = Annotated[Session, Depends(get_db)]

class AppointmentTraffic(Base):
    __tablename__ = 'appointment_traffic'
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    encrypted_context: Mapped[str] = mapped_column(Text)
    recipient_ids: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_check: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default='waiting')
    token: Mapped[str | None] = mapped_column(String(40))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[str | None] = mapped_column(String(20))
    disabled: Mapped[bool] = mapped_column(default=False)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def notification_time(start, seconds, buffer):
    return utc(start) - timedelta(minutes=max(45, ceil(seconds / 60) + buffer))


def reconcile(db):
    settings = db.get(DepartureSettings, 1)
    rule = db.get(CalendarAlertRule, 1)
    if not settings or not settings.home_address or not rule or not rule.enabled: return False
    data = upcoming_events()
    now = datetime.now(timezone.utc); active = set()
    # Read existing checks once, rather than one database lookup per calendar event.
    existing = {r.event_id: r for r in db.scalars(select(AppointmentTraffic))}
    for event in data['events']:
        if event.all_day or not event.busy or not event.departure_ready: continue
        start = datetime.fromisoformat(event.start.replace('Z', '+00:00'))
        if start <= now: continue
        active.add(event.id)
        context = dict(title=event.title, origin=settings.home_address, destination=event.location,
                       buffer=settings.arrival_buffer_minutes + settings.parking_walk_minutes,
                       default_recipient=rule.member_id)
        row = existing.get(event.id)
        if row is None:
            row = AppointmentTraffic(event_id=event.id, encrypted_context=encrypt_text(json.dumps(context)),
                starts_at=start, next_check=start-timedelta(hours=2), status='waiting', disabled=True)
            db.add(row)
        else:
            previous = json.loads(decrypt_text(row.encrypted_context))
            changed = utc(row.starts_at) != utc(start) or previous != context
            if (changed or row.status == 'cancelled') and row.status != 'notified':
                row.status='waiting'; row.token=None; row.next_check=start-timedelta(hours=2)
            if changed:
                row.starts_at=start; row.encrypted_context=encrypt_text(json.dumps(context))
    if data.get('conflict_check_complete'):
        for row in existing.values():
            if row.event_id not in active and row.status not in ('notified','cancelled'):
                row.status='cancelled';row.token=None
    db.flush()
    return bool(data.get('conflict_check_complete'))


def view(row):
    return dict(event_id=row.event_id, recipient_ids=json.loads(row.recipient_ids) if row.recipient_ids else [json.loads(decrypt_text(row.encrypted_context))['default_recipient']],
                status=row.status, disabled=row.disabled, starts_at=row.starts_at, next_check=row.next_check,
                last_checked=row.last_checked, duration_seconds=int(row.duration_seconds) if row.duration_seconds else None)

@router.get('')
def overview(db: DB):
    reconcile(db);db.commit()
    return [view(r) for r in db.scalars(select(AppointmentTraffic).where(AppointmentTraffic.starts_at>datetime.now(timezone.utc)))]

class Recipients(BaseModel):
    member_ids: list[int] = Field(max_length=20)
    disabled: bool = False

@router.put('/{event_id}/recipients')
def recipients(event_id: str, payload: Recipients, db: DB):
    row=db.get(AppointmentTraffic,event_id)
    if not row: raise HTTPException(404,'Refresh departures first')
    if not payload.disabled and not payload.member_ids: raise HTTPException(422,'Choose at least one recipient')
    for id in payload.member_ids:
        c=db.get(AlertContact,id)
        if not c or not c.enabled: raise HTTPException(422,'Each recipient needs an enabled messaging contact')
    row.recipient_ids=json.dumps(sorted(set(payload.member_ids)));row.disabled=payload.disabled
    if not row.disabled and row.status in ('cancelled', 'no_contact') and utc(row.starts_at)>datetime.now(timezone.utc):
        row.status='waiting'; row.token=None; row.next_check=utc(row.starts_at)-timedelta(hours=2)
    db.commit();return view(row)

@router.post('/claim')
def claim(db: DB):
    complete=reconcile(db); now=datetime.now(timezone.utc)
    if not complete: db.commit();return None
    rows=db.scalars(select(AppointmentTraffic).where(AppointmentTraffic.next_check<=now,
        AppointmentTraffic.starts_at>now, AppointmentTraffic.disabled.is_(False),
        AppointmentTraffic.status.in_(['waiting','checking'])).with_for_update(skip_locked=True))
    for row in rows:
        if row.status=='checking' and row.claimed_at and now-utc(row.claimed_at)<timedelta(minutes=3):continue
        row.status='checking';row.token=str(uuid4());row.claimed_at=now
        context=json.loads(decrypt_text(row.encrypted_context))
        db.commit()
        return dict(run_id=row.event_id, claim_token=row.token, origin_address=context['origin'],destination_address=context['destination'])
    db.commit();return None

class Result(CommuteResult):
    claim_token: str

@router.post('/{event_id}/complete')
def finish(event_id: str, result: Result, db: DB):
    row=db.scalar(select(AppointmentTraffic).where(AppointmentTraffic.event_id==event_id).with_for_update())
    if not row or row.token != result.claim_token: raise HTTPException(409,'Expired traffic claim')
    if row.status=='notified': return {'status':'notified'}
    if row.status!='checking': raise HTTPException(409,'Already processed')
    now=datetime.now(timezone.utc); start=utc(row.starts_at)
    if start<=now or row.disabled:
        row.status='cancelled';db.commit();return {'status':'cancelled'}
    context=json.loads(decrypt_text(row.encrypted_context))
    seconds=result.duration_seconds if not result.error else None
    row.last_checked=now;row.duration_seconds=str(seconds) if seconds else None
    due=notification_time(start,seconds or 0,context['buffer'] if seconds else 0)
    if now < due:
        row.status='waiting'; row.next_check=min(due,now+timedelta(minutes=15 if seconds else 5));row.token=None
        db.commit();return {'status':'waiting','next_check':row.next_check}
    start_text=start.astimezone(LOCAL_ZONE).strftime('%-I:%M %p')
    if seconds:
        departure=(start-timedelta(seconds=seconds,minutes=context['buffer'])).astimezone(LOCAL_ZONE).strftime('%-I:%M %p')
        text=f"{context['title'][:80]} starts at {start_text}. About {ceil(seconds/60)} min if you leave now. Leave by {departure} including {context['buffer']} min for arrival/parking."
    else:
        text=f"{context['title'][:80]} starts at {start_text}. Live traffic is unavailable. Check directions now; allow time for travel and parking."
    link='https://maps.apple.com/?'+urlencode(dict(saddr=context['origin'],daddr=context['destination'],dirflg='d'))
    if len(text+' '+link)<=500:text+=' '+link
    else:text+=' Open Departures for directions.'
    ids=json.loads(row.recipient_ids) if row.recipient_ids else [context['default_recipient']]
    contacts=list(db.scalars(select(AlertContact).where(AlertContact.member_id.in_(ids),AlertContact.enabled.is_(True))))
    for contact in contacts:
        db.add(Alert(member_id=contact.member_id,message=text[:500],scheduled_for=now))
    row.status='notified' if contacts else 'no_contact'
    db.commit();return {'status':row.status}

@router.get('/wake-plan')
def wake_plan(db: DB):
    now=datetime.now(timezone.utc)
    # OS helper only schedules future wake times; it never receives addresses or event titles.
    times=sorted(set(int(utc(r.next_check).timestamp())-60 for r in db.scalars(select(AppointmentTraffic).where(
        AppointmentTraffic.status=='waiting',AppointmentTraffic.disabled.is_(False),AppointmentTraffic.starts_at>now))
        if utc(r.next_check)>now+timedelta(minutes=1)))[:10]
    return {'wake_times':times}
