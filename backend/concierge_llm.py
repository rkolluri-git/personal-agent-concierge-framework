"""Optional structured LLM interpretation with a deterministic fallback."""
from datetime import date
from functools import lru_cache
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlparse


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

# Local requests must not be forwarded through a proxy or redirected elsewhere.
urlopen = build_opener(ProxyHandler({}), NoRedirect()).open


def local_endpoint():
    value = os.environ.get('OLLAMA_BASE_URL', 'http://host.docker.internal:11434').rstrip('/')
    parsed = urlparse(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost','127.0.0.1','::1','host.docker.internal'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
        return None
    return value

REQUEST_TEMPLATE = json.loads(Path(__file__).with_name("concierge_template.json").read_text())
VALID_REQUEST_TYPES = {"calendar", "task", "needs_review"}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def configured():
    return (os.environ.get('FAMILY_LLM_PROVIDER', 'none').casefold() == 'ollama'
            and local_endpoint() is not None
            and 'cloud' not in os.environ.get('FAMILY_LLM_MODEL', 'qwen3.5:9b').casefold())


def _schema():
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "request_type", "title", "primary_member", "notification_members",
            "date", "time", "calendar_events", "repeat_interval",
        ],
        "properties": {
            "request_type": {"type": "string", "enum": sorted(VALID_REQUEST_TYPES)},
            "title": nullable_string,
            "primary_member": nullable_string,
            "notification_members": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "date": nullable_string,
            "time": nullable_string,
            "calendar_events": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "start_time", "end_time"],
                    "properties": {
                        "title": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                    },
                },
            },
            "repeat_interval": {"type": "string", "enum": ["none", "weekly"]},
        },
    }


def _known_name(value, names):
    if not isinstance(value, str):
        return None
    return next((name for name in names if name.casefold() == value.casefold()), None)


def _validate(raw, member_names):
    if not isinstance(raw, dict) or raw.get("request_type") not in VALID_REQUEST_TYPES:
        return None
    result = {
        "request_type": raw["request_type"],
        "title": raw.get("title")[:200] if isinstance(raw.get("title"), str) else None,
        "primary_member": _known_name(raw.get("primary_member"), member_names),
        "notification_members": [],
        "date": None,
        "time": raw.get("time") if isinstance(raw.get("time"), str) and TIME_PATTERN.fullmatch(raw["time"]) else None,
        "calendar_events": [],
        "repeat_interval": raw.get("repeat_interval") if raw.get("repeat_interval") in {"none", "weekly"} else "none",
    }
    for value in raw.get("notification_members", []):
        name = _known_name(value, member_names)
        if name and name not in result["notification_members"]:
            result["notification_members"].append(name)
    if isinstance(raw.get("date"), str):
        try:
            result["date"] = date.fromisoformat(raw["date"]).isoformat()
        except ValueError:
            pass
    for event in raw.get("calendar_events", [])[:20]:
        if not isinstance(event, dict) or not isinstance(event.get("title"), str):
            continue
        start, end = event.get("start_time"), event.get("end_time")
        if not isinstance(start, str) or not isinstance(end, str) or not TIME_PATTERN.fullmatch(start) or not TIME_PATTERN.fullmatch(end):
            continue
        result["calendar_events"].append({
            "title": event["title"].strip()[:200],
            "start_time": start,
            "end_time": end,
            "time_assumed": False,
        })
    return result


@lru_cache(maxsize=128)
def _interpret_cached(text, member_names, local_now, dialog_context="{}"):
    if not configured():
        return None
    payload = {
        "instructions": (
            "Extract a family request into the supplied schema. Split every separately named activity with its own "
            "time range into a separate calendar event, even when events are adjacent. Resolve relative dates from "
            "the supplied local time. Use 24-hour HH:MM times. Only use a family member name from the supplied list. "
            "Do not invent missing facts. Return data only; never take an external action. "
            + json.dumps(REQUEST_TEMPLATE)
        ),
        "input": json.dumps({"request": text, "family_members": list(member_names), "local_now": local_now, "confirmed_draft": json.loads(dialog_context)}),
    }
    provider = os.environ.get("FAMILY_LLM_PROVIDER", "none").casefold()
    if provider == "ollama":
        local_payload = {
            "model": os.environ.get("FAMILY_LLM_MODEL", "qwen3.5:9b"),
            "messages": [
                {"role": "system", "content": payload["instructions"] + " Populate calendar_events with ALL activities that have time ranges; never leave it empty when ranges are present. Example: speech 15:30-16:00, therapy 16:00-16:30, scouts 19:00-19:30 must yield three entries. JSON schema: " + json.dumps(_schema())},
                {"role": "user", "content": payload["input"]},
            ],
            "format": _schema(), "stream": False,
            "think": "low" if os.environ.get("FAMILY_LLM_MODEL", "qwen3.5:9b").startswith("gpt-oss") else False, "options": {"temperature": 0, "num_predict": 4096},
        }
        request = Request(
            local_endpoint() + "/api/chat",
            data=json.dumps(local_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = json.load(response)
            if body.get("done_reason") == "length":
                return None
            return _validate(json.loads(body["message"]["content"]), member_names)
        except (URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
            return None
    return None


def interpret(text, member_names, local_now, dialog_context=None):
    """Return validated structured data, or None so the local parser continues safely."""
    cache_time = local_now.replace(second=0, microsecond=0).isoformat()
    return _interpret_cached(text, tuple(member_names), cache_time, json.dumps(dialog_context or {}, sort_keys=True)) if configured() else None
