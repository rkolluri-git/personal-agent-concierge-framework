"""One resumable request chain for previews and incoming conversations.

The encrypted inbox plan is the durable state between turns. This graph is pure:
only the API's existing transaction persists the result and queues a reply.
"""
from copy import deepcopy
from datetime import datetime
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from concierge_workflow import preview_request, prepare_preview
from concierge_dialog import merge_answer, finish


class RequestState(TypedDict, total=False):
    text: str
    names: list[str]
    profiles: list[dict]
    now: datetime
    requester: str | None
    driver: str | None
    transportation_mode: str | None
    pickup: str | None
    combine: bool
    previous: dict | None
    candidate: dict
    plan: dict
    steps: list[str]


def interpret_turn(state):
    previous = state.get('previous') or {}
    context = {key: previous.get(key) for key in (
        'request_type', 'title', 'primary_member', 'date', 'time',
        'notification_members', 'question_field',
    )} if previous else None
    candidate = preview_request(
        state['text'], state['names'], state['now'], state['profiles'],
        state.get('driver'), state.get('requester'), state.get('transportation_mode'),
        state.get('pickup'), state.get('combine', False), dialog_context=context,
    )
    return {'candidate': candidate, 'steps': [
        'llm_interpret' if candidate.get('llm_used') else 'local_fallback',
        'classify', 'extract',
    ]}


def merge_turn(state):
    previous = state.get('previous')
    plan = merge_answer(previous, state['text'], state['candidate'], state['names'],
        state['profiles'], state['now'], state.get('requester')) if previous else deepcopy(state['candidate'])
    return {'plan': plan, 'steps': [*state['steps'], 'merge_confirmed_details']}


def validate_turn(state):
    plan = deepcopy(state['plan'])
    plan.update(prepare_preview(plan))
    return {'plan': plan, 'steps': [*state['steps'], 'validate_required_details']}


def response(state, step):
    plan = finish(deepcopy(state['plan']))
    plan['workflow_version'] = 1
    plan['workflow_steps'] = [*state['steps'], step]
    # Distinguish a model used on an earlier turn from one available right now.
    plan['interpreter_this_turn'] = 'llm' if state['candidate'].get('llm_used') else 'local_fallback'
    return {'plan': plan}


def ask_for_details(state):
    return response(state, 'ask_for_details')


def acknowledge_draft(state):
    return response(state, 'acknowledge_ready_for_review')


builder = StateGraph(RequestState)
builder.add_node('interpret', interpret_turn)
builder.add_node('merge', merge_turn)
builder.add_node('validate', validate_turn)
builder.add_node('ask', ask_for_details)
builder.add_node('acknowledge', acknowledge_draft)
from concierge_events import is_events_search, search_plan
builder.add_node('events', lambda state: {'plan': search_plan(state['text'], state['now'])})
from concierge_ack import is_ack_test, ack_plan
builder.add_node('receipt', lambda state: {'plan': ack_plan()})
from concierge_schedule import is_schedule_query, schedule_plan
builder.add_node('schedule', lambda state: {'plan': schedule_plan(state['text'], state['now'], state.get('requester'))})
builder.add_edge('schedule', END)
def route_request(state):
    if is_schedule_query(state['text']) or (state.get('previous') or {}).get('request_type') == 'schedule_query': return 'schedule'
    if state.get('previous'): return 'interpret'
    if is_ack_test(state['text']): return 'receipt'
    return 'events' if is_events_search(state['text']) else 'interpret'
builder.add_conditional_edges(START, route_request, {'schedule': 'schedule', 'receipt': 'receipt', 'events': 'events', 'interpret': 'interpret'})
builder.add_edge('receipt', END)
builder.add_edge('events', END)
builder.add_edge('interpret', 'merge')
builder.add_edge('merge', 'validate')
builder.add_conditional_edges('validate', lambda state: 'ask' if state['plan']['missing_fields'] else 'acknowledge',
                              {'ask': 'ask', 'acknowledge': 'acknowledge'})
builder.add_edge('ask', END)
builder.add_edge('acknowledge', END)
request_chain = builder.compile()


def run_request(text, member_names, now, family_profiles=None, driver_name=None,
                requester_name=None, transportation_mode=None, pickup_by=None,
                combine_adjacent_events=False, *, previous=None):
    result = request_chain.invoke({
        'text': text, 'names': member_names, 'now': now, 'profiles': family_profiles or [],
        'requester': requester_name, 'driver': driver_name, 'transportation_mode': transportation_mode,
        'pickup': pickup_by, 'combine': combine_adjacent_events, 'previous': deepcopy(previous),
    })
    return result['plan']
