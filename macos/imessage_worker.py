#!/usr/bin/env python3
"""Deliver due Family Agent alerts through the signed-in macOS Messages app."""
from datetime import datetime
from http.client import RemoteDisconnected
import json
from pathlib import Path
try:
    from api_auth import worker_headers
except ModuleNotFoundError:
    from macos.api_auth import worker_headers
import re
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

API = "http://127.0.0.1:8000"
LOCAL_OPENER = build_opener(ProxyHandler({}))
def local_headers():
    return {'Content-Type': 'application/json', **worker_headers()}

MESSAGE_DB = Path.home() / "Library" / "Messages" / "chat.db"
INBOX_STATE = Path(__file__).resolve().parents[1] / "config" / "imessage-inbox-state.json"
INGEST_SETTINGS = Path(__file__).resolve().parents[1] / "config" / "imessage-ingest.json"
INBOX_SYNC_TIMES = ("07:05", "19:00")
AGENT_PREFIX = re.compile(r"^\s*FA(?:\s*[:,-]\s*|\s+)\S", re.IGNORECASE)
def is_agent_request(text):
    # Messages to our own Apple ID can appear again as incoming messages.
    if re.match(r"^\s*(?:FA|Family Agent)\s+request\s*#\d+\s*:", text, re.I):
        return False
    return bool(AGENT_PREFIX.match(text) or re.fullmatch(r".+?\s+FA\s+#\d+\s*", text, re.I | re.S))


APPLE_SCRIPT = """
on run argv
    set recipientHandle to item 1 of argv
    set messageText to item 2 of argv
    tell application "Messages"
        set targetService to first service whose service type = iMessage
        set targetBuddy to buddy recipientHandle of targetService
        send messageText to targetBuddy
    end tell
end run
"""


def post(path, timeout=10):
    request = Request(
        API + path,
        data=b"{}",
        headers=local_headers(),
        method="POST",
    )
    with LOCAL_OPENER.open(request, timeout=timeout) as response:
        return json.load(response)


def post_json(path, payload, timeout=30):
    request = Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=local_headers(),
        method="POST",
    )
    with LOCAL_OPENER.open(request, timeout=timeout) as response:
        return json.load(response)


def extract_message_text(text, attributed_body):
    """Read ordinary message text, with a best-effort fallback for newer macOS storage."""
    if isinstance(text, str) and text.strip():
        return text
    if not attributed_body:
        return None
    data = bytes(attributed_body)
    marker = b"NSString"
    marker_at = data.find(marker)
    if marker_at < 0:
        return None
    tail = data[marker_at + len(marker):]
    candidates = []
    for offset in range(min(16, len(tail))):
        first = tail[offset]
        if first == 0x81 and offset + 3 <= len(tail):
            length = int.from_bytes(tail[offset + 1:offset + 3], "little")
            start = offset + 3
        elif 0 < first < 0x80:
            length = first
            start = offset + 1
        else:
            continue
        if length <= 0 or start + length > len(tail):
            continue
        try:
            candidate = tail[start:start + length].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if candidate.strip() and all(character.isprintable() or character in "\r\n\t" for character in candidate):
            candidates.append(candidate)
    return next((candidate for candidate in candidates if AGENT_PREFIX.match(candidate)), None)


