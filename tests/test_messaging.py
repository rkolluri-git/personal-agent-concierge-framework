import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from twilio.request_validator import RequestValidator
from twilio.base.exceptions import TwilioRestException

import messaging_gateway as gateway
import messaging_settings as settings
import messaging_worker as worker
from main import claim_due_alert, receive_remote_message
from schemas import ConciergeInboxRequest


CONFIG = {
    'provider': 'twilio-sms', 'bridge_token': 'a' * 40,
    'sender_number': '+15555550100', 'opted_in_recipients': ['+15555550101'],
    'account_sid': 'AC' + '1' * 32, 'auth_token': '2' * 32,
    'webhook_url': 'https://relay.example/webhooks/twilio',
}
ALERT = {'id': 1, 'imessage_handle': '+15555550101', 'message': 'Bring a jacket', 'member_name': 'Alex'}


def test_settings_require_dedicated_number_consent_and_secret():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, FAMILY_MESSAGING_PROVIDER='twilio-sms'):
        path = Path(tmp) / 'messaging.json'
        path.write_text(json.dumps(CONFIG))
        assert settings.load_settings(path) == CONFIG
        for field, bad in [('bridge_token', 'short'), ('sender_number', '15555550100'),
                           ('opted_in_recipients', []), ('sender_number', '+15555550101'),
                           ('account_sid', 'invalid'), ('webhook_url', 'http://relay.example/webhooks/twilio')]:
            path.write_text(json.dumps({**CONFIG, field: bad}))
            with pytest.raises(ValueError):
                settings.load_settings(path)


def test_whatsapp_requires_approved_template():
    config = {**CONFIG, 'provider': 'twilio-whatsapp'}
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, FAMILY_MESSAGING_PROVIDER='twilio-whatsapp'):
        path = Path(tmp) / 'messaging.json'
        path.write_text(json.dumps(config))
        with pytest.raises(ValueError, match='content_sid'):
            settings.load_settings(path)
        path.write_text(json.dumps({**config, 'content_sid': 'HX' + '3' * 32}))
        assert settings.load_settings(path)['provider'] == 'twilio-whatsapp'


def test_nonconsenting_recipient_is_not_sent():
    with patch('twilio.rest.Client') as client:
        assert worker.deliver(CONFIG, {**ALERT, 'imessage_handle': '+915555550101'}) == 'failed'
        client.assert_not_called()


def test_sms_and_whatsapp_use_separate_payload_formats():
    with patch('twilio.rest.Client') as client:
        client.return_value.messages.create.return_value.sid = 'SM123'
        assert worker.deliver(CONFIG, ALERT) == 'sent'
        assert client.return_value.messages.create.call_args.kwargs['body'] == 'Bring a jacket'
        client.return_value.messages.create.return_value.status = 'failed'
        assert worker.deliver(CONFIG, ALERT) == 'failed'
        client.return_value.messages.create.return_value.status = 'queued'
        wa = {**CONFIG, 'provider': 'twilio-whatsapp', 'content_sid': 'HX' + '3' * 32,
              'content_variables': {'1': '{member_name}', '2': '{message}'}}
        assert worker.deliver(wa, ALERT) == 'sent'
        fields = client.return_value.messages.create.call_args.kwargs
        assert fields['to'] == 'whatsapp:+15555550101'
        assert 'body' not in fields
        assert json.loads(fields['content_variables']) == {'1': 'Alex', '2': 'Bring a jacket'}


def test_uncertain_provider_outcomes_are_never_marked_retryable():
    with patch('twilio.rest.Client') as client:
        for error, expected in [(TimeoutError(), 'uncertain'),
                                (TwilioRestException(503, 'test'), 'uncertain'),
                                (TwilioRestException(400, 'test'), 'failed')]:
            client.return_value.messages.create.side_effect = error
            assert worker.deliver(CONFIG, ALERT) == expected


def test_openclaw_uses_explicit_account_and_argument_list_without_shell():
    oc = {**CONFIG, 'provider': 'openclaw', 'openclaw_account': 'family'}
    with patch.object(worker.shutil, 'which', return_value='/usr/bin/openclaw'), patch.object(worker.subprocess, 'run') as run:
        run.return_value.returncode = 0
        assert worker.deliver(oc, {**ALERT, 'message': '$(do not execute)'}) == 'sent'
        command = run.call_args.args[0]
        assert command[command.index('--account') + 1] == 'family'
        assert command[command.index('--message') + 1] == '$(do not execute)'
        assert 'shell' not in run.call_args.kwargs
        run.side_effect = subprocess.TimeoutExpired(command, 45)
        assert worker.deliver(oc, ALERT) == 'uncertain'


