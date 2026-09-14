"""Local-first LangGraph workflow for previewing family requests."""
import re
from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


TIME_RANGE = re.compile(
    r"(?<![\d/-])(?:(?:from|at)\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*"
    r"(?:to|[-–])\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?![\d/])",
    re.IGNORECASE,
)


def _clock_value(hour_text, minute_text, meridiem, context):
    hour = int(hour_text)
    minute = int(minute_text or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    marker = meridiem
    if marker is None:
        if re.search(r"\bmorning\b", context):
            marker = "am"
        elif re.search(r"\b(?:afternoon|evening|tonight)\b", context):
            marker = "pm"
        else:
            marker = "pm" if hour <= 8 or hour == 12 else "am"
    hour = hour % 12 + (12 if marker.casefold() == "pm" else 0)
    return f"{hour:02d}:{minute:02d}"


def _event_title_before_range(value, index, primary_member):
    value = value.strip(" ,;.-")
    if primary_member and re.search(rf"\b{re.escape(primary_member)}\b", value, re.IGNORECASE):
        value = re.split(rf"\b{re.escape(primary_member)}\b", value, flags=re.IGNORECASE)[-1]
        value = re.sub(r"^\s*(?:has|have|is|will)?\s*", "", value, flags=re.IGNORECASE)
    if index and re.search(r"\band\b", value, re.IGNORECASE):
        value = re.split(r"\band\b", value, flags=re.IGNORECASE)[-1]
    value = re.sub(r"^(?:for\s+)?(?:today|tomorrow)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:please\s+)?(?:schedule|add|create)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*(?:and|is|for)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:from|at)$", "", value, flags=re.IGNORECASE)
    return " ".join(value.split()).strip(" ,;.-")


def extract_calendar_events(text, primary_member):
    matches = list(TIME_RANGE.finditer(text))
    if not matches:
        return []
    gaps = []
    previous_end = 0
    for match in matches:
        gaps.append(text[previous_end:match.start()])
        previous_end = match.end()
    gaps.append(text[previous_end:])
    events = []
    lowered = text.casefold()
    for index, match in enumerate(matches):
        title = _event_title_before_range(gaps[index], index, primary_member)
        if not title:
            after = re.match(r"\s*(?:is|for)\s+(.+?)(?=\s+and\s+|$)", gaps[index + 1], re.IGNORECASE)
            if after:
                title = " ".join(after.group(1).split()).strip(" ,;.-")
                gaps[index + 1] = gaps[index + 1][after.end():]
        start_marker = match.group(3) or match.group(6)
        end_marker = match.group(6) or match.group(3)
        start = _clock_value(match.group(1), match.group(2), start_marker, lowered)
        end = _clock_value(match.group(4), match.group(5), end_marker, lowered)
        if not title or not start or not end:
            continue
        events.append({
            "title": title[0].upper() + title[1:],
            "start_time": start,
            "end_time": end,
            "time_assumed": not bool(match.group(3) or match.group(6)),
        })
    return events


def combine_adjacent_calendar_events(events):
    combined = []
    for event in events:
        current = dict(event)
        if combined and combined[-1]["end_time"] == current["start_time"]:
            previous = combined[-1]
            previous_segments = previous.get("segments") or [{
                "title": previous["title"],
                "start_time": previous["start_time"],
                "end_time": previous["end_time"],
            }]
            previous["segments"] = [*previous_segments, {
                "title": current["title"],
                "start_time": current["start_time"],
                "end_time": current["end_time"],
            }]
            previous["title"] = f"{previous['title']} + {current['title']}"
            previous["end_time"] = current["end_time"]
            previous["time_assumed"] = previous["time_assumed"] or current["time_assumed"]
        else:
            combined.append(current)
    return combined


class ConciergeState(TypedDict, total=False):
    text: str
    now: str
    member_names: list[str]
    family_profiles: list[dict]
    requested_driver: str | None
    requested_transportation_mode: str | None
    requested_pickup_by: str | None
    combine_adjacent_events: bool
    requester_name: str | None
    normalized_text: str
    request_type: str
    mentioned_members: list[str]
    primary_member: str | None
    notification_members: list[str]
    subject_role: str | None
    subject_age: int | None
    requires_parent_driver: bool | None
    driver: str | None
    driver_options: list[str]
    transportation_mode: str | None
    requires_pickup: bool
    pickup_by: str | None
    pickup_options: list[str]
    date: str | None
    time: str | None
    repeat_interval: str
    title: str
    missing_fields: list[str]
    proposed_actions: list[str]
    calendar_events: list[dict]
    source_event_count: int
    llm_plan: dict | None
    llm_used: bool
    dialog_context: dict


def normalize_request(state: ConciergeState):
    return {"normalized_text": " ".join(state["text"].strip().split())}


def interpret_with_llm(state: ConciergeState):
    from concierge_llm import interpret

    plan = interpret(
        state["normalized_text"],
        state["member_names"],
        datetime.fromisoformat(state["now"]),
        **({"dialog_context": state["dialog_context"]} if state.get("dialog_context") else {}),
    )
    return {"llm_plan": plan, "llm_used": plan is not None}


def classify_request(state: ConciergeState):
    text = state["normalized_text"].casefold()
    calendar_words = ("appointment", "calendar", "event", "practice", "meeting", "schedule")
    task_words = ("task", "todo", "to-do", "needs to", "need to", "remember to", "remind")
    llm_type = (state.get("llm_plan") or {}).get("request_type")
    if re.search(r"\b(?:submit|submission|homework|take out|buy|purchase|pay|finish|complete)\b", text) and not re.search(r"\b(?:appointment|meeting|practice|class|therapy|attend)\b", text):
        kind = "task"
    elif re.search(r"\b(?:appointment|dentist|meeting|practice|therapy|class)\b", text) and not re.search(r"\b(?:task|todo|to-do)\b", text):
        kind = "calendar"
    elif llm_type in {"calendar", "task", "needs_review"}:
        kind = llm_type
    elif any(word in text for word in calendar_words):
        kind = "calendar"
    elif any(word in text for word in task_words):
        kind = "task"
    else:
        kind = "needs_review"
    return {"request_type": kind}


def extract_details(state: ConciergeState):
    text = state["normalized_text"]
    lowered = text.casefold()
    now = datetime.fromisoformat(state["now"])
    member_matches = []
    for name in state["member_names"]:
        match = re.search(rf"\b{re.escape(name.casefold())}\b", lowered)
        if match:
            member_matches.append((match.start(), name))
    member_matches.sort()
    mentioned = [name for _, name in member_matches]
    notify_match = re.search(r"\bnotify\b", lowered)
    notify_start = notify_match.start() if notify_match else len(text)
    primary_candidates = [name for position, name in member_matches if position < notify_start]
    primary_member = primary_candidates[0] if primary_candidates else (mentioned[0] if mentioned else None)
    llm_plan = state.get("llm_plan") or {}
    llm_primary = llm_plan.get("primary_member")
    if primary_member is None and llm_primary in state["member_names"]:
        primary_member = llm_primary
        mentioned = [llm_primary, *mentioned]
    requester_name = state.get("requester_name")
    if primary_member is None and requester_name and re.search(r"\b(?:i|me|my|mine)\b", lowered):
        primary_member = requester_name
        mentioned = [requester_name]
    notification_matches = []
    if notify_match:
        notification_text = lowered[notify_match.end():]
        for name in state["member_names"]:
            match = re.search(rf"\b{re.escape(name.casefold())}\b", notification_text)
            if match:
                notification_matches.append((match.start(), name))
    notification_matches.sort()
    notification_members = [name for _, name in notification_matches]
    for name in llm_plan.get("notification_members", []):
        if name in state["member_names"] and name not in notification_members:
            notification_members.append(name)
    profiles = {profile["name"].casefold(): profile for profile in state.get("family_profiles", [])}
    parents = [
        profile["name"] for profile in state.get("family_profiles", [])
        if profile.get("role") == "parent" and profile["name"].casefold() in {name.casefold() for name in state["member_names"]}
    ]
    if notify_match and re.search(r"\bparents?\b", lowered[notify_match.end():]):
        notification_members = list(dict.fromkeys([*notification_members, *parents]))
    subject_profile = profiles.get(primary_member.casefold()) if primary_member else None
    subject_role = subject_profile.get("role") if subject_profile else None
    subject_age = subject_profile.get("age") if subject_profile else None
    is_minor = subject_age < 18 if subject_age is not None else None
    transport_relevant = state["request_type"] == "calendar" or bool(re.search(
        r"\b(?:school|pickup|pick\s+up|practice|transport|ride|drive)\b", lowered
    ))
    requires_parent_driver = is_minor if transport_relevant else False
    transportation_mode = None
    if transport_relevant and is_minor:
        requested_mode = state.get("requested_transportation_mode")
        if requested_mode:
            transportation_mode = requested_mode
        elif re.search(r"\b(?:continues?|remain(?:s|ing)?|already|stays?)\s+(?:at|in)\s+school\b|\bpickup\s+only\b|\bpick\s+up\s+only\b", lowered):
            transportation_mode = "pickup_only"
        elif re.search(r"\b(?:no|doesn['’]?t|does\s+not)\s+(?:driving|drive|ride|transportation|pickup)\s+(?:is\s+)?needed\b", lowered):
            transportation_mode = "none"
        else:
            transportation_mode = "dropoff_and_pickup"
    elif transport_relevant and is_minor is False:
        transportation_mode = "none"
    if transportation_mode in {"pickup_only", "none"} or (transport_relevant and is_minor is False):
        requires_parent_driver = False
    driver = None
    if requires_parent_driver:
        requested_driver = state.get("requested_driver")
        if requested_driver:
            driver = next((parent for parent in parents if parent.casefold() == requested_driver.casefold()), None)
        if driver is None:
            request_before_notify = lowered[:notify_start]
            for parent in parents:
                if re.search(rf"\b{re.escape(parent.casefold())}\b", request_before_notify) and re.search(r"\b(?:drive|take|bring)\b", request_before_notify):
                    driver = parent
                    break
    pickup_options = [*parents, "Uber", "Undecided"] if is_minor and transport_relevant else []
    pickup_by = None
    if transportation_mode in {"dropoff_and_pickup", "pickup_only"}:
        requested_pickup = state.get("requested_pickup_by")
        if requested_pickup:
            pickup_by = next(
                (option for option in pickup_options if option.casefold() == requested_pickup.casefold()),
                None,
            )
        if pickup_by is None and re.search(r"\bpick\s*up\b|\bpickup\b", lowered):
            for option in pickup_options:
                name = re.escape(option.casefold())
                if re.search(rf"\b{name}\b(?:\s+\w+){{0,3}}\s+pick\s*up\b", lowered) or re.search(
                    rf"\bpick\s*up\b(?:\s+\w+){{0,3}}\s+\b{name}\b", lowered
                ):
                    pickup_by = option
                    break
        if pickup_by is None and re.search(r"\buber\b", lowered):
            pickup_by = "Uber"
        if pickup_by is None and re.search(r"\b(?:undecided|not\s+decided|decide\s+later)\b", lowered):
            pickup_by = "Undecided"
        if pickup_by is None and transportation_mode == "dropoff_and_pickup" and driver:
            pickup_by = driver
    if transportation_mode == "none":
        driver = None
        pickup_by = None
    requires_pickup = transportation_mode in {"dropoff_and_pickup", "pickup_only"}
    weekday_numbers = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    weekday_match = re.search(
        r"\b(?:every|each)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lowered,
    )
    repeat_interval = "weekly" if (
        weekday_match or re.search(r"\b(?:weekly|every\s+week)\b", lowered)
    ) else "none"
    day = None
    if re.search(r"\btomorrow\b", lowered):
        day = (now + timedelta(days=1)).date().isoformat()
    elif re.search(r"\btoday\b", lowered):
        day = now.date().isoformat()
    else:
        iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        slash = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
        if iso:
            day = iso.group(1)
        elif slash:
            year = int(slash.group(3) or now.year)
            if year < 100:
                year += 2000
            try:
                day = now.replace(year=year, month=int(slash.group(1)), day=int(slash.group(2))).date().isoformat()
            except ValueError:
                day = None
        elif (weekday_match := re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered)):
            days_ahead = (weekday_numbers[weekday_match.group(1)] - now.weekday()) % 7 or 7
            day = (now + timedelta(days=days_ahead)).date().isoformat()
    if day is None:
        day = llm_plan.get("date")
    clock = None
    match = re.search(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if match:
        hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if 1 <= hour <= 12 and minute < 60:
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
            clock = f"{hour:02d}:{minute:02d}"
    calendar_events = extract_calendar_events(text, primary_member) if state["request_type"] == "calendar" else []
    llm_events = llm_plan.get("calendar_events", [])
    if state["request_type"] == "calendar" and llm_events and len(llm_events) >= len(calendar_events):
        calendar_events = llm_events
    source_event_count = len(calendar_events)
    if state.get("combine_adjacent_events"):
        calendar_events = combine_adjacent_calendar_events(calendar_events)
    if calendar_events:
        clock = calendar_events[0]["start_time"]
    elif clock is None:
        clock = llm_plan.get("time")
    title = re.sub(r"\s*(?:,|\band\b)?\s*\bnotify\b.*$", "", text, flags=re.IGNORECASE)
    title = re.sub(r"\b(today|tomorrow)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", "", title)
    title = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", "", title)
    title = re.sub(r"\b(?:at\s*)?\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(
        r"\b(?:every|each)\s+(?:week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\bweekly\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"^(?:please\s+)?(?:schedule|add|create|put|task|remind(?:\s+me(?:\s+to)?)?)\b\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"^(?:for|to)\s+", "", title, flags=re.IGNORECASE)
    if state["request_type"] == "task" and primary_member:
        title = re.sub(rf"^{re.escape(primary_member)}\s+to\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.-")[:200]
    title = re.sub(r"\bfor\s+for\b", "for", title, flags=re.IGNORECASE)
    if title:
        title = title[0].upper() + title[1:]
    if not title and llm_plan.get("title"):
        title = llm_plan["title"]
    if len(calendar_events) > 1:
        title = f"{len(calendar_events)} calendar events" + (f" for {primary_member}" if primary_member else "")
    return {
        "mentioned_members": mentioned,
        "primary_member": primary_member,
        "notification_members": notification_members,
        "subject_role": subject_role,
        "subject_age": subject_age,
        "requires_parent_driver": requires_parent_driver,
        "driver": driver,
        "driver_options": parents if is_minor and transport_relevant else [],
        "transportation_mode": transportation_mode,
        "requires_pickup": requires_pickup,
        "pickup_by": pickup_by,
        "pickup_options": pickup_options,
        "date": day,
        "time": clock,
        "repeat_interval": repeat_interval,
        "title": title,
        "calendar_events": calendar_events,
        "source_event_count": source_event_count,
        "combine_adjacent_events": bool(state.get("combine_adjacent_events")),
    }


def prepare_preview(state: ConciergeState):
    missing = []
    if state.get("date"):
        try:
            datetime.fromisoformat(state["date"])
        except (TypeError, ValueError):
            state["date"] = None
    if state["request_type"] == "needs_review":
        missing.append("whether this should be a task or calendar event")
    if not state.get("primary_member"):
        missing.append("family member")
    if state["request_type"] == "calendar":
        if not state.get("title"):
            missing.append("title")
        if not state.get("date"):
            missing.append("date")
        if not state.get("time") and not state.get("calendar_events"):
            missing.append("time")
    elif state["request_type"] == "task" and (
        state.get("date") or state.get("time") or state.get("repeat_interval") == "weekly"
    ):
        if not state.get("date"):
            missing.append("date")
        if not state.get("time"):
            missing.append("time")
    if state.get("subject_role") == "child" and state.get("subject_age") is None:
        missing.append(f"{state['primary_member']}’s age in the private family profile")
    if state.get("requires_parent_driver"):
        if not state.get("driver_options"):
            missing.append("a parent in the private family profile")
        elif not state.get("driver"):
            missing.append("which parent will drive")
    if state.get("requires_pickup") and not state.get("pickup_by"):
        missing.append("who will pick up")
    actions = []
    if state["request_type"] == "task":
        actions.append(
            "Prepare a weekly task for review"
            if state.get("repeat_interval") == "weekly"
            else "Prepare a task for review"
        )
    elif state["request_type"] == "calendar":
        event_count = len(state.get("calendar_events", []))
        actions.append(
            f"Prepare {event_count} calendar events for review"
            if event_count > 1 else "Prepare a calendar event for review"
        )
    else:
        actions.append("Ask for clarification")
    if state.get("notification_members"):
        actions.append("Prepare notifications for " + ", ".join(state["notification_members"]))
    if state.get("requires_parent_driver"):
        if state.get("driver"):
            actions.append(f"Plan for {state['driver']} to drive {state['primary_member']}")
        elif state.get("driver_options"):
            actions.append(
                f"Choose a parent to drive {state['primary_member']}: " + ", ".join(state["driver_options"])
            )
    if state.get("transportation_mode") == "pickup_only":
        actions.append(f"No drop-off needed because {state['primary_member']} is already at school")
    elif state.get("transportation_mode") == "none":
        actions.append("Record that no transportation is needed")
    if state.get("requires_pickup"):
        if state.get("pickup_by") == "Undecided":
            actions.append(f"Keep {state['primary_member']}’s pickup assignment undecided")
        elif state.get("pickup_by"):
            actions.append(f"Plan for {state['pickup_by']} to pick up {state['primary_member']}")
        elif state.get("pickup_options"):
            actions.append("Choose pickup: " + ", ".join(state["pickup_options"]))
    return {"missing_fields": missing, "proposed_actions": actions}


builder = StateGraph(ConciergeState)
builder.add_node("normalize", normalize_request)
builder.add_node("interpret_llm", interpret_with_llm)
builder.add_node("classify", classify_request)
builder.add_node("extract", extract_details)
builder.add_node("preview", prepare_preview)
builder.add_edge(START, "normalize")
builder.add_edge("normalize", "interpret_llm")
builder.add_edge("interpret_llm", "classify")
builder.add_edge("classify", "extract")
builder.add_edge("extract", "preview")
builder.add_edge("preview", END)
concierge_graph = builder.compile()


def preview_request(
    text: str,
    member_names: list[str],
    now: datetime,
    family_profiles: list[dict] | None = None,
    driver_name: str | None = None,
    requester_name: str | None = None,
    transportation_mode: str | None = None,
    pickup_by: str | None = None,
    combine_adjacent_events: bool = False,
    dialog_context: dict | None = None,
):
    result = concierge_graph.invoke({
        "text": text,
        "dialog_context": dialog_context or {},
        "member_names": member_names,
        "family_profiles": family_profiles or [],
        "requested_driver": driver_name,
        "requested_transportation_mode": transportation_mode,
        "requested_pickup_by": pickup_by,
        "combine_adjacent_events": combine_adjacent_events,
        "requester_name": requester_name,
        "now": now.isoformat(),
    })
    return {key: result.get(key) for key in (
        "request_type", "title", "mentioned_members", "primary_member", "notification_members",
        "subject_role", "subject_age", "requires_parent_driver", "driver", "driver_options",
        "transportation_mode", "requires_pickup", "pickup_by", "pickup_options",
        "date", "time", "calendar_events", "source_event_count", "combine_adjacent_events",
        "repeat_interval", "missing_fields", "proposed_actions", "llm_used"
    )}
