from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Annotated
from urllib.parse import urlencode

from regional_settings import REGIONAL

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from traffic_checks import router as traffic_router
from database import Base, engine, get_db
from models import (
    Alert, AlertContact, CalendarAlertMarker, CalendarAlertRule, CalendarAssignment, CommuteRun,
    CommuteSchedule, ConciergeInboxItem, ConciergeReplyReceipt,
    DepartureSettings, DepartureTripPreference, FamilyMember, MorningBriefingMarker, MorningBriefingRun,
    MorningBriefingPreference, MorningBriefingSettings, Task, WeatherSettings,
)
from schemas import (
    AlertClaim, AlertContactRead, AlertContactsBulkUpdate, AlertContactUpdate, AlertCreate, AlertRead,
    CalendarAlertRuleRead, CalendarAlertRuleUpdate, CalendarAssignmentsUpdate, CommuteClaim,
    CommuteResult, CommuteScheduleRead, CommuteScheduleUpdate, DepartureSettingsRead,
    DepartureSettingsUpdate, DepartureTripRead, DepartureTripUpdate, FamilyDirectoryUpdate,
    MemberCreate, MemberCreateWithContact, MemberProfileUpdate, MemberRead,
    TaskCreate, TaskRead, TaskStatus, TaskStatusUpdate,
    ConciergeInboxRequest, ConciergeInboxStatus, ConciergeInboxStatusUpdate,
    ConciergePlanUpdate, ConciergePreviewRequest, ConciergeReplyRequest, MorningBriefingUpdate, WeatherSettingsRead, WeatherSettingsUpdate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from messaging_settings import load_settings
    load_settings()  # Validate optional transport configuration before accepting work.
    from auth_service import initialize_keys
    initialize_keys()
    # Creates missing tables without dropping existing tables or data.
    # Future schema changes should use versioned migrations.
    Base.metadata.create_all(bind=engine)
    # Additive upgrades for databases created by earlier Family Agent versions.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminder_minutes_before INTEGER"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS repeat_interval VARCHAR(20) NOT NULL DEFAULT 'none'"))
        connection.execute(text("ALTER TABLE family_members ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'adult'"))
        connection.execute(text("ALTER TABLE family_members ADD COLUMN IF NOT EXISTS encrypted_age TEXT"))
        connection.execute(text("ALTER TABLE alert_contacts ALTER COLUMN imessage_handle TYPE TEXT"))
        connection.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE"))
        connection.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE concierge_inbox_items ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
        connection.execute(text("ALTER TABLE concierge_inbox_items ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_concierge_inbox_items_status ON concierge_inbox_items (status)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_alerts_task_id ON alerts (task_id) WHERE task_id IS NOT NULL"))
        if engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alert_status_valid"))
            connection.execute(text("ALTER TABLE alerts ADD CONSTRAINT alert_status_valid CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'uncertain'))"))
        from sensitive_crypto import encrypt_text, is_encrypted

        contacts = connection.execute(text("SELECT member_id, imessage_handle FROM alert_contacts")).mappings().all()
        for contact in contacts:
            if contact["imessage_handle"] and not is_encrypted(contact["imessage_handle"]):
                connection.execute(
                    text("UPDATE alert_contacts SET imessage_handle = :value WHERE member_id = :member_id"),
                    {"value": encrypt_text(contact["imessage_handle"]), "member_id": contact["member_id"]},
                )
    yield
    engine.dispose()


app = FastAPI(title="Personal Agent / Concierge Framework API", lifespan=lifespan)
from auth_service import AuthenticationMiddleware, router as auth_router
app.add_middleware(AuthenticationMiddleware)
app.include_router(auth_router)
app.include_router(traffic_router)
from events_service import router as events_router
app.include_router(events_router)
from appointment_traffic import router as appointment_traffic_router
app.include_router(appointment_traffic_router)
from calendar_archive import router as archive_router
from icloud_editor import router as icloud_editor_router
app.include_router(archive_router)
app.include_router(icloud_editor_router)
DB = Annotated[Session, Depends(get_db)]


@app.get("/")
def root():
    return {"message": "Family Agent is running"}


@app.get("/settings/regional")
def regional_settings():
    from messaging_settings import provider
    return {**REGIONAL.public(), 'messaging_provider': provider()}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get('/health/database')
def database_health(db: DB):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}


@app.get("/health/self-healing")
def self_healing_status():
    from calendar_service import CONFIG

    path = CONFIG / "self-healing-state.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        return report if isinstance(report, dict) else {"status": "never_run"}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "never_run", "checks": [], "actions": [], "issues": []}


@app.get("/places/status")
def places_status():
    from places_service import configured

    return {"configured": configured()}


@app.get("/places/autocomplete")
def places_autocomplete(q: str = Query(min_length=3, max_length=200)):
    from places_service import address_suggestions, configured

    if not configured():
        raise HTTPException(409, "Google address suggestions are not configured")
    q = q.strip()
    if len(q) < 3:
        raise HTTPException(422, "Enter at least three address characters")
    try:
        return {"suggestions": address_suggestions(q)}
    except RuntimeError:
        raise HTTPException(502, "Google address suggestions are temporarily unavailable")


from schemas import ConciergeWebRequest

@app.post("/concierge/requests")
def create_web_request(payload: ConciergeWebRequest, db: DB):
    """Persist browser requests in the same encrypted conversation as iMessage."""
    from uuid import UUID
    from calendar_service import LOCAL_ZONE
    from concierge_chain import run_request
    from concierge_dialog import finish
    from sensitive_crypto import encrypt_text
    try: key = "web:" + str(UUID(payload.request_id))
    except ValueError: raise HTTPException(422, "Invalid request identifier")
    member = db.scalar(select(FamilyMember).where(FamilyMember.id == payload.member_id).with_for_update())
    if member is None: raise HTTPException(404, "Choose a saved family member")
    existing = db.scalar(select(ConciergeInboxItem).where(ConciergeInboxItem.message_guid == key))
    if existing:
        if existing.member_id != payload.member_id: raise HTTPException(409, "Request belongs to another member")
        return concierge_inbox_payload(existing)
    members = db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all()
    plan = finish(run_request(payload.text, [m.name for m in members], datetime.now(LOCAL_ZONE),
        [{"name": m.name, "role": m.role, "age": m.age} for m in members], requester_name=member.name))
    item = ConciergeInboxItem(message_guid=key, member_id=member.id,
        encrypted_request=encrypt_text(payload.text), encrypted_plan=encrypt_text(json.dumps(plan)),
        received_at=datetime.now(timezone.utc))
    if plan.get('request_type') in ('acknowledgment', 'schedule_query', 'events') and not plan.get('missing_fields'):
        item.status='handled'; item.processed_at=datetime.now(timezone.utc)
    db.add(item); db.commit(); db.refresh(item)
    return concierge_inbox_payload(item)


@app.post("/concierge/preview")
def preview_concierge_request(payload: ConciergePreviewRequest, db: DB):
    from calendar_service import LOCAL_ZONE
    from concierge_chain import run_request as preview_request

    members = db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all()
    requester_name = next(
        (member.name for member in members if payload.requester_name and member.name.casefold() == payload.requester_name.casefold()),
        None,
    )
    return preview_request(
        payload.text,
        [member.name for member in members],
        datetime.now(LOCAL_ZONE),
        [{"name": member.name, "role": member.role, "age": member.age} for member in members],
        payload.driver,
        requester_name,
        payload.transportation_mode,
        payload.pickup_by,
        payload.combine_adjacent_events,
    )