def test_worker_reports_completion_once_and_stops_on_lost_ack():
    with patch.object(worker, 'api') as api, patch.object(worker, 'deliver', return_value='sent') as deliver:
        api.side_effect = [{}, {}, ALERT, ConnectionError()]
        with pytest.raises(ConnectionError):
            worker.run_once(CONFIG)
        deliver.assert_called_once()
        assert api.call_args.args[1] == '/alerts/1/sent'


def fields():
    return {'From': '+15555550101', 'To': CONFIG['sender_number'], 'AccountSid': CONFIG['account_sid'],
            'MessageSid': 'SM' + '4' * 32, 'Body': 'FA bring milk'}


def signed_post(client, data):
    signature = RequestValidator(CONFIG['auth_token']).compute_signature(CONFIG['webhook_url'], data)
    return client.post('/webhooks/twilio', data=data, headers={'X-Twilio-Signature': signature})


def test_signed_webhook_forwards_only_expected_account_number_and_fa_messages():
    client = TestClient(gateway.app)
    with patch.object(gateway, 'load_settings', return_value=CONFIG), patch.object(gateway, 'api') as api:
        assert signed_post(client, fields()).status_code == 200
        assert api.call_args.args[2]['message_guid'].startswith('twilio-sms:SM')
        api.reset_mock()
        for change in [{'Body': 'personal conversation'}, {'From': '+15555550999'}]:
            assert signed_post(client, {**fields(), **change}).status_code == 200
        api.assert_not_called()
        for change in [{'To': '+15555550999'}, {'AccountSid': 'AC' + '9' * 32}]:
            assert signed_post(client, {**fields(), **change}).status_code == 403


def test_invalid_signatures_and_oversized_webhooks_never_reach_api():
    client = TestClient(gateway.app)
    with patch.object(gateway, 'load_settings', return_value=CONFIG), patch.object(gateway, 'api') as api:
        assert client.post('/webhooks/twilio', data=fields()).status_code == 403
        assert client.post('/webhooks/twilio', content='a' * 20000,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 413
        api.assert_not_called()


def test_openclaw_requires_token_account_and_allowlisted_number():
    client = TestClient(gateway.app)
    config = {**CONFIG, 'provider': 'openclaw', 'openclaw_account': 'family'}
    data = {'account_id': 'family', 'sender': '+15555550101', 'text': 'FA test', 'message_id': 'stable-id'}
    with patch.object(gateway, 'load_settings', return_value=config), patch.object(gateway, 'api') as api:
        assert client.post('/webhooks/openclaw', json=data).status_code == 403
        headers = {'Authorization': 'Bearer ' + config['bridge_token']}
        assert client.post('/webhooks/openclaw', json={**data, 'account_id': 'personal'}, headers=headers).status_code == 403
        api.assert_not_called()
        assert client.post('/webhooks/openclaw', json=data, headers=headers).status_code == 200
        assert api.call_args.args[2]['message_guid'] == 'openclaw:stable-id'


def test_imessage_worker_cannot_claim_remote_transport_alerts():
    with patch.dict(os.environ, FAMILY_MESSAGING_PROVIDER='twilio-sms'):
        database = MagicMock()
        with pytest.raises(HTTPException) as error:
            claim_due_alert(database)
        assert error.value.status_code == 409
        database.scalar.assert_not_called()


def test_remote_inbox_requires_auth_and_preserves_existing_review_path():
    payload = ConciergeInboxRequest(sender_handle='+15555550101', text='FA test', message_guid='twilio-sms:test')
    with patch.object(settings, 'load_settings', return_value=CONFIG), patch('main.receive_concierge_imessage', return_value={'status': 'planned'}) as receive:
        with pytest.raises(HTTPException):
            receive_remote_message(payload, MagicMock())
        assert receive_remote_message(payload, MagicMock(), 'Bearer ' + CONFIG['bridge_token']) == {'status': 'planned'}
        receive.assert_called_once()
