from pathlib import Path
from datetime import datetime
import sqlite3
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

from macos import imessage_worker
from macos.imessage_worker import AGENT_PREFIX, extract_message_text


def test_prefers_plain_message_text():
    assert extract_message_text("FA add a task", b"ignored") == "FA add a task"


def test_extracts_short_attributed_message_text():
    message = "FA: add milk"
    blob = b"prefixNSString\x00" + bytes([len(message)]) + message.encode()
    assert extract_message_text(None, blob) == message


def test_extracts_long_attributed_message_text():
    message = "FA " + "schedule this appointment " * 12
    encoded = message.encode()
    blob = b"prefixNSString\x00\x81" + len(encoded).to_bytes(2, "little") + encoded
    assert extract_message_text(None, blob) == message


def test_local_filter_requires_explicit_fa_prefix():
    assert AGENT_PREFIX.match("FA schedule a task")
    assert AGENT_PREFIX.match(" fa: schedule a task")
    assert not AGENT_PREFIX.match("Family schedule a task")
    assert not AGENT_PREFIX.match("FA")


def test_inbox_ingestion_has_one_morning_and_evening_slot():
    zone = ZoneInfo("America/New_York")
    assert imessage_worker.inbox_sync_slot(datetime(2026, 9, 13, 7, 4, tzinfo=zone)) is None
    assert imessage_worker.inbox_sync_slot(datetime(2026, 9, 13, 7, 5, tzinfo=zone)) == "2026-09-13:07:05"
    assert imessage_worker.inbox_sync_slot(datetime(2026, 9, 13, 18, 59, tzinfo=zone)) == "2026-09-13:07:05"
    assert imessage_worker.inbox_sync_slot(datetime(2026, 9, 13, 19, 0, tzinfo=zone)) == "2026-09-13:19:00"


def test_cursor_and_ingestion_slot_share_the_private_state_file():
    with tempfile.TemporaryDirectory() as directory:
        original_state = imessage_worker.INBOX_STATE
        imessage_worker.INBOX_STATE = Path(directory) / "state.json"
        try:
            imessage_worker.write_inbox_cursor(42)
            imessage_worker.mark_inbox_slot_completed("2026-09-13:07:05")
            assert imessage_worker.read_inbox_cursor() == 42
            assert imessage_worker.inbox_slot_completed("2026-09-13:07:05")
        finally:
            imessage_worker.INBOX_STATE = original_state


