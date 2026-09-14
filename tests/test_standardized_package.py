import json
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import auth_service
import events_service as events
from regional_settings import RegionalSettings


def test_school_calendar_requires_explicit_selection():
    assert RegionalSettings.from_env({}).school_calendar == 'none'


def test_no_event_sources_until_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(events, 'CONFIG', tmp_path)
    assert events.load_sources() == ({}, 'USD')


def test_event_sources_and_currency_are_installation_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(events, 'CONFIG', tmp_path)
    sources = {'Example Venue': 'https://example.com/concerts'}
    (tmp_path / 'event-sources.json').write_text(json.dumps({'sources': sources, 'currency': 'INR'}))
    assert events.load_sources() == (sources, 'INR')
    monkeypatch.setattr(events, 'CURRENCY', 'INR')
    prefs = events.EventPreferences(enabled=True, max_ticket_price=500, include_unknown_prices=False).model_dump()
    assert events.preference_match({'price': 'INR 450'}, prefs)
    assert not events.preference_match({'price': 'USD 450'}, prefs)


@pytest.mark.parametrize('url', ['http://example.com', 'https://user:secret@example.com', 'file:///tmp/page'])
def test_event_source_urls_reject_credentials_and_non_https(tmp_path, monkeypatch, url):
    monkeypatch.setattr(events, 'CONFIG', tmp_path)
    (tmp_path / 'event-sources.json').write_text(json.dumps({'sources': {'Example': url}}))
    with pytest.raises(ValueError): events.load_sources()


def test_event_dates_follow_installation_timezone(monkeypatch):
    monkeypatch.setattr(events, 'ZONE', ZoneInfo('Asia/Kolkata'))
    html = '<script type="application/ld+json">' + json.dumps({
        '@type': 'MusicEvent', 'name': 'Example', 'startDate': '2026-10-01T20:00:00',
    }) + '</script>'
    assert events.parse_events(html, 'Example Venue')[0]['start'].endswith('+05:30')


def test_traffic_worker_scope_cannot_create_or_list_private_checks():
    assert auth_service.worker_allowed('/traffic/checks/claim', 'POST')
    assert auth_service.worker_allowed('/traffic/checks/123/complete', 'POST')
    assert not auth_service.worker_allowed('/traffic/checks', 'POST')
    assert not auth_service.worker_allowed('/traffic/checks', 'GET')
    assert not auth_service.worker_allowed('/traffic/checks/claim', 'POST', remote=True)


def test_actual_api_protects_new_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    monkeypatch.setattr(auth_service, 'CONFIG', tmp_path)
    auth_service.initialize_keys()
    # Deliberately omit lifespan: no production database or integration startup.
    client = TestClient(app)
    for path in ('/events/concerts', '/traffic/checks', '/places/status', '/concierge/inbox'):
        assert client.get(path).status_code == 401
    assert client.post('/concierge/inbox/1/reply', json={}).status_code == 401
    headers = {'Authorization': 'Bearer ' + auth_service.read_key('worker')}
    assert client.get('/events/concerts', headers=headers).status_code == 403
    assert client.post('/traffic/checks', json={}, headers=headers).status_code == 403
    client.close()


def test_appointment_worker_cannot_edit_calendars_or_recipients():
    assert auth_service.worker_allowed('/departure/traffic/claim', 'POST')
    assert auth_service.worker_allowed('/departure/traffic/example-event/complete', 'POST')
    assert auth_service.worker_allowed('/departure/traffic/wake-plan', 'GET')
    assert not auth_service.worker_allowed('/departure/traffic/example-event/recipients', 'PUT')
    assert not auth_service.worker_allowed('/calendar/icloud/events', 'POST')
    assert not auth_service.worker_allowed('/calendar/archive', 'GET')
    assert not auth_service.worker_allowed('/departure/traffic/claim', 'POST', remote=True)


def test_new_actual_routes_reject_unauthenticated_requests(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    monkeypatch.setattr(auth_service, 'CONFIG', tmp_path)
    auth_service.initialize_keys()
    client = TestClient(app)
    for path in ('/calendar/archive', '/calendar/icloud/calendars', '/departure/traffic/wake-plan'):
        assert client.get(path).status_code == 401
    assert client.post('/calendar/icloud/events', json={}).status_code == 401
    assert client.get('/health', headers={'Host': 'untrusted.example'}).status_code == 400
    client.close()
