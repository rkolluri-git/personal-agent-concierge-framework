"""Single-household administrator authentication with separate worker credentials."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

CONFIG = Path(os.environ.get('CALENDAR_CONFIG_DIR', '/app/config'))
COOKIE = 'personal_agent_session'
SESSION_SECONDS = 12 * 60 * 60
router = APIRouter()


def key_path(kind='admin'):
    return CONFIG / ('api-auth.key' if kind == 'admin' else 'worker-auth.key')


def read_key(kind='admin'):
    key = key_path(kind).read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', key):
        raise ValueError('Invalid local authentication key; restore or rotate it')
    return key


def initialize_keys():
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    for kind in ('admin', 'worker'):
        path = key_path(kind)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            read_key(kind)
        else:
            with os.fdopen(fd, 'w', encoding='ascii') as stream:
                stream.write(secrets.token_urlsafe(32) + '\n')
        path.chmod(0o600)


def matches(value, expected):
    return hmac.compare_digest(value.encode(), expected.encode())


def session_value():
    expires = str(int(time.time()) + SESSION_SECONDS)
    nonce = secrets.token_urlsafe(24)
    payload = expires + '.' + nonce
    signature = hmac.new(read_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + '.' + signature


def valid_session(value):
    try:
        expires, nonce, signature = value.split('.')
        if not int(time.time()) < int(expires) <= int(time.time()) + SESSION_SECONDS or len(nonce) != 32:
            return False
        expected = hmac.new(read_key().encode(), (expires + '.' + nonce).encode(), hashlib.sha256).hexdigest()
        return matches(signature, expected)
    except (ValueError, OSError):
        return False


def same_origin(request):
    origin = request.headers.get('origin')
    if not origin:
        return False
    expected = urlsplit(str(request.base_url))
    actual = urlsplit(origin)
    return (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc) and actual.path in ('', '/')


def worker_allowed(path, method, remote=False):
    if method == 'POST':
        common = {'/alerts/claim', '/alerts/calendar/sync', '/alerts/morning/sync'}
        if path in common or re.fullmatch(r'/alerts/[0-9]+/(sent|failed|uncertain)', path):
            return True
        if remote:
            return path == '/messaging/inbox'
        return path in {'/concierge/inbox', '/commutes/claim', '/traffic/checks/claim', '/departure/traffic/claim'} or bool(re.fullmatch(r'/(?:commutes/runs|traffic/checks)/[0-9]+/complete', path) or re.fullmatch(r'/departure/traffic/[A-Za-z0-9_-]+/complete', path))
    return not remote and method == 'GET' and path in {'/departure/traffic/wake-plan', '/health/database', '/calendar/events', '/weather/forecast', '/commutes/school-calendar'}


def bearer_role(token):
    if matches(token, read_key()):
        return 'admin'
    from messaging_settings import provider, load_settings
    if provider() == 'imessage' and matches(token, read_key('worker')):
        return 'worker'
    if provider() != 'imessage':
        if matches(token, load_settings()['bridge_token']):
            return 'remote-worker'
    return None


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.hostname not in {'localhost', '127.0.0.1', 'testserver', 'family-agent-api'}:
            return JSONResponse({'detail': 'Unrecognized host'}, status_code=400)
        path = request.url.path
        public = (request.method == 'GET' and path in {'/health', '/login', '/static/login.js'}) or path == '/auth/session'
        # A logout operation may only clear the requesting browser's cookie.
        if not public:
            role = None
            authorization = request.headers.get('authorization', '')
            if authorization.startswith('Bearer '):
                try:
                    role = bearer_role(authorization[7:])
                except (OSError, ValueError):
                    return JSONResponse({'detail': 'Authentication is unavailable'}, status_code=503)
            elif valid_session(request.cookies.get(COOKIE, '')):
                if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not same_origin(request):
                    return JSONResponse({'detail': 'Same-origin request required'}, status_code=403)
                role = 'admin'
            if role is None:
                if path == '/dashboard' and request.method == 'GET':
                    return RedirectResponse('/login', status_code=303)
                return JSONResponse({'detail': 'Sign in required'}, status_code=401)
            if role != 'admin' and not worker_allowed(path, request.method, role == 'remote-worker'):
                return JSONResponse({'detail': 'Worker credential cannot access this resource'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        return response


@router.get('/login', include_in_schema=False)
def login_page():
    return FileResponse(Path(__file__).parent / 'static/login.html')


@router.post('/auth/session', include_in_schema=False)
async def login(request: Request):
    if not same_origin(request):
        raise HTTPException(403, 'Same-origin request required')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024:
            raise HTTPException(413, 'Request too large')
    import json
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Invalid login request') from None
    token = payload.get('token') if isinstance(payload, dict) else None
    if not isinstance(token, str) or not matches(token, read_key()):
        raise HTTPException(401, 'Invalid access key')
    response = JSONResponse({'status': 'signed_in'})
    response.set_cookie(COOKIE, session_value(), max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == 'https', samesite='strict', path='/')
    return response


@router.post('/auth/logout', include_in_schema=False)
def logout():
    response = JSONResponse({'status': 'signed_out'})
    response.delete_cookie(COOKIE, path='/')
    return response


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read the local administrator access key; do not share the output.')
    parser.add_argument('--show-key', action='store_true', required=True)
    parser.parse_args()
    print(read_key())
