"""One-time, directional traffic updates delivered by the existing Mac bridge."""
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from database import Base, get_db
from models import Alert, AlertContact
from schemas import CommuteResult
from sensitive_crypto import encrypt_text, decrypt_text

router=APIRouter(prefix='/traffic/checks',tags=['Traffic'])
DB=Annotated[Session,Depends(get_db)]


class TrafficCheck(Base):
    __tablename__='traffic_checks'
    id: Mapped[int]=mapped_column(primary_key=True)
    request_key: Mapped[str]=mapped_column(String(100),unique=True)
    member_id: Mapped[int]=mapped_column(ForeignKey('family_members.id'))
    label: Mapped[str]=mapped_column(String(100))
    encrypted_origin: Mapped[str]=mapped_column(Text)
    encrypted_destination: Mapped[str]=mapped_column(Text)
    scheduled_for: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    status: Mapped[str]=mapped_column(String(20),default='queued',index=True)
    claim_token: Mapped[str | None]=mapped_column(String(40))
    claimed_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    alert_id: Mapped[int | None]=mapped_column(ForeignKey('alerts.id'),unique=True)


class TrafficCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    request_key: str=Field(min_length=1,max_length=100)
    member_id: int=Field(gt=0)
    label: str=Field(min_length=1,max_length=100)
    origin_address: str=Field(min_length=5,max_length=300)
    destination_address: str=Field(min_length=5,max_length=300)
    scheduled_for: datetime

    @field_validator('scheduled_for')
    @classmethod
    def aware(cls,value):
        if value.utcoffset() is None:raise ValueError('Include a timezone')
        return value


class TrafficResult(CommuteResult):
    claim_token: str=Field(min_length=1,max_length=40)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def summary(row):
    return {'id':row.id,'member_id':row.member_id,'label':row.label,'scheduled_for':row.scheduled_for,
            'expires_at':row.expires_at,'status':row.status,'alert_id':row.alert_id}


@router.post('')
def create_check(payload:TrafficCreate,db:DB):
    # A member-row lock serializes duplicate requests without storing contact details.
    from models import FamilyMember
    if db.scalar(select(FamilyMember.id).where(FamilyMember.id==payload.member_id).with_for_update()) is None:
        raise HTTPException(404,'Family member not found')
    existing=db.scalar(select(TrafficCheck).where(TrafficCheck.request_key==payload.request_key))
    if existing:
        if (existing.member_id!=payload.member_id or existing.label!=payload.label
            or decrypt_text(existing.encrypted_origin)!=payload.origin_address
            or decrypt_text(existing.encrypted_destination)!=payload.destination_address
            or utc(existing.scheduled_for)!=utc(payload.scheduled_for)):
            raise HTTPException(409,'This request key already has different traffic details')
        return summary(existing)
    contact=db.get(AlertContact,payload.member_id)
    if contact is None or not contact.enabled:raise HTTPException(422,'Enable a messaging contact first')
    if utc(payload.scheduled_for)<datetime.now(timezone.utc):raise HTTPException(422,'Choose a future traffic check time')
    row=TrafficCheck(request_key=payload.request_key,member_id=payload.member_id,label=payload.label,
        encrypted_origin=encrypt_text(payload.origin_address),encrypted_destination=encrypt_text(payload.destination_address),
        scheduled_for=payload.scheduled_for,expires_at=payload.scheduled_for+timedelta(minutes=30))
    db.add(row);db.commit();db.refresh(row)
    return summary(row)


@router.get('')
def list_checks(db:DB):
    return [summary(r) for r in db.scalars(select(TrafficCheck).order_by(TrafficCheck.id.desc()).limit(50)).all()]


@router.post('/claim')
def claim_check(db:DB):
    now=datetime.now(timezone.utc)
    rows=db.scalars(select(TrafficCheck).where(TrafficCheck.status.in_(['queued','claimed']))
        .order_by(TrafficCheck.scheduled_for,TrafficCheck.id).with_for_update(skip_locked=True)).all()
    for row in rows:
        if utc(row.expires_at)<=now:
            row.status='expired';continue
        if utc(row.scheduled_for)>now:continue
        if row.status=='claimed' and row.claimed_at and utc(row.claimed_at)>now-timedelta(minutes=10):continue
        contact=db.get(AlertContact,row.member_id)
        if contact is None or not contact.enabled:
            row.status='failed';continue
        row.status='claimed';row.claim_token=str(uuid4());row.claimed_at=now
        result={'run_id':row.id,'claim_token':row.claim_token,'label':row.label,
                'origin_address':decrypt_text(row.encrypted_origin),'destination_address':decrypt_text(row.encrypted_destination)}
        db.commit();return result
    db.commit();return None


@router.post('/{check_id}/complete')
def complete_check(check_id:int,payload:TrafficResult,db:DB):
    row=db.scalar(select(TrafficCheck).where(TrafficCheck.id==check_id).with_for_update())
    if row is None:raise HTTPException(404,'Traffic check not found')
    if row.claim_token!=payload.claim_token:raise HTTPException(409,'This claim is no longer current')
    if row.alert_id is not None:return summary(row)
    if row.status!='claimed':raise HTTPException(409,'Traffic check is not claimed')
    if utc(row.expires_at)<=datetime.now(timezone.utc):
        row.status='expired';db.commit();raise HTTPException(409,'Traffic check has expired')
    directions='https://maps.apple.com/?'+urlencode({'saddr':decrypt_text(row.encrypted_origin),
        'daddr':decrypt_text(row.encrypted_destination),'dirflg':'d'})
    text=(f'{row.label}: about {max(1,round(payload.duration_seconds/60))} min with current traffic.'
          if payload.duration_seconds else f'{row.label}: traffic is unavailable right now.')
    message=text+' Directions: '+directions
    if len(message)>500:message=text+' Open Maps for current directions.'
    alert=Alert(member_id=row.member_id,message=message,scheduled_for=datetime.now(timezone.utc))
    db.add(alert);db.flush()
    row.alert_id=alert.id;row.status='completed' if payload.duration_seconds else 'failed'
    db.commit();db.refresh(row);return summary(row)