def test_first_scan_skips_history_then_submits_only_new_fa_messages():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "chat.db"
        state = Path(directory) / "cursor.json"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                CREATE TABLE message (
                    ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT,
                    attributedBody BLOB, handle_id INTEGER, is_from_me INTEGER
                );
                INSERT INTO handle VALUES (1, 'family@example.com');
                INSERT INTO message VALUES (1, 'old', 'FA old request', NULL, 1, 0);
                """
            )
        original_database = imessage_worker.MESSAGE_DB
        original_state = imessage_worker.INBOX_STATE
        original_post = imessage_worker.post_json
        submitted = []
        imessage_worker.MESSAGE_DB = database
        imessage_worker.INBOX_STATE = state
        imessage_worker.post_json = lambda path, payload, timeout=30: submitted.append((path, payload)) or {"status": "planned"}
        try:
            assert imessage_worker.sync_incoming_messages() == 0
            assert submitted == []
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO message VALUES (2, 'personal', 'Thanks!', NULL, 1, 0)")
                connection.execute("INSERT INTO message VALUES (3, 'agent', 'FA: add milk', NULL, 1, 0)")
            assert imessage_worker.sync_incoming_messages() == 1
            assert len(submitted) == 1
            assert submitted[0][1]["message_guid"] == "agent"
            assert submitted[0][1]["text"] == "FA: add milk"
            assert imessage_worker.sync_incoming_messages() == 0
        finally:
            imessage_worker.MESSAGE_DB = original_database
            imessage_worker.INBOX_STATE = original_state
            imessage_worker.post_json = original_post


def test_message_timeout_is_acknowledged_as_uncertain():
    alert = {"id": 7, "imessage_handle": "family@example.com", "message": "Test"}
    calls = []

    def fake_post(path, timeout=10):
        calls.append(path)
        return alert if path == "/alerts/claim" and calls.count(path) == 1 else None

    with patch("macos.self_healing.maybe_run_weekly_validation", return_value=None), \
         patch.object(imessage_worker, "wait_for_api"), \
         patch.object(imessage_worker, "inbox_sync_slot", return_value=None), \
         patch.object(imessage_worker, "sync_calendar_alerts"), \
         patch.object(imessage_worker, "sync_morning_briefings"), \
         patch.object(imessage_worker, "sync_commute_reports"), \
         patch.object(imessage_worker, "post", side_effect=fake_post), \
         patch.object(imessage_worker.subprocess, "run", side_effect=imessage_worker.subprocess.TimeoutExpired("osascript", 30)):
        imessage_worker.main()

    assert "/alerts/7/uncertain" in calls


def test_numbered_replies_do_not_consume_regular_ingest_cursor(tmp_path, monkeypatch):
    database = tmp_path / 'chat.db'
    state = tmp_path / 'state.json'
    monkeypatch.setattr(imessage_worker, 'MESSAGE_DB', database)
    monkeypatch.setattr(imessage_worker, 'INBOX_STATE', state)
    with sqlite3.connect(database) as connection:
        connection.executescript('''
            CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
            CREATE TABLE message (ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB, handle_id INTEGER, is_from_me INTEGER);
            INSERT INTO handle VALUES (1, '+15555550101');
            INSERT INTO message VALUES (1, 'new-request', 'FA buy milk', NULL, 1, 0);
            INSERT INTO message VALUES (2, 'reply', 'FA #42 tomorrow', NULL, 1, 0);
            INSERT INTO message VALUES (3, 'personal', 'See you soon', NULL, 1, 0);
        ''')
    imessage_worker.write_inbox_cursor(0)
    submitted=[]
    monkeypatch.setattr(imessage_worker,'post_json',lambda path,payload,timeout: submitted.append(payload['message_guid']) or {'status':'planned'})
    assert imessage_worker.sync_incoming_messages(replies_only=True)==1
    assert submitted==['reply']
    assert imessage_worker.read_inbox_cursor()==0
    assert imessage_worker.sync_incoming_messages(replies_only=True)==0
    assert imessage_worker.sync_incoming_messages()==2
    assert submitted==['reply','new-request','reply']


def test_testing_and_hourly_ingest_modes(tmp_path, monkeypatch):
    settings=tmp_path/'ingest.json'
    monkeypatch.setattr(imessage_worker,'INGEST_SETTINGS',settings)
    zone=ZoneInfo('America/New_York')
    first=datetime(2026,9,14,11,30,tzinfo=zone)
    later=datetime(2026,9,14,11,31,tzinfo=zone)
    next_hour=datetime(2026,9,14,12,0,tzinfo=zone)
    settings.write_text('{"mode":"testing"}')
    assert imessage_worker.inbox_sync_slot(first)!=imessage_worker.inbox_sync_slot(later)
    settings.write_text('{"mode":"hourly"}')
    assert imessage_worker.inbox_sync_slot(first)==imessage_worker.inbox_sync_slot(later)
    assert imessage_worker.inbox_sync_slot(first)!=imessage_worker.inbox_sync_slot(next_hour)
    settings.write_text('invalid')
    assert imessage_worker.ingest_mode()=='scheduled'
    settings.write_text('{"mode":"unexpected"}')
    assert imessage_worker.ingest_mode()=='scheduled'


def test_worker_ignores_self_echo_and_accepts_numbered_suffix():
    assert not imessage_worker.is_agent_request('FA request #12: Is this a task? Reply FA #12 followed by your answer.')
    assert not imessage_worker.is_agent_request('Family Agent request #12: What date is it?')
    assert imessage_worker.is_agent_request('Parent One will drive. FA #10')
    assert imessage_worker.is_agent_request('FA #10 Parent One will drive')
    assert not imessage_worker.is_agent_request('Parent One will drive')
