"""Local encrypted history; never deletes provider events."""
from datetime import datetime,timedelta,time,timezone
import json
from fastapi import APIRouter
from sqlalchemy import DateTime,String,Text,select,delete
from sqlalchemy.orm import Mapped,mapped_column
from database import Base,SessionLocal
from sensitive_crypto import encrypt_text,decrypt_text

router=APIRouter(prefix='/calendar',tags=['Calendar archive'])
class CalendarHistory(Base):
    __tablename__='calendar_history'
    event_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    ends_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    encrypted_event:Mapped[str]=mapped_column(Text)


def end_time(event,zone):
    if not event.end or not getattr(event,'end_known',True):return None
    try:
        end=datetime.combine(datetime.fromisoformat(event.end).date(),time.min,zone) if event.all_day else datetime.fromisoformat(event.end.replace('Z','+00:00'))
        if end.tzinfo is None:return None
        if not event.all_day and event.end==event.start:return None
        return end.astimezone(timezone.utc)
    except ValueError:return None


def maintain(events, complete, zone):
    if not complete:return
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        existing={r.event_id:r for r in db.scalars(select(CalendarHistory))}
        for event in events:
            end=end_time(event,zone)
            if end is None or end<now-timedelta(days=90):continue
            value=json.dumps(event.model_dump(),sort_keys=True)
            row=existing.get(event.id)
            if row is None:db.add(CalendarHistory(event_id=event.id,ends_at=end,encrypted_event=encrypt_text(value)))
            elif decrypt_text(row.encrypted_event)!=value:row.ends_at=end;row.encrypted_event=encrypt_text(value)
        db.execute(delete(CalendarHistory).where(CalendarHistory.ends_at<now-timedelta(days=90)).execution_options(synchronize_session=False))
        db.commit()

@router.get('/archive')
def archive():
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        return [json.loads(decrypt_text(r.encrypted_event)) for r in db.scalars(select(CalendarHistory).where(
            CalendarHistory.ends_at<=now-timedelta(hours=1),CalendarHistory.ends_at>=now-timedelta(days=90)).order_by(CalendarHistory.ends_at.desc()))]
