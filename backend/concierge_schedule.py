"""Read-only day schedule requests; never create an appointment from a query."""
from datetime import datetime, time, timedelta
import re
from sqlalchemy import select
from database import SessionLocal
from models import FamilyMember, CalendarAssignment
from calendar_service import LOCAL_ZONE, upcoming_events


def is_schedule_query(text):
    return bool(re.search(r'\b(?:provide|show|list|what|check|view|give)\b', text, re.I)
                and re.search(r'\b(?:activity|activities|calendar|schedule|appointments)\b', text, re.I)
                and not re.search(r'\b(?:create|book|add|cancel|delete|reschedule)\b', text, re.I))


def scope_for(requester):
    # The local dashboard already exposes the household calendar. Messages have a verified sender.
    if not requester: return None
    with SessionLocal() as db:
        member = db.scalar(select(FamilyMember).where(FamilyMember.name == requester))
        if not member: return set()
        if member.role == 'parent': return None
        return set(db.scalars(select(CalendarAssignment.calendar_key).where(CalendarAssignment.member_id == member.id)))


def overlaps_day(event, day):
    if event.all_day:
        return event.start[:10] <= day.isoformat() < event.end[:10]
    start = datetime.fromisoformat(event.start.replace('Z', '+00:00')).astimezone(LOCAL_ZONE)
    end = datetime.fromisoformat(event.end.replace('Z', '+00:00')).astimezone(LOCAL_ZONE)
    boundary = datetime.combine(day, time.min, LOCAL_ZONE)
    return start < boundary + timedelta(days=1) and end > boundary


def schedule_plan(text, now, requester=None):
    day = now.astimezone(LOCAL_ZONE).date() if now.tzinfo else now.date()
    plan = dict(request_type='schedule_query', title='View calendar schedule', missing_fields=[],
                notification_members=[], proposed_actions=[], dialog_state='ready_for_review', question_field=None,
                workflow_version=1, workflow_steps=['recognize_schedule_query','read_calendar','reply_with_schedule'],
                llm_used=False, interpreter_this_turn='local_fallback', schedule_events=[])
    if re.search(r'\btomorrow\b', text, re.I): day += timedelta(days=1)
    elif not re.search(r'\btoday\b', text, re.I):
        plan.update(missing_fields=['schedule day'], question_field='schedule day', dialog_state='awaiting_details', reply_text='Would you like today’s or tomorrow’s calendar?')
        return plan
    keys = scope_for(requester)
    if keys == set():
        plan['reply_text'] = 'No calendars are assigned to your profile yet. Ask a parent to configure calendar assignments.'
        return plan
    data = upcoming_events(refresh=True)
    events = [e for e in data['events'] if overlaps_day(e, day) and (keys is None or e.calendar_key in keys)]
    events.sort(key=lambda e: e.start)
    summaries = []
    for e in events:
        stamp = 'All day' if e.all_day else datetime.fromisoformat(e.start.replace('Z','+00:00')).astimezone(LOCAL_ZONE).strftime('%-I:%M %p')
        summaries.append(f'{stamp}: {e.title[:90]}')
    partial = not data.get('conflict_check_complete', False)
    header = f'Calendar for {day.strftime("%a, %b %-d")} ({len(events)} activities).'
    warning = ' Calendar sources are incomplete; this may miss activities.' if partial else ''
    body = ''; shown = 0
    for summary in summaries:
        if len(header + warning + body + summary) > 320: break
        body += '\n' + summary; shown += 1
    if not events: body = '\nNo activities found in the connected calendars.'
    if shown < len(events): body += f'\n+{len(events)-shown} more; open Calendar in the dashboard.'
    plan.update(date=day.isoformat(), reply_text=header + warning + body, schedule_events=[e.model_dump() for e in events])
    return plan