def read_inbox_state():
    try:
        data = json.loads(INBOX_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_inbox_state(data):
    INBOX_STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = INBOX_STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(INBOX_STATE)


def read_inbox_cursor():
    data = read_inbox_state()
    if "last_rowid" not in data:
        return None
    try:
        return max(0, int(data["last_rowid"]))
    except (ValueError, TypeError):
        return None


def write_inbox_cursor(rowid):
    data = read_inbox_state()
    data["last_rowid"] = rowid
    write_inbox_state(data)


def ingest_mode():
    try:
        settings = json.loads(INGEST_SETTINGS.read_text(encoding="utf-8"))
        mode = settings.get("mode") if isinstance(settings, dict) else None
        return mode if mode in {"testing", "hourly", "scheduled"} else "scheduled"
    except (OSError, ValueError):
        return "scheduled"


def inbox_sync_slot(local_now=None):
    local_now = local_now or datetime.now().astimezone()
    mode = ingest_mode()
    if mode == "testing":
        return "testing:" + local_now.strftime("%Y-%m-%dT%H:%M%z")
    if mode == "hourly":
        return "hourly:" + local_now.strftime("%Y-%m-%dT%H%z")
    minute_of_day = local_now.hour * 60 + local_now.minute
    due_times = []
    for value in INBOX_SYNC_TIMES:
        hour, minute = (int(part) for part in value.split(":"))
        if minute_of_day >= hour * 60 + minute:
            due_times.append(value)
    if not due_times:
        return None
    return f"{local_now.date().isoformat()}:{due_times[-1]}"


def inbox_slot_completed(slot):
    return read_inbox_state().get("last_ingest_slot") == slot


def mark_inbox_slot_completed(slot):
    data = read_inbox_state()
    data["last_ingest_slot"] = slot
    write_inbox_state(data)


def sync_incoming_messages(replies_only=False):
    """Submit only new FA-prefixed family replies for a reviewed Concierge plan."""
    uri = "file:{}?mode=ro".format(MESSAGE_DB.as_posix())
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        cursor = read_inbox_state().get("dialog_cursor", read_inbox_cursor()) if replies_only else read_inbox_cursor()
        if cursor is None:
            newest = connection.execute("SELECT COALESCE(MAX(ROWID), 0) FROM message").fetchone()[0]
            if replies_only:
                state = read_inbox_state()
                state["dialog_cursor"] = newest
                write_inbox_state(state)
            else:
                write_inbox_cursor(newest)
            return 0
        rows = connection.execute(
            """
            SELECT message.ROWID, message.guid, message.text, message.attributedBody, handle.id
            FROM message
            LEFT JOIN handle ON handle.ROWID = message.handle_id
            WHERE message.ROWID > ? AND message.is_from_me = 0
            ORDER BY message.ROWID
            LIMIT 200
            """,
            (cursor,),
        ).fetchall()
    planned = 0
    newest = cursor
    for rowid, guid, text, attributed_body, sender in rows:
        newest = max(newest, rowid)
        message_text = extract_message_text(text, attributed_body)
        if (
            not guid or not sender or not message_text or not is_agent_request(message_text)
            or len(guid) > 200 or len(sender) > 254 or len(message_text) > 2000
        ):
            continue
        if replies_only and not (re.match(r"^\s*FA(?:\s*[:,-]\s*|\s+)#\d+\s+\S", message_text, re.I) or re.fullmatch(r".+?\s+FA\s+#\d+\s*", message_text, re.I | re.S)):
            continue
        result = post_json(
            "/concierge/inbox",
            {"message_guid": guid, "sender_handle": sender, "text": message_text},
            timeout=150,
        )
        # No message text, address or phone number is logged.
        print("FA intake result: {} (request {}).".format(result.get("status", "unknown"), (result.get("item") or {}).get("id", "none")), flush=True)
        if result.get("status") == "planned":
            planned += 1
    if newest != cursor:
        if replies_only:
            state = read_inbox_state()
            state["dialog_cursor"] = newest
            write_inbox_state(state)
        else:
            write_inbox_cursor(newest)
    return planned


def wait_for_api():
    for _ in range(30):
        try:
            with LOCAL_OPENER.open(API + "/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (URLError, RemoteDisconnected, ConnectionResetError):
            time.sleep(1)
    raise RuntimeError("Family Agent did not become ready within 30 seconds")


def sync_calendar_alerts():
    try:
        post("/alerts/calendar/sync", timeout=60)
    except HTTPError as error:
        if error.code != 404:
            print("Calendar reminders could not be refreshed (HTTP {}).".format(error.code), file=sys.stderr)
    except (URLError, RemoteDisconnected, ConnectionResetError, TimeoutError):
        print("Calendar reminders could not be refreshed. Existing due alerts will still be delivered.", file=sys.stderr)


def sync_morning_briefings():
    try:
        post("/alerts/morning/sync", timeout=60)
    except HTTPError as error:
        if error.code != 404:
            print("Morning briefings could not be refreshed (HTTP {}).".format(error.code), file=sys.stderr)
    except (URLError, RemoteDisconnected, ConnectionResetError, TimeoutError):
        print("Morning briefings could not be refreshed. Existing due alerts will still be delivered.", file=sys.stderr)


def sync_commute_reports():
    source = Path(__file__).with_name("traffic_eta.m")
    binary = Path(__file__).resolve().parents[1] / "config" / "traffic_eta"
    while True:
        try:
            appointment = False
            claim = post("/commutes/claim", timeout=60)
            one_time = claim is None
            if one_time:
                claim = post("/traffic/checks/claim", timeout=60)
            if claim is None:
                appointment = True
                claim = post("/departure/traffic/claim", timeout=60)
        except HTTPError as error:
            if error.code != 404:
                print("Commute traffic schedules could not be refreshed (HTTP {}).".format(error.code), file=sys.stderr)
            return
        except (URLError, RemoteDisconnected, ConnectionResetError, TimeoutError):
            print("Commute traffic schedules could not be refreshed. Existing alerts will still be delivered.", file=sys.stderr)
            return
        if claim is None:
            return
        try:
            if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
                compiled = subprocess.run(
                    ["/usr/bin/xcrun", "clang", "-fobjc-arc", str(source), "-o", str(binary),
                     "-framework", "Foundation", "-framework", "CoreLocation", "-framework", "MapKit"],
                    capture_output=True, text=True, timeout=60,
                )
                if compiled.returncode != 0:
                    raise OSError("traffic helper compilation failed")
                binary.chmod(0o700)
            result = subprocess.run(
                [str(binary), claim["origin_address"], claim["destination_address"]],
                capture_output=True, text=True, timeout=60,
            )
            payload = json.loads(result.stdout.strip()) if result.returncode == 0 else {"error": "routing unavailable"}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            payload = {"error": "routing unavailable"}
        try:
            if appointment:
                payload["claim_token"] = claim["claim_token"]
                post_json("/departure/traffic/{}/complete".format(claim["run_id"]), payload, timeout=30)
            elif one_time:
                payload["claim_token"] = claim["claim_token"]
                post_json("/traffic/checks/{}/complete".format(claim["run_id"]), payload, timeout=30)
            else:
                post_json("/commutes/runs/{}/complete".format(claim["run_id"]), payload, timeout=30)
        except (HTTPError, URLError, RemoteDisconnected, ConnectionResetError, TimeoutError):
            print("A commute traffic result could not be saved. It will be recovered safely.", file=sys.stderr)
            return


def deliver(alert):
    try:
        result = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                APPLE_SCRIPT,
                alert["imessage_handle"],
                alert["message"],
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return "sent" if result.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        # Messages may have accepted the send before osascript timed out.
        return "uncertain"
    except OSError:
        return "failed"


def main():
    try:
        from self_healing import maybe_run_weekly_validation
    except ModuleNotFoundError:  # Allows the same worker to be imported by the test suite.
        from macos.self_healing import maybe_run_weekly_validation

    try:
        healing = maybe_run_weekly_validation()
        if healing is not None:
            print("Weekly validation finished with status: {}.".format(healing["status"]))
    except Exception:
        print("Weekly validation could not complete; alert delivery will continue.")
    wait_for_api()
    slot = inbox_sync_slot()
    if slot is not None and not inbox_slot_completed(slot):
        try:
            planned = sync_incoming_messages()
            mark_inbox_slot_completed(slot)
            print("Ingested FA messages for the {} window.".format(slot.split(":", 1)[1]))
            if planned:
                print("Added {} new FA request{} to Concierge review.".format(planned, "" if planned == 1 else "s"))
        except sqlite3.Error:
            print(
                "Incoming FA requests could not be checked. Allow Full Disk Access for the Family Agent iMessage bridge.",
                file=sys.stderr,
            )
        except (URLError, RemoteDisconnected, TimeoutError, OSError):
            print("FA ingestion could not complete; it will retry next run.", file=sys.stderr)
    try:
        sync_incoming_messages(replies_only=True)
    except (sqlite3.Error, URLError, RemoteDisconnected, TimeoutError, OSError):
        print("Concierge follow-up check could not complete; it will retry next run.", file=sys.stderr)
    sync_calendar_alerts()
    sync_morning_briefings()
    sync_commute_reports()
    delivered = 0
    while True:
        alert = post("/alerts/claim")
        if alert is None:
            break
        outcome = deliver(alert)
        post("/alerts/{}/{}".format(alert["id"], outcome))
        if outcome == "sent":
            delivered += 1
        elif outcome == "failed":
            print("An iMessage could not be delivered. No contact details were printed.", file=sys.stderr)
        else:
            print("An iMessage delivery timed out and was marked uncertain to prevent a duplicate.", file=sys.stderr)
    print("Delivered {} due alert{}.".format(delivered, "" if delivered == 1 else "s"))


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        print(
            "Family Agent returned HTTP {} while processing the alert.".format(error.code),
            file=sys.stderr,
        )
        raise SystemExit(1)
    except URLError as error:
        print("Could not connect to Family Agent: {}.".format(error.reason), file=sys.stderr)
        raise SystemExit(1)
    except (RemoteDisconnected, ConnectionResetError, TimeoutError, RuntimeError) as error:
        print("Could not connect to Family Agent: {}.".format(error), file=sys.stderr)
        raise SystemExit(1)