def concierge_inbox_payload(item: ConciergeInboxItem):
    from sensitive_crypto import decrypt_text

    request_text = decrypt_text(item.encrypted_request) or ""
    plan_text = decrypt_text(item.encrypted_plan) or "{}"
    try:
        plan = json.loads(plan_text)
    except json.JSONDecodeError:
        plan = {"request_type": "needs_review", "missing_fields": ["readable saved plan"]}
    return {
        "id": item.id,
        "member_name": item.member_name,
        "request_text": request_text,
        "plan": plan,
        "received_at": item.received_at,
        "status": item.status,
        "processed_at": item.processed_at,
    }


@app.post("/concierge/inbox")
def receive_concierge_imessage(payload: ConciergeInboxRequest, db: DB):
    from calendar_service import LOCAL_ZONE
    from concierge_inbox import handles_match, strip_agent_prefix
    from concierge_chain import run_request as preview_request
    from sensitive_crypto import encrypt_text

    request_text = strip_agent_prefix(payload.text)
    if request_text is None:
        return {"status": "ignored"}
    contacts = db.scalars(select(AlertContact).where(AlertContact.enabled.is_(True))).all()
    contact = next((item for item in contacts if handles_match(item.imessage_handle, payload.sender_handle)), None)
    if contact is None:
        return {"status": "ignored"}
    # Serialize new messages from the same household member, including retries.
    db.execute(select(FamilyMember.id).where(FamilyMember.id == contact.member_id).with_for_update())
    message_key = hashlib.sha256(payload.message_guid.encode("utf-8")).hexdigest()
    receipt = db.get(ConciergeReplyReceipt, message_key)
    if receipt:
        return {"status": "planned", "item": concierge_inbox_payload(db.get(ConciergeInboxItem, receipt.item_id))}
    import re
    reply = re.fullmatch(r"#(\d+)\s+(.+)", request_text, re.DOTALL)
    if reply:
        item = db.get(ConciergeInboxItem, int(reply.group(1)))
        if item is None or item.member_id != contact.member_id:
            return {"status": "ignored"}
        if item.status != "pending" or concierge_inbox_payload(item)["plan"].get("dialog_state") == "ready_for_review":
            return {"status": "ignored"}
        return apply_concierge_reply(item, reply.group(2), message_key, db, send_reply=True)

    existing = db.scalar(select(ConciergeInboxItem).where(ConciergeInboxItem.message_guid == message_key))
    if existing is not None:
        return {"status": "planned", "item": concierge_inbox_payload(existing)}
    members = db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all()
    plan = preview_request(
        request_text,
        [member.name for member in members],
        datetime.now(LOCAL_ZONE),
        [{"name": member.name, "role": member.role, "age": member.age} for member in members],
        requester_name=contact.member_name,
    )
    from concierge_dialog import finish, reply_message
    plan = finish(plan)
    item = ConciergeInboxItem(
        message_guid=message_key,
        member_id=contact.member_id,
        encrypted_request=encrypt_text(request_text),
        encrypted_plan=encrypt_text(json.dumps(plan, ensure_ascii=False)),
        received_at=payload.received_at or datetime.now(timezone.utc),
    )
    if plan.get('request_type') == 'acknowledgment':
        item.status = 'handled'
        item.processed_at = datetime.now(timezone.utc)
    db.add(item)
    db.flush()
    db.add(Alert(member_id=contact.member_id, message=reply_message(item.id, plan), scheduled_for=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(item)
    return {"status": "planned", "item": concierge_inbox_payload(item)}


def apply_concierge_reply(item, answer, message_key, db, send_reply=False):
    from calendar_service import LOCAL_ZONE
    from concierge_dialog import advance, reply_message
    from sensitive_crypto import encrypt_text

    stored = concierge_inbox_payload(item)
    plan = stored['plan']
    if 'dialog_state' not in plan:
        from concierge_dialog import finish
        plan = finish(plan)
    if plan.get('dialog_state') != 'awaiting_details':
        raise HTTPException(409, "This draft is ready for review. Open the plan to make changes.")
    members = db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all()
    plan = advance(plan, answer, [m.name for m in members],
        [{"name": m.name, "role": m.role, "age": m.age} for m in members],
        datetime.now(LOCAL_ZONE), item.member_name)
    history = stored['plan'].get('dialog_answers', [])
    if len(history) >= 30:
        raise HTTPException(409, "Please finish this request in the dashboard.")
    plan['dialog_answers'] = [*history, answer]
    item.encrypted_plan = encrypt_text(json.dumps(plan, ensure_ascii=False))
    db.add(ConciergeReplyReceipt(message_key=message_key, item_id=item.id))
    if send_reply:
        db.add(Alert(member_id=item.member_id, message=reply_message(item.id, plan), scheduled_for=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(item)
    return {"status": "planned", "item": concierge_inbox_payload(item)}


@app.post("/concierge/inbox/{item_id}/reply")
def reply_to_concierge(item_id: int, payload: ConciergeReplyRequest, db: DB):
    item = db.get(ConciergeInboxItem, item_id)
    if item is None:
        raise HTTPException(404, "Concierge request not found")
    db.execute(select(FamilyMember.id).where(FamilyMember.id == item.member_id).with_for_update())
    db.refresh(item)
    key = hashlib.sha256((f"dashboard:{item_id}:" + payload.message_guid).encode()).hexdigest()
    if db.get(ConciergeReplyReceipt, key):
        return {"status": "planned", "item": concierge_inbox_payload(item)}
    if item.status != "pending":
        raise HTTPException(409, "Only a pending draft can receive replies")
    return apply_concierge_reply(item, payload.text, key, db)


@app.get("/concierge/inbox")
def list_concierge_imessages(
    db: DB,
    status: ConciergeInboxStatus | None = "pending",
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(ConciergeInboxItem)
    if status is not None:
        query = query.where(ConciergeInboxItem.status == status)
    items = db.scalars(
        query.order_by(ConciergeInboxItem.received_at.desc(), ConciergeInboxItem.id.desc()).offset(offset).limit(limit)
    ).all()
    return [concierge_inbox_payload(item) for item in items]


@app.patch("/concierge/inbox/{item_id}")
def update_concierge_imessage(item_id: int, payload: ConciergeInboxStatusUpdate, db: DB):
    item = db.get(ConciergeInboxItem, item_id)
    if item is None:
        raise HTTPException(404, "Concierge request not found")
    item.status = payload.status
    item.processed_at = None if payload.status == "pending" else datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return concierge_inbox_payload(item)


@app.put("/concierge/inbox/{item_id}/plan")
def update_concierge_plan(item_id: int, payload: ConciergePlanUpdate, db: DB):
    from calendar_service import LOCAL_ZONE
    from concierge_chain import run_request as preview_request
    from sensitive_crypto import decrypt_text, encrypt_text

    item = db.get(ConciergeInboxItem, item_id)
    if item is None:
        raise HTTPException(404, "Concierge request not found")
    if item.status != "pending":
        raise HTTPException(409, "Only a pending Concierge plan can be edited")
    if not decrypt_text(item.encrypted_request):
        raise HTTPException(409, "The saved Concierge request could not be read")
    members = db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all()
    saved = concierge_inbox_payload(item)
    if saved['plan'].get('dialog_state') and payload.text == saved['request_text']:
        from concierge_dialog import finish
        from concierge_workflow import extract_details, combine_adjacent_calendar_events
        plan = saved['plan']
        details = extract_details({"normalized_text": f"{plan.get('primary_member') or ''} {plan.get('title') or ''}",
            "now": datetime.now(LOCAL_ZONE).isoformat(), "member_names": [m.name for m in members],
            "family_profiles": [{"name": m.name, "role": m.role, "age": m.age} for m in members],
            "request_type": plan['request_type'], "requested_driver": payload.driver or plan.get('driver'),
            "requested_transportation_mode": payload.transportation_mode or plan.get('transportation_mode'),
            "requested_pickup_by": payload.pickup_by or plan.get('pickup_by')})
        for key in ('subject_role','subject_age','requires_parent_driver','driver','driver_options',
                    'transportation_mode','requires_pickup','pickup_by','pickup_options'):
            plan[key] = details[key]
        if payload.combine_adjacent_events:
            plan['calendar_events'] = combine_adjacent_calendar_events(plan.get('calendar_events', []))
        plan = finish(plan)
    else:
        plan = preview_request(
            payload.text,
            [member.name for member in members],
            datetime.now(LOCAL_ZONE),
            [{"name": member.name, "role": member.role, "age": member.age} for member in members],
            payload.driver,
            item.member_name,
            payload.transportation_mode,
            payload.pickup_by,
            payload.combine_adjacent_events,
        )
    if payload.edits is not None:
        from concierge_dialog import finish
        from concierge_workflow import extract_details
        edits = payload.edits.model_dump()
        names = {m.name for m in members}
        if edits['primary_member'] not in names or not set(edits['notification_members']).issubset(names):
            raise HTTPException(422, 'Choose saved family members')
        end_time = edits.pop('end_time')
        plan.update(edits)
        if len(plan.get('calendar_events', [])) > 1:
            raise HTTPException(422, 'Edit multi-event requests separately before changing these fields')
        if not plan['time']:
            plan['calendar_events'] = []
        if plan.get('calendar_events'):
            plan['calendar_events'][0].update(title=plan['title'], start_time=plan['time'], end_time=end_time)
        elif end_time and plan['request_type'] == 'calendar':
            plan['calendar_events'] = [dict(title=plan['title'], start_time=plan['time'], end_time=end_time)]
        if end_time and (not plan['time'] or end_time <= plan['time']):
            raise HTTPException(422, 'End time must be later than start time')
        details = extract_details({'normalized_text':plan['primary_member'], 'now':datetime.now(LOCAL_ZONE).isoformat(),
            'member_names':list(names), 'family_profiles':[{'name':m.name,'role':m.role,'age':m.age} for m in members],
            'request_type':plan['request_type'], 'llm_plan':{'primary_member':plan['primary_member']},
            'requested_driver':payload.driver, 'requested_pickup_by':payload.pickup_by,
            'requested_transportation_mode':payload.transportation_mode})
        for key in ('subject_role','subject_age','requires_parent_driver','driver','driver_options','transportation_mode','requires_pickup','pickup_by','pickup_options'):
            plan[key] = details[key]
        plan = finish(plan)
    for receipt_key in ('saved_task_id','saved_calendar_uid','calendar_receipts'):
        if receipt_key in saved['plan']: plan[receipt_key]=saved['plan'][receipt_key]
    item.encrypted_request = encrypt_text(payload.text)
    item.encrypted_plan = encrypt_text(json.dumps(plan, ensure_ascii=False))
    item.status = "pending" if payload.keep_in_inbox or plan.get("missing_fields") else "handled"
    item.processed_at = None if item.status == "pending" else datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return concierge_inbox_payload(item)


@app.post("/family-members", response_model=MemberRead, status_code=201)
def create_member(payload: MemberCreate, db: DB):
    from sensitive_crypto import encrypt_age

    member = FamilyMember(name=payload.name, role=payload.role, encrypted_age=encrypt_age(payload.age))
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@app.post("/family-members/with-contact", response_model=MemberRead, status_code=201)
def create_member_with_contact(payload: MemberCreateWithContact, db: DB):
    from sensitive_crypto import encrypt_age, encrypt_text

    member = FamilyMember(
        name=payload.name,
        role=payload.role,
        encrypted_age=encrypt_age(payload.age),
    )
    db.add(member)
    db.flush()
    if payload.imessage_handle is not None:
        db.add(AlertContact(
            member_id=member.id,
            encrypted_imessage_handle=encrypt_text(payload.imessage_handle),
            enabled=payload.alerts_enabled,
        ))
    db.commit()
    db.refresh(member)
    return member


@app.put("/family-members/directory")
def save_family_directory(payload: FamilyDirectoryUpdate, db: DB):
    from sensitive_crypto import encrypt_age, encrypt_text

    member_ids = [item.member_id for item in payload.members]
    if len(member_ids) != len(set(member_ids)):
        raise HTTPException(422, "Each family member can appear only once")
    members = {member.id: member for member in db.scalars(
        select(FamilyMember).where(FamilyMember.id.in_(member_ids))
    ).all()}
    if len(members) != len(member_ids):
        raise HTTPException(404, "One or more family members were not found")
    contacts = {contact.member_id: contact for contact in db.scalars(
        select(AlertContact).where(AlertContact.member_id.in_(member_ids))
    ).all()}
    for item in payload.members:
        member = members[item.member_id]
        member.role = item.role
        member.encrypted_age = encrypt_age(item.age)
        contact = contacts.get(item.member_id)
        if item.imessage_handle is None:
            if contact is not None:
                db.delete(contact)
        elif contact is None:
            db.add(AlertContact(
                member_id=item.member_id,
                encrypted_imessage_handle=encrypt_text(item.imessage_handle),
                enabled=item.alerts_enabled,
            ))
        else:
            contact.encrypted_imessage_handle = encrypt_text(item.imessage_handle)
            contact.enabled = item.alerts_enabled
    db.commit()
    return {"status": "saved", "members": len(payload.members)}


@app.patch("/family-members/{member_id}", response_model=MemberRead)
def update_member_profile(member_id: int, payload: MemberProfileUpdate, db: DB):
    from sensitive_crypto import encrypt_age

    member = db.get(FamilyMember, member_id)
    if member is None:
        raise HTTPException(404, "Family member not found")
    if "role" in payload.model_fields_set and payload.role is not None:
        member.role = payload.role
    if "age" in payload.model_fields_set:
        member.encrypted_age = encrypt_age(payload.age)
    db.commit()
    db.refresh(member)
    return member


@app.get("/family-members", response_model=list[MemberRead])
def list_members(db: DB, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return db.scalars(select(FamilyMember).order_by(FamilyMember.id).offset(offset).limit(limit)).all()


@app.get("/calendar/assignments")
def get_calendar_assignments(db: DB):
    from calendar_service import available_calendars

    assignments = {}
    for assignment in db.scalars(select(CalendarAssignment)).all():
        assignments.setdefault(assignment.calendar_key, []).append(assignment.member_id)
    return {
        "calendars": [
            {**calendar, "member_ids": sorted(assignments.get(calendar["key"], []))}
            for calendar in available_calendars()
        ],
        "members": [
            {"id": member.id, "name": member.name}
            for member in db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all()
        ],
    }


@app.put("/calendar/assignments")
def save_calendar_assignments(payload: CalendarAssignmentsUpdate, db: DB):
    from calendar_service import available_calendars

    calendar_keys = [item.calendar_key for item in payload.assignments]
    if len(calendar_keys) != len(set(calendar_keys)):
        raise HTTPException(422, "Each calendar can appear only once")
    valid_calendars = {calendar["key"] for calendar in available_calendars()}
    if set(calendar_keys) != valid_calendars:
        raise HTTPException(422, "Refresh and choose from the available calendars")
    valid_members = set(db.scalars(select(FamilyMember.id)).all())
    for item in payload.assignments:
        if len(item.member_ids) != len(set(item.member_ids)):
            raise HTTPException(422, "A calendar cannot list the same family member twice")
        if not set(item.member_ids).issubset(valid_members):
            raise HTTPException(404, "One or more family members were not found")
    for assignment in db.scalars(select(CalendarAssignment)).all():
        db.delete(assignment)
    for item in payload.assignments:
        for member_id in item.member_ids:
            db.add(CalendarAssignment(calendar_key=item.calendar_key, member_id=member_id))
    db.commit()
    return get_calendar_assignments(db)


def resolve_member(value: int | str, db: Session) -> int:
    if isinstance(value, int):
        if value <= 0:
            raise HTTPException(422, "Member ID must be positive")
        member = db.get(FamilyMember, value)
        if member is None:
            raise HTTPException(404, "Assigned family member not found")
        return member.id
    name = value.strip()
    if not name:
        raise HTTPException(422, "Enter a family member name or ID")
    matches = db.scalars(select(FamilyMember).where(func.lower(FamilyMember.name) == func.lower(name)).limit(2)).all()
    if len(matches) > 1:
        raise HTTPException(409, "More than one family member has this name. Use their numeric ID.")
    if matches:
        return matches[0].id
    # Query parameters arrive as strings; keep numeric-ID filters working.
    if name.isascii() and name.isdecimal():
        return resolve_member(int(name), db)
    raise HTTPException(404, "No family member found with that name. Check GET /family-members.")


def task_values(payload, db):
    values = payload.model_dump()
    if payload.assigned_to is not None:
        values["assigned_to"] = resolve_member(payload.assigned_to, db)
    if payload.reminder_minutes_before is not None:
        if payload.due_at <= datetime.now(timezone.utc):
            raise HTTPException(422, "Choose a future due time for an iMessage reminder")
        contact = db.get(AlertContact, values["assigned_to"])
        if contact is None or not contact.enabled:
            raise HTTPException(409, "Add and enable this family member's iMessage contact first")
    return values

@app.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(payload: TaskCreate, db: DB):
    task = Task(**task_values(payload, db))
    db.add(task); db.flush(); sync_task_alert(task, db)
    db.commit(); db.refresh(task)
    return task

@app.put("/tasks/{task_id}", response_model=TaskRead)
def edit_task(task_id: int, payload: TaskCreate, db: DB):
    task=db.get(Task,task_id)
    if task is None: raise HTTPException(404,"Task not found")
    for key,value in task_values(payload, db).items(): setattr(task,key,value)
    sync_task_alert(task,db);db.commit();db.refresh(task)
    return task

@app.post("/concierge/inbox/{item_id}/task", response_model=TaskRead)
def create_request_task(item_id: int, payload: TaskCreate, db: DB):
    from sensitive_crypto import encrypt_text
    item=db.scalar(select(ConciergeInboxItem).where(ConciergeInboxItem.id==item_id).with_for_update())
    if item is None: raise HTTPException(404,"Request not found")
    plan=concierge_inbox_payload(item)['plan']
    if plan.get('saved_task_id'):
        task=db.get(Task,plan['saved_task_id'])
        if task is None: raise HTTPException(409,"Linked task is no longer available")
        return task
    if plan.get('request_type')!='task' or plan.get('missing_fields'):
        raise HTTPException(409,"Complete and save this task draft before creating it")
    task=Task(**task_values(payload,db));db.add(task);db.flush();sync_task_alert(task,db)
    plan['saved_task_id']=task.id
    item.encrypted_plan=encrypt_text(json.dumps(plan));item.status='handled';item.processed_at=datetime.now(timezone.utc)
    db.commit();db.refresh(task)
    return task


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks(db: DB, status: TaskStatus | None = None,
               assigned_to: str | None = Query(None, min_length=1, max_length=100, description="Family member name or numeric ID"),
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    query = select(Task).order_by(Task.id)
    if status is not None:
        query = query.where(Task.status == status)
    if assigned_to is not None:
        query = query.where(Task.assigned_to == resolve_member(assigned_to, db))
    return db.scalars(query.offset(offset).limit(limit)).all()


@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task_status(task_id: int, payload: TaskStatusUpdate, db: DB):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if payload.status == "completed" and task.repeat_interval == "weekly" and task.due_at is not None:
        from task_recurrence import next_weekly_due

        task.due_at = next_weekly_due(task.due_at, datetime.now(timezone.utc))
        task.status = "pending"
    else:
        task.status = payload.status
    sync_task_alert(task, db)
    db.commit()
    db.refresh(task)
    return task


def sync_task_alert(task: Task, db: Session) -> None:
    from calendar_service import LOCAL_ZONE

    alert = db.scalar(select(Alert).where(Alert.task_id == task.id))
    should_remind = (
        task.status != "completed"
        and task.assigned_to is not None
        and task.due_at is not None
        and task.reminder_minutes_before is not None
    )
    if not should_remind:
        if alert is not None and alert.status == "pending":
            db.delete(alert)
        return

    scheduled_for = task.due_at - timedelta(minutes=task.reminder_minutes_before)
    due_text = task.due_at.astimezone(LOCAL_ZONE).strftime("%a, %b %d at %-I:%M %p")
    message = f"Task reminder: {task.title[:180]} is due {due_text}."
    if alert is None:
        db.add(Alert(
            task_id=task.id,
            member_id=task.assigned_to,
            message=message,
            scheduled_for=scheduled_for,
        ))
    elif alert.status == "pending":
        alert.member_id = task.assigned_to
        alert.message = message
        alert.scheduled_for = scheduled_for
    else:
        db.delete(alert)
        db.flush()
        db.add(Alert(
            task_id=task.id,
            member_id=task.assigned_to,
            message=message,
            scheduled_for=scheduled_for,
        ))


@app.get("/departure/settings", response_model=DepartureSettingsRead)
def get_departure_settings(db: DB):
    settings = db.get(DepartureSettings, 1)
    if settings is None:
        return DepartureSettingsRead(
            configured=False, home_address="",
            arrival_buffer_minutes=10, parking_walk_minutes=10,
        )
    return settings


@app.put("/departure/settings", response_model=DepartureSettingsRead)
def save_departure_settings(payload: DepartureSettingsUpdate, db: DB):
    settings = db.get(DepartureSettings, 1)
    if settings is None:
        settings = DepartureSettings(id=1, **payload.model_dump())
        db.add(settings)
    else:
        for key, value in payload.model_dump().items():
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings


@app.get("/departure/trips", response_model=list[DepartureTripRead])
def list_departure_trips(db: DB):
    return db.scalars(select(DepartureTripPreference).order_by(DepartureTripPreference.event_id)).all()


@app.put("/departure/trips/{event_id}", response_model=DepartureTripRead)
def save_departure_trip(event_id: str, payload: DepartureTripUpdate, db: DB):
    if len(event_id) != 32 or any(character not in "0123456789abcdef" for character in event_id):
        raise HTTPException(422, "Invalid calendar event")
    preference = db.get(DepartureTripPreference, event_id)
    if preference is None:
        preference = DepartureTripPreference(event_id=event_id, round_trip=payload.round_trip)
        db.add(preference)
    else:
        preference.round_trip = payload.round_trip
    db.commit()
    db.refresh(preference)
    return preference


def commute_schedule_data(schedule: CommuteSchedule):
    return {
        "id": schedule.id,
        "member_id": schedule.member_id,
        "member_name": schedule.member_name,
        "label": schedule.label,
        "kind": schedule.kind,
        "destination_address": schedule.destination_address,
        "send_time": schedule.send_time,
        "weekdays": [int(value) for value in schedule.weekdays.split(",") if value],
        "use_school_calendar": schedule.use_school_calendar,
        "enabled": schedule.enabled,
        "updated_at": schedule.updated_at,
    }


def save_commute_schedule_values(schedule, payload):
    from sensitive_crypto import encrypt_text

    if payload.use_school_calendar and REGIONAL.school_calendar == "none":
        raise HTTPException(422, "Configure a school calendar provider before enabling school-day filtering")
    schedule.member_id = payload.member_id
    schedule.label = payload.label
    schedule.kind = payload.kind
    schedule.encrypted_destination_address = encrypt_text(payload.destination_address)
    schedule.send_time = payload.send_time
    schedule.weekdays = ",".join(str(value) for value in payload.weekdays)
    schedule.use_school_calendar = payload.use_school_calendar
    schedule.enabled = payload.enabled


@app.get("/commutes", response_model=list[CommuteScheduleRead])
def list_commute_schedules(db: DB):
    return [commute_schedule_data(value) for value in db.scalars(
        select(CommuteSchedule).order_by(CommuteSchedule.send_time, CommuteSchedule.id)
    ).all()]


@app.post("/commutes", response_model=CommuteScheduleRead, status_code=201)
def create_commute_schedule(payload: CommuteScheduleUpdate, db: DB):
    member = db.get(FamilyMember, payload.member_id)
    if member is None:
        raise HTTPException(404, "Family member not found")
    if member.role != "parent":
        raise HTTPException(422, "Commute traffic reports can be assigned only to a parent")
    schedule = CommuteSchedule()
    save_commute_schedule_values(schedule, payload)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return commute_schedule_data(schedule)


@app.put("/commutes/{schedule_id}", response_model=CommuteScheduleRead)
def update_commute_schedule(schedule_id: int, payload: CommuteScheduleUpdate, db: DB):
    schedule = db.get(CommuteSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "Commute schedule not found")
    member = db.get(FamilyMember, payload.member_id)
    if member is None:
        raise HTTPException(404, "Family member not found")
    if member.role != "parent":
        raise HTTPException(422, "Commute traffic reports can be assigned only to a parent")
    save_commute_schedule_values(schedule, payload)
    db.commit()
    db.refresh(schedule)
    return commute_schedule_data(schedule)


@app.delete("/commutes/{schedule_id}", status_code=204)
def delete_commute_schedule(schedule_id: int, db: DB):
    schedule = db.get(CommuteSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "Commute schedule not found")
    db.delete(schedule)
    db.commit()


@app.get("/commutes/school-calendar")
def get_school_calendar_status(refresh: bool = False):
    from calendar_service import LOCAL_ZONE
    from school_calendar_service import school_day_status

    if REGIONAL.school_calendar == "none":
        return {"status": "disabled", "is_school_day": False}
    try:
        return {"status": "ready", **school_day_status(datetime.now(LOCAL_ZONE).date(), refresh)}
    except Exception:
        return {"status": "unavailable", "date": datetime.now(LOCAL_ZONE).date().isoformat(), "is_school_day": False}


@app.post("/commutes/claim", response_model=CommuteClaim | None)
def claim_due_commute(db: DB):
    from calendar_service import LOCAL_ZONE
    from school_calendar_service import school_day_status

    now = datetime.now(LOCAL_ZONE)
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.execute(delete(CommuteRun).where(CommuteRun.status == "claimed", CommuteRun.created_at < stale_before))
    home = db.get(DepartureSettings, 1)
    if home is None or not home.home_address:
        db.commit()
        return None
    school_status = None
    for schedule in db.scalars(select(CommuteSchedule).where(CommuteSchedule.enabled.is_(True)).order_by(CommuteSchedule.send_time, CommuteSchedule.id)).all():
        if now.weekday() not in {int(value) for value in schedule.weekdays.split(",") if value}:
            continue
        if now.strftime("%H:%M") < schedule.send_time:
            continue
        if schedule.use_school_calendar:
            if school_status is None:
                try:
                    school_status = school_day_status(now.date())
                except Exception:
                    school_status = {"is_school_day": False}
            if not school_status["is_school_day"]:
                continue
        existing = db.scalar(select(CommuteRun).where(
            CommuteRun.schedule_id == schedule.id, CommuteRun.run_date == now.date()
        ))
        if existing is not None:
            continue
        contact = db.get(AlertContact, schedule.member_id)
        if contact is None or not contact.enabled:
            continue
        run = CommuteRun(schedule_id=schedule.id, run_date=now.date(), status="claimed")
        db.add(run)
        db.commit()
        db.refresh(run)
        return CommuteClaim(
            run_id=run.id, schedule_id=schedule.id, member_name=schedule.member_name,
            label=schedule.label, kind=schedule.kind, origin_address=home.home_address,
            destination_address=schedule.destination_address, send_time=schedule.send_time,
        )
    db.commit()
    return None


@app.post("/commutes/runs/{run_id}/complete")
def complete_commute_run(run_id: int, payload: CommuteResult, db: DB):
    run = db.get(CommuteRun, run_id)
    if run is None:
        raise HTTPException(404, "Commute check not found")
    if run.status != "claimed":
        raise HTTPException(409, "Commute check is already complete")
    schedule = db.get(CommuteSchedule, run.schedule_id)
    if schedule is None:
        raise HTTPException(404, "Commute schedule not found")
    query = urlencode({"saddr": db.get(DepartureSettings, 1).home_address, "daddr": schedule.destination_address, "dirflg": "d"})
    directions = "https://maps.apple.com/?" + query
    if payload.duration_seconds is not None:
        minutes = max(1, round(payload.duration_seconds / 60))
        distance = f" ({REGIONAL.distance(payload.distance_meters)})" if payload.distance_meters else ""
        message = f"{schedule.label} traffic for {schedule.member_name}: about {minutes} min{distance} with current traffic. Directions: {directions}"
        run.status = "completed"
    else:
        message = f"{schedule.label} traffic could not be calculated right now. Open live directions: {directions}"
        run.status = "failed"
    alert = Alert(member_id=schedule.member_id, message=message[:500], scheduled_for=datetime.now(timezone.utc))
    db.add(alert)
    db.flush()
    run.duration_seconds = payload.duration_seconds
    run.distance_meters = payload.distance_meters
    run.alert_id = alert.id
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": run.status, "alert_id": alert.id}


def suggested_weather_location(db: Session) -> str:
    settings = db.get(DepartureSettings, 1)
    if settings is None or not settings.home_address:
        return ""
    parts = [part.strip() for part in settings.home_address.split(",") if part.strip()]
    return ", ".join(parts[-2:]) if len(parts) >= 2 else parts[0]


@app.get("/weather/settings", response_model=WeatherSettingsRead)
def get_weather_settings(db: DB):
    settings = db.get(WeatherSettings, 1)
    if settings is None:
        return WeatherSettingsRead(configured=False, suggested_location=suggested_weather_location(db))
    return WeatherSettingsRead.model_validate(settings)


@app.put("/weather/settings", response_model=WeatherSettingsRead)
def save_weather_settings(payload: WeatherSettingsUpdate, db: DB):
    from weather_service import geocode_location

    try:
        location = geocode_location(payload.location)
    except ValueError:
        raise HTTPException(422, "Location not found. Try a city, state, or ZIP code.")
    except Exception:
        raise HTTPException(502, "The weather location service is unavailable. Try again shortly.")
    values = {
        **location,
        "rain_probability_percent": payload.rain_probability_percent,
        "jacket_below_fahrenheit": payload.jacket_below_fahrenheit,
        "dress_light_above_fahrenheit": payload.dress_light_above_fahrenheit,
    }
    settings = db.get(WeatherSettings, 1)
    if settings is None:
        settings = WeatherSettings(id=1, **values)
        db.add(settings)
    else:
        for key, value in values.items():
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings


@app.get("/weather/forecast")
def get_weather_forecast(db: DB):
    from weather_service import weather_forecast

    settings = db.get(WeatherSettings, 1)
    if settings is None:
        raise HTTPException(409, "Save a weather location first")
    try:
        return weather_forecast(settings)
    except Exception:
        raise HTTPException(502, "The weather forecast is unavailable. Try again shortly.")


@app.get("/alerts/contacts", response_model=list[AlertContactRead])
def list_alert_contacts(db: DB):
    return db.scalars(select(AlertContact).order_by(AlertContact.member_id)).all()


@app.put("/alerts/contacts")
def save_alert_contacts(payload: AlertContactsBulkUpdate, db: DB):
    from sensitive_crypto import encrypt_text

    member_ids = [item.member_id for item in payload.contacts]
    if len(member_ids) != len(set(member_ids)):
        raise HTTPException(422, "Each family member can appear only once")
    existing_members = set(db.scalars(
        select(FamilyMember.id).where(FamilyMember.id.in_(member_ids))
    ).all())
    if existing_members != set(member_ids):
        raise HTTPException(404, "One or more family members were not found")
    contacts = {contact.member_id: contact for contact in db.scalars(
        select(AlertContact).where(AlertContact.member_id.in_(member_ids))
    ).all()}
    for item in payload.contacts:
        contact = contacts.get(item.member_id)
        if item.imessage_handle is None:
            if contact is not None:
                db.delete(contact)
        elif contact is None:
            db.add(AlertContact(
                member_id=item.member_id,
                encrypted_imessage_handle=encrypt_text(item.imessage_handle),
                enabled=item.enabled,
            ))
        else:
            contact.encrypted_imessage_handle = encrypt_text(item.imessage_handle)
            contact.enabled = item.enabled
    db.commit()
    return {"status": "saved", "contacts": len(payload.contacts)}


@app.put("/alerts/contacts/{member_id}", response_model=AlertContactRead)
def save_alert_contact(member_id: int, payload: AlertContactUpdate, db: DB):
    from sensitive_crypto import encrypt_text

    if db.get(FamilyMember, member_id) is None:
        raise HTTPException(404, "Family member not found")
    contact = db.get(AlertContact, member_id)
    if contact is None:
        contact = AlertContact(
            member_id=member_id,
            encrypted_imessage_handle=encrypt_text(payload.imessage_handle),
            enabled=payload.enabled,
        )
        db.add(contact)
    else:
        contact.encrypted_imessage_handle = encrypt_text(payload.imessage_handle)
        contact.enabled = payload.enabled
    db.commit()
    db.refresh(contact)
    return contact


@app.post("/alerts", response_model=AlertRead, status_code=201)
def create_alert(payload: AlertCreate, db: DB):
    member = db.get(FamilyMember, payload.member_id)
    if member is None:
        raise HTTPException(404, "Family member not found")
    contact = db.get(AlertContact, payload.member_id)
    if contact is None or not contact.enabled:
        raise HTTPException(409, "Add and enable this family member's iMessage contact first")
    alert = Alert(**payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@app.get("/alerts", response_model=list[AlertRead])
def list_alerts(db: DB, limit: int = Query(100, ge=1, le=500)):
    return db.scalars(select(Alert).order_by(Alert.scheduled_for.desc()).limit(limit)).all()


@app.get("/alerts/calendar-rule", response_model=CalendarAlertRuleRead)
def get_calendar_alert_rule(db: DB):
    rule = db.get(CalendarAlertRule, 1)
    if rule is None:
        return CalendarAlertRuleRead(
            configured=False,
            member_id=None,
            enabled=False,
            appointment_reminder_minutes=30,
            leave_reminder_minutes=60,
        )
    return rule


@app.put("/alerts/calendar-rule", response_model=CalendarAlertRuleRead)
def save_calendar_alert_rule(payload: CalendarAlertRuleUpdate, db: DB):
    if db.get(FamilyMember, payload.member_id) is None:
        raise HTTPException(404, "Family member not found")
    contact = db.get(AlertContact, payload.member_id)
    if contact is None or not contact.enabled:
        raise HTTPException(409, "Add and enable this family member's iMessage contact first")
    rule = db.get(CalendarAlertRule, 1)
    if rule is None:
        rule = CalendarAlertRule(id=1, **payload.model_dump())
        db.add(rule)
    else:
        for key, value in payload.model_dump().items():
            setattr(rule, key, value)
    rule.last_synced_at = None
    db.commit()
    db.refresh(rule)
    return rule


def calendar_alert_message(event, kind, event_start, zone):
    title = event.title[:160]
    local_time = event_start.astimezone(zone).strftime("%a, %b %d at %-I:%M %p")
    if kind == "leave":
        return f"Time to leave for {title}. It starts {local_time}. Open Family Agent for directions."
    location = event.location[:160] if event.location else "No location is listed"
    return f"Reminder: {title} starts {local_time}. {location}."


def calendar_reminders_for_event(event, rule):
    reminders = [("appointment", rule.appointment_reminder_minutes)]
    if event.departure_ready:
        reminders.insert(0, ("leave", rule.leave_reminder_minutes))
    return reminders


@app.post("/alerts/calendar/sync")
def sync_calendar_alerts(db: DB):
    from calendar_archive import maintain
    from calendar_service import upcoming_events, LOCAL_ZONE
    archive_data=upcoming_events()
    maintain(archive_data['events'],archive_data['conflict_check_complete'],LOCAL_ZONE)
    rule = db.get(CalendarAlertRule, 1)
    now = datetime.now(timezone.utc)
    if rule is None or not rule.enabled:
        return {"status": "disabled", "created": 0, "updated": 0}
    if rule.last_synced_at and now - rule.last_synced_at < timedelta(minutes=10):
        return {"status": "recently_synced", "created": 0, "updated": 0}
    contact = db.get(AlertContact, rule.member_id)
    if contact is None or not contact.enabled:
        return {"status": "contact_unavailable", "created": 0, "updated": 0}

    from calendar_service import LOCAL_ZONE, upcoming_events

    calendar_data = upcoming_events()
    active_keys = set()
    created = updated = 0
    for event in calendar_data["events"]:
        if event.all_day or not event.busy:
            continue
        event_start = datetime.fromisoformat(event.start.replace("Z", "+00:00"))
        if event_start <= now:
            continue
        for kind, minutes_before in calendar_reminders_for_event(event, rule):
            # Route-based departure checks replace fixed "Time to leave" messages.
            settings = db.get(DepartureSettings, 1)
            if kind == 'leave' and settings and settings.home_address:
                continue
            scheduled_for = event_start - timedelta(minutes=minutes_before)
            if kind == "appointment" and scheduled_for < now:
                continue
            if scheduled_for < now:
                scheduled_for = now
            key = f"{event.id}:{kind}"
            active_keys.add(key)
            message = calendar_alert_message(event, kind, event_start, LOCAL_ZONE)
            marker = db.get(CalendarAlertMarker, key)
            if marker is not None:
                alert = db.get(Alert, marker.alert_id)
                if alert is not None and alert.status == "pending":
                    alert.member_id = rule.member_id
                    alert.message = message
                    alert.scheduled_for = scheduled_for
                    updated += 1
                continue
            alert = Alert(
                member_id=rule.member_id,
                message=message,
                scheduled_for=scheduled_for,
            )
            db.add(alert)
            db.flush()
            db.add(CalendarAlertMarker(
                key=key, event_id=event.id, kind=kind, alert_id=alert.id,
            ))
            created += 1

    if calendar_data["conflict_check_complete"]:
        for marker in db.scalars(select(CalendarAlertMarker)).all():
            if marker.key in active_keys:
                continue
            alert = db.get(Alert, marker.alert_id)
            if alert is not None and alert.status != 'pending':
                continue  # Retain the minimal occurrence marker to prevent repeat delivery.
            db.delete(marker)
            db.flush()
            if alert is not None and alert.status == "pending":
                db.delete(alert)
    rule.last_synced_at = now
    db.commit()
    return {"status": "synced", "created": created, "updated": updated}


@app.get("/alerts/morning")
def get_morning_briefing(db: DB):
    from calendar_service import LOCAL_ZONE, available_calendars

    settings = db.get(MorningBriefingSettings, 1)
    preferences = {row.member_id: row for row in db.scalars(select(MorningBriefingPreference)).all()}
    assignments = {}
    for row in db.scalars(select(CalendarAssignment)).all():
        assignments.setdefault(row.member_id, []).append(row.calendar_key)
    contacts = {row.member_id: row for row in db.scalars(select(AlertContact)).all()}
    recipients = []
    for member in db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all():
        preference = preferences.get(member.id)
        recipients.append({
            "member_id": member.id,
            "member_name": member.name,
            "enabled": preference.enabled if preference else False,
            "include_family_schedule": (
                preference.include_family_schedule if preference
                else member.role == "parent"
            ),
            "calendar_keys": assignments.get(member.id, []),
            "contact_ready": bool(contacts.get(member.id) and contacts[member.id].enabled),
        })
    return {
        "configured": settings is not None,
        "enabled": settings.enabled if settings else False,
        "send_time": settings.send_time if settings else "07:00",
        "timezone": str(LOCAL_ZONE),
        "calendars": available_calendars(),
        "recipients": recipients,
    }


@app.put("/alerts/morning")
def save_morning_briefing(payload: MorningBriefingUpdate, db: DB):
    from calendar_service import available_calendars

    valid_members = set(db.scalars(select(FamilyMember.id)).all())
    valid_calendars = {row["key"] for row in available_calendars()}
    for recipient in payload.recipients:
        if recipient.member_id not in valid_members:
            raise HTTPException(404, "Family member not found")
        if not set(recipient.calendar_keys).issubset(valid_calendars):
            raise HTTPException(422, "Refresh and choose from the available calendars")
    settings = db.get(MorningBriefingSettings, 1)
    if settings is None:
        settings = MorningBriefingSettings(id=1)
        db.add(settings)
    settings.enabled = payload.enabled
    settings.send_time = payload.send_time
    for recipient in payload.recipients:
        preference = db.get(MorningBriefingPreference, recipient.member_id)
        if preference is None:
            preference = MorningBriefingPreference(member_id=recipient.member_id)
            db.add(preference)
        preference.enabled = recipient.enabled
        preference.include_family_schedule = recipient.include_family_schedule
        existing_assignments = db.scalars(
            select(CalendarAssignment).where(CalendarAssignment.member_id == recipient.member_id)
        ).all()
        desired_keys = set(recipient.calendar_keys)
        existing_keys = {assignment.calendar_key for assignment in existing_assignments}
        for assignment in existing_assignments:
            if assignment.calendar_key not in desired_keys:
                db.delete(assignment)
        for key in desired_keys - existing_keys:
            db.add(CalendarAssignment(calendar_key=key, member_id=recipient.member_id))
    db.commit()
    return get_morning_briefing(db)


@app.post("/alerts/morning/sync")
def sync_morning_briefings(db: DB):
    from briefing_service import build_briefing, delivery_state, event_is_today
    from calendar_service import LOCAL_ZONE, upcoming_events
    from weather_service import weather_forecast

    settings = db.get(MorningBriefingSettings, 1)
    if settings is None or not settings.enabled:
        return {"status": "disabled", "created": 0}
    local_now = datetime.now(LOCAL_ZONE)
    run = db.get(MorningBriefingRun, local_now.date())
    if run is None:
        run = MorningBriefingRun(
            briefing_date=local_now.date(), status="scheduled", attempts=0,
            last_checked_at=datetime.now(timezone.utc),
        )
        db.add(run)
    tomorrow = local_now.date() + timedelta(days=1)
    if db.get(MorningBriefingRun, tomorrow) is None:
        db.add(MorningBriefingRun(
            briefing_date=tomorrow, status="scheduled", attempts=0,
            last_checked_at=datetime.now(timezone.utc),
        ))
    state = delivery_state(local_now, settings.send_time)
    if state != "ready":
        db.commit()
        return {"status": state, "created": 0}
    preferences = db.scalars(
        select(MorningBriefingPreference).where(MorningBriefingPreference.enabled.is_(True))
    ).all()
    run.attempts += 1
    run.last_checked_at = datetime.now(timezone.utc)
    eligible = []
    for preference in preferences:
        key = f"{local_now.date().isoformat()}:{preference.member_id}"
        contact = db.get(AlertContact, preference.member_id)
        if db.get(MorningBriefingMarker, key) is None and contact is not None and contact.enabled:
            eligible.append((preference, key))
    if not eligible:
        marker_count = sum(
            db.get(MorningBriefingMarker, f"{local_now.date().isoformat()}:{preference.member_id}") is not None
            for preference in preferences
        )
        run.status = "complete" if preferences and marker_count == len(preferences) else "no_contacts"
        db.commit()
        return {"status": "already_sent_or_no_contacts", "created": 0}

    calendar_data = upcoming_events()
    if any(source["status"] == "error" for source in calendar_data["sources"]):
        run.status = "waiting_for_calendar"
        db.commit()
        return {"status": "waiting_for_calendar", "created": 0}
    today_events = [event for event in calendar_data["events"] if event_is_today(event, local_now.date(), LOCAL_ZONE)]
    weather_settings = db.get(WeatherSettings, 1)
    try:
        forecast = weather_forecast(weather_settings) if weather_settings else {}
    except Exception:
        forecast = {}
    if weather_settings is not None and not forecast:
        run.status = "waiting_for_weather"
        db.commit()
        return {"status": "waiting_for_weather", "created": 0}
    all_tasks = db.scalars(select(Task).where(Task.status != "completed", Task.due_at.is_not(None))).all()
    assignments = {}
    for row in db.scalars(select(CalendarAssignment)).all():
        assignments.setdefault(row.member_id, set()).add(row.calendar_key)

    created = 0
    for preference, key in eligible:
        member = db.get(FamilyMember, preference.member_id)
        member_keys = assignments.get(preference.member_id, set())
        events = today_events if preference.include_family_schedule else [
            event for event in today_events if event.calendar_key in member_keys
        ]
        tasks = [task for task in all_tasks if task.assigned_to == preference.member_id and task.due_at.astimezone(LOCAL_ZONE).date() == local_now.date()]
        message = build_briefing(
            member.id, member.name, events, tasks, forecast, preference.include_family_schedule,
            local_now.date(), LOCAL_ZONE,
        )
        alert = Alert(member_id=member.id, message=message, scheduled_for=datetime.now(timezone.utc))
        db.add(alert)
        db.flush()
        db.add(MorningBriefingMarker(key=key, alert_id=alert.id))
        created += 1
    run.status = "queued"
    db.commit()
    return {"status": "synced", "created": created}


@app.get("/alerts/morning/ledger")
def morning_briefing_ledger(db: DB, days: int = Query(7, ge=1, le=31)):
    from calendar_service import LOCAL_ZONE

    settings = db.get(MorningBriefingSettings, 1)
    local_now = datetime.now(LOCAL_ZONE)
    preferences = db.scalars(
        select(MorningBriefingPreference).where(MorningBriefingPreference.enabled.is_(True))
    ).all()
    members = {member.id: member for member in db.scalars(select(FamilyMember)).all()}
    contacts = {contact.member_id: contact for contact in db.scalars(select(AlertContact)).all()}
    rows = []
    for offset in range(days):
        day = local_now.date() - timedelta(days=offset)
        run = db.get(MorningBriefingRun, day)
        deliveries = []
        for preference in preferences:
            marker = db.get(MorningBriefingMarker, f"{day.isoformat()}:{preference.member_id}")
            alert = db.get(Alert, marker.alert_id) if marker else None
            if alert is not None:
                status = "retrying" if alert.status == "pending" and alert.attempt_count else alert.status
                if status == "sending":
                    status = "queued"
            elif day < local_now.date():
                status = "missed" if run is not None else "not_recorded"
            elif settings is None or not settings.enabled:
                status = "disabled"
            elif preference.member_id not in contacts or not contacts[preference.member_id].enabled:
                status = "no_contact"
            else:
                hour, minute = (int(part) for part in settings.send_time.split(":"))
                scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if local_now < scheduled:
                    status = "scheduled"
                elif run and run.status in {"waiting_for_calendar", "waiting_for_weather"}:
                    status = run.status
                else:
                    status = "waiting_for_mac"
            deliveries.append({
                "member_id": preference.member_id,
                "member_name": members[preference.member_id].name,
                "status": status,
                "attempt_count": alert.attempt_count if alert else 0,
                "sent_at": alert.sent_at if alert else None,
            })
        statuses = {delivery["status"] for delivery in deliveries}
        summary = "sent" if deliveries and statuses == {"sent"} else (
            "missed" if deliveries and statuses == {"missed"} else
            "not_recorded" if deliveries and statuses == {"not_recorded"} else
            "attention_needed" if statuses & {"failed", "uncertain", "missed", "no_contact"} else
            "in_progress" if deliveries else "not_configured"
        )
        rows.append({
            "date": day.isoformat(),
            "summary": summary,
            "last_checked_at": run.last_checked_at if run else None,
            "check_attempts": run.attempts if run else 0,
            "deliveries": deliveries,
        })
    return {"timezone": str(LOCAL_ZONE), "days": rows}


def weekend_schedule_preview(db: Session, refresh: bool = True):
    from briefing_service import build_weekend_schedule, event_local_date, next_weekend_range
    from calendar_service import LOCAL_ZONE, upcoming_events

    local_today = datetime.now(LOCAL_ZONE).date()
    saturday, sunday = next_weekend_range(local_today)
    calendar_data = upcoming_events(refresh=refresh)
    weekend_events = [
        event for event in calendar_data["events"]
        if saturday <= event_local_date(event, LOCAL_ZONE) <= sunday
    ]
    contacts = {row.member_id: row for row in db.scalars(select(AlertContact)).all()}
    recipients = []
    unavailable = []
    for member in db.scalars(select(FamilyMember).order_by(FamilyMember.id)).all():
        contact = contacts.get(member.id)
        if contact is None or not contact.enabled or not contact.imessage_handle:
            unavailable.append(member.name)
            continue
        recipients.append({
            "member_id": member.id,
            "member_name": member.name,
            "message": build_weekend_schedule(
                member.name, weekend_events, saturday, sunday, LOCAL_ZONE,
            ),
        })
    calendar_connected = any(source["status"] == "connected" for source in calendar_data["sources"])
    refresh_complete = calendar_connected and all(
        source["status"] != "error" for source in calendar_data["sources"]
    )
    return {
        "weekend_start": saturday.isoformat(),
        "weekend_end": sunday.isoformat(),
        "timezone": str(LOCAL_ZONE),
        "event_count": len(weekend_events),
        "recipients": recipients,
        "unavailable_members": unavailable,
        "calendar_connected": calendar_connected,
        "calendar_refresh_complete": refresh_complete,
    }


@app.get("/alerts/weekend/preview")
def preview_weekend_schedule(db: DB):
    return weekend_schedule_preview(db)


@app.post("/alerts/weekend/send")
def send_weekend_schedule(db: DB):
    preview = weekend_schedule_preview(db)
    if not preview["calendar_refresh_complete"]:
        raise HTTPException(503, "Calendar refresh is incomplete. Preview again before sending.")
    if not preview["recipients"]:
        raise HTTPException(422, "No enabled family iMessage contacts are ready")
    scheduled_for = datetime.now(timezone.utc)
    for recipient in preview["recipients"]:
        db.add(Alert(
            member_id=recipient["member_id"],
            message=recipient["message"],
            scheduled_for=scheduled_for,
        ))
    db.commit()
    return {
        "status": "queued",
        "created": len(preview["recipients"]),
        "weekend_start": preview["weekend_start"],
        "weekend_end": preview["weekend_end"],
    }


def verify_messaging_token(authorization):
    import hmac
    from messaging_settings import load_settings
    config = load_settings()
    if config['provider'] == 'imessage' or not hmac.compare_digest(
        (authorization or '').encode(), ('Bearer ' + config['bridge_token']).encode()
    ):
        raise HTTPException(403, 'Messaging authentication failed')
    return config


@app.post('/messaging/inbox')
def receive_remote_message(payload: ConciergeInboxRequest, db: DB, authorization: Annotated[str | None, Header()] = None):
    from messaging_settings import allowed_number
    config = verify_messaging_token(authorization)
    if not allowed_number(config, payload.sender_handle):
        return {'status': 'ignored'}
    if not payload.message_guid.startswith(config['provider'] + ':'):
        raise HTTPException(400, 'Invalid message namespace')
    return receive_concierge_imessage(payload, db)


@app.post("/alerts/claim", response_model=AlertClaim | None)
def claim_due_alert(db: DB, provider: str = 'imessage', authorization: Annotated[str | None, Header()] = None):
    from messaging_settings import provider as selected_provider
    if provider != selected_provider():
        raise HTTPException(409, 'This worker does not match the configured messaging provider')
    if provider != 'imessage':
        verify_messaging_token(authorization)
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=2)
    for abandoned in db.scalars(select(Alert).where(
        Alert.status == "sending",
        or_(Alert.last_attempt_at.is_(None), Alert.last_attempt_at < stale_before),
    )).all():
        # The worker may have handed this message to Messages before crashing.
        # Mark it uncertain instead of retrying and risking a duplicate.
        abandoned.status = "uncertain"
    db.commit()
    alert = db.scalar(
        select(Alert)
        .where(Alert.status == "pending", Alert.scheduled_for <= datetime.now(timezone.utc))
        .order_by(Alert.scheduled_for, Alert.id)
        .with_for_update(skip_locked=True, of=Alert)
        .limit(1)
    )
    if alert is None:
        return None
    contact = db.get(AlertContact, alert.member_id)
    if contact is None or not contact.enabled:
        alert.status = "failed"
        db.commit()
        return None
    alert.status = "sending"
    alert.attempt_count += 1
    alert.last_attempt_at = datetime.now(timezone.utc)
    db.commit()
    return AlertClaim(
        id=alert.id,
        member_name=alert.member_name,
        imessage_handle=contact.imessage_handle,
        message=alert.message,
        scheduled_for=alert.scheduled_for,
    )


def finish_alert(alert_id: int, status: str, db: Session):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    if alert.status != "sending":
        raise HTTPException(409, "Alert is not waiting for delivery")
    if status == "failed" and alert.attempt_count < 3:
        alert.status = "pending"
        alert.scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=5)
        alert.sent_at = None
    else:
        alert.status = status
        alert.sent_at = datetime.now(timezone.utc) if status == "sent" else None
    db.commit()
    db.refresh(alert)
    return alert


@app.post("/alerts/{alert_id}/sent", response_model=AlertRead)
def mark_alert_sent(alert_id: int, db: DB):
    return finish_alert(alert_id, "sent", db)


@app.post("/alerts/{alert_id}/failed", response_model=AlertRead)
def mark_alert_failed(alert_id: int, db: DB):
    return finish_alert(alert_id, "failed", db)


@app.post("/alerts/{alert_id}/uncertain", response_model=AlertRead)
def mark_alert_uncertain(alert_id: int, db: DB):
    return finish_alert(alert_id, "uncertain", db)


# Serve the local dashboard with the same API container and origin.
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(static_dir / "index.html")

from calendar_service import router as calendar_router
app.include_router(calendar_router)

@app.get('/concierge/activity-alerts', response_model=list[AlertRead])
def activity_alerts(db: DB, task_id: int | None = None, event_id: str | None = None):
    if (task_id is None)==(event_id is None):
        raise HTTPException(422,'Choose one task or appointment')
    query=select(Alert)
    if task_id is not None: query=query.where(Alert.task_id==task_id)
    else: query=query.join(CalendarAlertMarker,CalendarAlertMarker.alert_id==Alert.id).where(CalendarAlertMarker.event_id==event_id)
    return db.scalars(query.order_by(Alert.created_at.desc()).limit(100)).all()
