"""Exercise real HTTP authentication with synthetic data and temporary keys."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import auth_service as auth


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(auth, 'CONFIG', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, FAMILY_MESSAGING_PROVIDER='imessage')
        environment.start()
        self.addCleanup(environment.stop)
        auth.initialize_keys()
        self.admin, self.worker = auth.read_key(), auth.read_key('worker')
        app = FastAPI()
        app.add_middleware(auth.AuthenticationMiddleware)
        app.include_router(auth.router)
        @app.get('/health')
        def health():
            return {'status': 'ok'}
        @app.get('/alerts/contacts')
        def contacts():
            return {'contact': 'synthetic@example.com'}
        @app.post('/tasks')
        def tasks():
            return {'created': True}
        @app.post('/alerts/claim')
        def claim():
            return {'id': 1}
        @app.post('/messaging/inbox')
        def inbox():
            return {'status': 'planned'}
        @app.get('/health/database')
        def db_health():
            return {'status': 'ok'}
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def login(self):
        return self.client.post('/auth/session', json={'token': self.admin}, headers={'Origin': 'http://testserver'})

    def test_unauthenticated_contacts_and_writes_are_rejected(self):
        response = self.client.get('/alerts/contacts')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('synthetic@example.com', response.text)
        self.assertEqual(self.client.post('/tasks').status_code, 401)
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/dashboard', follow_redirects=False).headers['location'], '/login')

    def test_admin_can_read_with_bearer_without_exposing_credential(self):
        response = self.client.get('/alerts/contacts', headers={'Authorization': 'Bearer ' + self.admin})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn(self.admin, response.text)

    def test_worker_is_not_an_admin(self):
        headers = {'Authorization': 'Bearer ' + self.worker}
        self.assertEqual(self.client.get('/alerts/contacts', headers=headers).status_code, 403)
        self.assertEqual(self.client.post('/tasks', headers=headers).status_code, 403)
        self.assertEqual(self.client.post('/alerts/claim', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/health/database', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/openapi.json', headers=headers).status_code, 403)

    def test_browser_session_and_csrf_boundary(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=strict', response.headers['set-cookie'])
        self.assertEqual(self.client.get('/alerts/contacts').status_code, 200)
        self.assertEqual(self.client.post('/tasks').status_code, 403)
        self.assertEqual(self.client.post('/tasks', headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/tasks', headers={'Origin': 'http://testserver'}).status_code, 200)

    def test_login_rejects_wrong_secret_worker_key_and_cross_origin(self):
        for token in ['wrong', self.worker]:
            self.assertEqual(self.client.post('/auth/session', json={'token': token}, headers={'Origin': 'http://testserver'}).status_code, 401)
        self.assertEqual(self.client.post('/auth/session', json={'token': self.admin}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/auth/session', content='x' * 2048, headers={'Origin': 'http://testserver'}).status_code, 413)

    def test_expired_tampered_and_rotated_sessions_fail(self):
        value = auth.session_value()
        self.assertTrue(auth.valid_session(value))
        self.assertFalse(auth.valid_session(value[:-1] + ('a' if value[-1] != 'a' else 'b')))
        with patch.object(auth.time, 'time', return_value=auth.time.time() + auth.SESSION_SECONDS + 1):
            self.assertFalse(auth.valid_session(value))
        auth.key_path().write_text('z' * 43)
        self.assertFalse(auth.valid_session(value))

    def test_logout_clears_browser_cookie(self):
        self.login()
        self.assertEqual(self.client.post('/auth/logout', headers={'Origin': 'http://testserver'}).status_code, 200)
        self.assertEqual(self.client.get('/alerts/contacts').status_code, 401)

    def test_keys_are_private_and_persist_across_startups(self):
        self.assertEqual(auth.key_path().stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(self.admin, self.worker)
        auth.initialize_keys()
        self.assertEqual(auth.read_key(), self.admin)

    def test_remote_worker_has_only_messaging_scope(self):
        token = 'remote-token-' + 'b' * 40
        with patch('messaging_settings.provider', return_value='twilio-sms'), patch('messaging_settings.load_settings', return_value={'bridge_token': token}):
            headers = {'Authorization': 'Bearer ' + token}
            self.assertEqual(self.client.post('/alerts/claim', headers=headers).status_code, 200)
            self.assertEqual(self.client.post('/messaging/inbox', headers=headers).status_code, 200)
            self.assertEqual(self.client.get('/alerts/contacts', headers=headers).status_code, 403)
            self.assertEqual(self.client.post('/tasks', headers=headers).status_code, 403)
            self.assertEqual(self.client.post('/alerts/claim', headers={'Authorization': 'Bearer ' + self.worker}).status_code, 401)

    def test_https_login_sets_secure_cookie(self):
        response = self.client.post('https://testserver/auth/session', json={'token': self.admin}, headers={'Origin':'https://testserver'})
        self.assertIn('Secure', response.headers['set-cookie'])

    def test_local_worker_sends_only_scoped_key(self):
        import io
        from macos import imessage_worker, self_healing
        headers = {'Authorization': 'Bearer synthetic-worker-credential'}
        with patch.object(imessage_worker, 'worker_headers', return_value=headers), patch.object(imessage_worker.LOCAL_OPENER, 'open', return_value=io.BytesIO(b'{}')) as opened:
            imessage_worker.post('/alerts/claim')
            self.assertEqual(opened.call_args.args[0].get_header('Authorization'), headers['Authorization'])
        with patch.object(self_healing, 'worker_headers', return_value=headers), patch.object(self_healing.LOCAL_OPENER, 'open', return_value=io.BytesIO(b'{}')) as opened:
            self_healing.api_json('/health/database')
            self.assertEqual(opened.call_args.args[0].get_header('Authorization'), headers['Authorization'])
