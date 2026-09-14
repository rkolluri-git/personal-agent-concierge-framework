"""Narrow optional ingress. Never expose the dashboard/API to provider webhooks."""
from contextlib import asynccontextmanager
import hmac
import json
import re
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from twilio.request_validator import RequestValidator

from messaging_settings import allowed_number, load_settings
from messaging_worker import api

@asynccontextmanager
async def lifespan(app):
    if load_settings()['provider'] == 'imessage':
        raise ValueError('The messaging gateway needs an optional provider')
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


async def bounded_body(request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 16384:
            raise HTTPException(413, 'Request too large')
    return bytes(data)


@app.get('/health')
def health():
    return {'status': 'ok'}


def inbound(config, sender, message_id, body):
    if not allowed_number(config, sender) or not isinstance(body, str) or len(body) > 2000:
        return
    if not re.match(r'^\s*FA(?:\s*[:,-]\s*|\s+)\S', body, re.IGNORECASE):
        return
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 150:
        raise HTTPException(400, 'Missing stable message ID')
    # Downstream also requires FA prefix, an enabled saved contact, and deduplicates IDs.
    api(config, '/messaging/inbox', {'sender_handle': sender, 'text': body,
                                   'message_guid': config['provider'] + ':' + message_id})


@app.post('/webhooks/twilio')
async def twilio_inbound(request: Request):
    config = load_settings()
    if not config['provider'].startswith('twilio-'):
        raise HTTPException(404)
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415)
    try:
        parsed = parse_qs((await bounded_body(request)).decode('utf-8'), keep_blank_values=True, max_num_fields=100)
    except (ValueError, UnicodeError):
        raise HTTPException(400) from None
    # Twilio sends single-valued form fields. Reject ambiguous duplicates.
    if any(len(values) != 1 for values in parsed.values()):
        raise HTTPException(400)
    fields = {key: values[0] for key, values in parsed.items()}
    signature = request.headers.get('x-twilio-signature', '')
    if not RequestValidator(config['auth_token']).validate(config['webhook_url'], fields, signature):
        raise HTTPException(403)
    prefix = 'whatsapp:' if config['provider'] == 'twilio-whatsapp' else ''
    if fields.get('AccountSid') != config['account_sid'] or fields.get('To') != prefix + config['sender_number']:
        raise HTTPException(403)
    sender = fields.get('From', '')
    if prefix and not sender.startswith(prefix):
        raise HTTPException(403)
    await run_in_threadpool(inbound, config, sender.removeprefix(prefix) if prefix else sender,
                            fields.get('MessageSid'), fields.get('Body', ''))
    return Response('<Response/>', media_type='application/xml')


@app.post('/webhooks/openclaw')
async def openclaw_inbound(request: Request):
    config = load_settings()
    if config['provider'] != 'openclaw':
        raise HTTPException(404)
    expected = 'Bearer ' + config['bridge_token']
    if not hmac.compare_digest(request.headers.get('authorization', '').encode(), expected.encode()):
        raise HTTPException(403)
    try:
        data = json.loads(await bounded_body(request))
    except (ValueError, UnicodeError):
        raise HTTPException(400) from None
    if not isinstance(data, dict) or data.get('account_id') != config['openclaw_account']:
        raise HTTPException(403)
    await run_in_threadpool(inbound, config, data.get('sender'), data.get('message_id'), data.get('text'))
    return {'status': 'accepted'}
