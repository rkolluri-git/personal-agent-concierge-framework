"""Read-only calendar adapters. Credentials stay in the private config mount."""
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import quote
from zoneinfo import ZoneInfo

import caldav
import niquests
from fastapi import APIRouter
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field
from calendar_conflicts import find_conflicts

CONFIG = Path(os.environ.get("CALENDAR_CONFIG_DIR", "/app/config"))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
from regional_settings import REGIONAL
LOCAL_ZONE = ZoneInfo(REGIONAL.timezone)
router = APIRouter(prefix="/calendar", tags=["Calendar"])
CALENDAR_CACHE_SECONDS = 60
_calendar_cache = {}
_calendar_cache_lock = Lock()


def read_config(name):
    path = CONFIG / name
    return json.loads(path.read_text()) if path.exists() else None


def save_config(name, value):
    CONFIG.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=CONFIG)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(value, file)
        os.chmod(temporary, 0o600)
        os.replace(temporary, CONFIG / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CalendarEvent(BaseModel):
    id: str
    source: str
    calendar: str
    title: str
    start: str
    end: str
    all_day: bool
    end_known: bool = True
    location: str = ""
    busy: bool = True
    uid: str = Field(default="", exclude=True)
    departure_ready: bool = False
    calendar_key: str = ""


def event_id(source, calendar, uid, start):
    return hashlib.sha256(json.dumps([source, calendar, uid, start]).encode()).hexdigest()[:32]


def calendar_key(source, calendar_id):
    return hashlib.sha256(json.dumps([source, calendar_id]).encode()).hexdigest()[:24]


def available_calendars():
    rows = []
    google = read_config("google-calendars.json") or []
    icloud = read_config("icloud.json") or {}
    for source, calendars in (("google", google), ("icloud", icloud.get("calendars", []))):
        for calendar in calendars:
            rows.append({
                "key": calendar_key(source, calendar["id"]),
                "source": source,
                "name": calendar.get("name") or "Calendar",
            })
    return rows


def google_event(item, calendar):
    if item.get("status") == "cancelled":
        return None
    start = item["start"]
    all_day = "date" in start
    key = "date" if all_day else "dateTime"
    beginning, end = start[key], item["end"][key]
    return CalendarEvent(id=event_id("google", calendar["id"], item["id"], beginning),
                         source="google", calendar=calendar["name"],
                         title=item.get("summary") or "Untitled event", start=beginning,
                         end=end, all_day=all_day, location=item.get("location", ""),
                         uid=item.get("iCalUID", ""),
                         calendar_key=calendar_key("google", calendar["id"]),
                         departure_ready=not all_day and bool(item.get("location", "").strip()),
                         busy=item.get("transparency") != "transparent" and not any(
                             a.get("self") and a.get("responseStatus") == "declined" for a in item.get("attendees", [])))


def aware(value, zone=LOCAL_ZONE):
    return value.replace(tzinfo=zone) if value.tzinfo is None else value


def icloud_event(component, calendar, zone=LOCAL_ZONE):
    if str(component.get("STATUS", "")).upper() == "CANCELLED":
        return None
    start = component.decoded("DTSTART")
    all_day = isinstance(start, date) and not isinstance(start, datetime)
    end = component.decoded("DTEND") if "DTEND" in component else start + (component.decoded("DURATION") if "DURATION" in component else timedelta(days=1) if all_day else timedelta())
    if not all_day:
        start, end = aware(start, zone), aware(end, zone)
    beginning, ending = start.isoformat(), end.isoformat()
    return CalendarEvent(id=event_id("icloud", calendar["id"], str(component.get("UID", "")), beginning),
                         source="icloud", calendar=calendar["name"],
                         title=str(component.get("SUMMARY", "")) or "Untitled event",
                         start=beginning, end=ending, all_day=all_day, end_known=("DTEND" in component or "DURATION" in component),
                         location=str(component.get("LOCATION", "")),
                         uid=str(component.get("UID", "")),
                         calendar_key=calendar_key("icloud", calendar["id"]),
                         departure_ready=not all_day and bool(str(component.get("LOCATION", "")).strip()),
                         busy=str(component.get("TRANSP", "OPAQUE")).upper() != "TRANSPARENT")


def read_google(start, end):
    token, selected = read_config("google-token.json"), read_config("google-calendars.json")
    if not token or not selected:
        return [], {"source": "google", "status": "not_connected", "message": "Connect Google Calendar on your Mac."}
    credentials = Credentials.from_authorized_user_info(token, SCOPES)
    events = []
    with AuthorizedSession(credentials) as session:
        for calendar in selected:
            page = None
            for _ in range(20):
                params = {"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                          "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
                if page:
                    params["pageToken"] = page
                response = session.get(f'https://www.googleapis.com/calendar/v3/calendars/{quote(calendar["id"], safe="")}/events', params=params, timeout=20)
                response.raise_for_status()
                result = response.json()
                events.extend(event for item in result.get("items", []) if (event := google_event(item, calendar)) is not None)
                page = result.get("nextPageToken")
                if not page:
                    break
            if page:
                raise ValueError("Calendar response exceeds the supported window size")
    save_config("google-token.json", json.loads(credentials.to_json()))
    return events, {"source": "google", "status": "connected", "message": "Up to date"}


def icloud_client(username, password):
    client = caldav.DAVClient(url="https://caldav.icloud.com", username=username,
                              password=password, timeout=20)
    # Automatic protocol upgrades stall during iCloud authentication in Docker.
    # Use HTTPS over HTTP/1.1; certificate verification remains enabled.
    client.session.close()
    client.session = niquests.Session(disable_http2=True, disable_http3=True)
    return client


def read_icloud(start, end):
    config = read_config("icloud.json")
    if not config:
        return [], {"source": "icloud", "status": "not_connected", "message": "Connect iCloud Calendar on your Mac."}
    events = []
    with icloud_client(config["username"], config["password"]) as client:
        for selected in config["calendars"]:
            calendar = client.calendar(url=selected["id"])
            for result in calendar.search(start=start, end=end, event=True, expand=True):
                event = icloud_event(result.get_icalendar_component(), selected)
                if event is not None:
                    events.append(event)
    return events, {"source": "icloud", "status": "connected", "message": "Up to date"}


def fetch_source(source, start, end):
    try:
        return (read_google if source == "google" else read_icloud)(start, end)
    except Exception:
        # Provider errors may contain account identifiers or tokens. Never expose them.
        return [], {"source": source, "status": "error", "message": "Could not refresh. Check the connection and try again; reconnect if needed."}


def sort_key(event):
    return (datetime.combine(date.fromisoformat(event.start), time.min, LOCAL_ZONE)
            if event.all_day else datetime.fromisoformat(event.start.replace("Z", "+00:00"))).timestamp()


def upcoming_events(refresh: bool = False):
    start = datetime.combine(datetime.now(LOCAL_ZONE).date(), time.min, LOCAL_ZONE)
    end = start + timedelta(days=14)
    cache_key = (str(CONFIG), start.date().isoformat())
    with _calendar_cache_lock:
        cached = _calendar_cache.get(cache_key)
        if not refresh and cached and monotonic() - cached[0] < CALENDAR_CACHE_SECONDS:
            return cached[1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda source: fetch_source(source, start - timedelta(days=1), end), ["google", "icloud"]))
        events = sorted((event for rows, _ in results for event in rows), key=sort_key)
        response = {"events": events, "sources": [status for _, status in results],
                    "departure_ready_count": sum(event.departure_ready for event in events),
                    "missing_location_count": sum(not event.all_day and not event.departure_ready for event in events),
                    "conflicts": find_conflicts(events, start, end),
                    "conflict_check_complete": all(status["status"] == "connected" for _, status in results),
                    "window_start": start.isoformat(), "window_end": end.isoformat(),
                    "timezone": str(LOCAL_ZONE), "checked_at": datetime.now(timezone.utc).isoformat()}
        _calendar_cache[cache_key] = (monotonic(), response)
        return response


@router.get("/available")
def list_available_calendars():
    return available_calendars()


@router.get('/events')
def visible_calendar_events():
    from calendar_archive import maintain, end_time
    data=upcoming_events()
    maintain(data['events'],data['conflict_check_complete'],LOCAL_ZONE)
    now=datetime.now(timezone.utc)
    events=[e for e in data['events'] if not data['conflict_check_complete'] or end_time(e,LOCAL_ZONE) is None or now < end_time(e,LOCAL_ZONE)+timedelta(hours=1)]
    result=dict(data,events=events)
    result['departure_ready_count']=sum(e.departure_ready for e in events)
    result['missing_location_count']=sum(not e.all_day and not e.departure_ready for e in events)
    result['conflicts']=[c for c in data['conflicts'] if all(id in {e.id for e in events} for id in c.get('event_ids',[]))]
    return result
