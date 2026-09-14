"""Template-driven clarification. Stored drafts remain unexecuted until reviewed."""
from copy import deepcopy
from datetime import date
import re

from concierge_llm import REQUEST_TEMPLATE
from concierge_workflow import preview_request, prepare_preview, extract_details


def finish(plan):
    if plan.get('request_type') in ('events', 'acknowledgment', 'schedule_query'):
        return plan
    plan.update(prepare_preview(plan))
    missing = plan['missing_fields']
    plan['dialog_state'] = 'awaiting_details' if missing else 'ready_for_review'
    if missing:
        field = missing[0]
        plan['question_field'] = field
        plan['reply_text'] = REQUEST_TEMPLATE['questions'].get(field, f'Please provide {field}.')
    else:
        plan['question_field'] = None
        when = ' '.join(value for value in (plan.get('date'), plan.get('time')) if value)
        plan['reply_text'] = (
            f"Got it — {plan.get('title') or 'Your request'} for {plan.get('primary_member') or 'the family'}"
            + (f" on {when}" if when else '')
            + '. All required details are captured. The draft is ready for review; nothing has been booked or sent.'
        )
    return plan


def merge_answer(previous, answer, candidate, names, profiles, now, requester):
    """Merge a parsed answer without calling the model or executing an action."""
    plan = deepcopy(previous)
    question = plan.get('question_field')
    for field in ('date', 'time'):
        if candidate.get(field) is not None:
            plan[field] = candidate[field]
    if question == 'family member' and candidate.get('primary_member'):
        plan['primary_member'] = candidate['primary_member']
    # Explicit 24-hour answers and ISO dates work even when the model is offline.
    if question == 'time' and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', answer.strip()):
        plan['time'] = answer.strip()
    if plan.get('date'):
        try:
            date.fromisoformat(plan['date'])
        except ValueError:
            plan['date'] = None
    if question == 'whether this should be a task or calendar event':
        kind = candidate.get('request_type')
        if re.fullmatch(r'(?:a )?calendar(?: event)?', answer.strip(), re.I): kind = 'calendar'
        if re.fullmatch(r'(?:a )?task', answer.strip(), re.I): kind = 'task'
        if kind in ('calendar', 'task'): plan['request_type'] = kind
    if question == 'title':
        plan['title'] = answer.strip()[:200]
    if candidate.get('calendar_events') and question in ('time', 'title'):
        plan['calendar_events'] = candidate['calendar_events']
        plan['time'] = candidate['calendar_events'][0]['start_time']
    if re.search(r'\bnotify\b', answer, re.I):
        plan['notification_members'] = candidate.get('notification_members', [])
    if re.search(r'\b(?:every|weekly|each)\b', answer, re.I):
        plan['repeat_interval'] = candidate.get('repeat_interval', 'none')
    driver = plan.get('driver')
    pickup = plan.get('pickup_by')
    mode = plan.get('transportation_mode')
    if question == 'which parent will drive':
        driver = next((p['name'] for p in profiles if p.get('role') == 'parent' and re.search(rf"\b{re.escape(p['name'])}\b", answer, re.I)), driver)
    if question == 'who will pick up':
        pickup = next((p for p in plan.get('pickup_options', []) if re.search(rf'\b{re.escape(p)}\b', answer, re.I)), pickup)
    if re.search(r'\b(?:no transportation|transportation not needed|no driving|online|virtual)\b', answer, re.I):
        mode = 'none'
    if re.search(r'\b(?:pickup only|already at school)\b', answer, re.I): mode = 'pickup_only'
    # Compute safety requirements from the selected member's saved profile, not model guesses.
    text = f"{plan.get('primary_member') or ''} {plan.get('title') or ''}. {answer}"
    details = extract_details({'normalized_text':text, 'now':now.isoformat(), 'member_names':names,
        'family_profiles':profiles, 'request_type':plan['request_type'],
        'requested_driver':driver, 'requested_pickup_by':pickup, 'requested_transportation_mode':mode,
        'llm_plan':{'primary_member':plan.get('primary_member')}, 'requester_name':requester})
    for key in ('subject_role','subject_age','requires_parent_driver','driver','driver_options',
                'transportation_mode','requires_pickup','pickup_by','pickup_options'):
        plan[key] = details[key]
    plan['llm_used'] = bool(plan.get('llm_used') or candidate.get('llm_used'))
    return plan


def advance(previous, answer, names, profiles, now, requester):
    from concierge_chain import run_request
    return run_request(answer, names, now, profiles, requester_name=requester, previous=previous)


def reply_message(item_id, plan):
    prefix = f'Family Agent request #{item_id}: '
    suffix = f' Reply FA #{item_id} followed by your answer.' if plan['dialog_state'] == 'awaiting_details' else ''
    return prefix + plan['reply_text'][:500-len(prefix)-len(suffix)] + suffix
