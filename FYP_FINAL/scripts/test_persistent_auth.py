"""Persistent session and cookie boundary regressions (isolated SQLite only)."""
from pathlib import Path
import sys
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from starlette.applications import Starlette
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth.persistent_sessions import Account, BrowserSession, LoginGrant, SessionStore, credential_fingerprint
import auth.http_routes as http


class PersistentAuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.accounts = {('qa', 'db'): Account('qa', 'HR Manager', 'QA User', credential_fingerprint('db', 'qa', 'fixture-secret'))}
        self.store = SessionStore(self.engine, lambda user, source: self.accounts.get((user, source)), ttl_seconds=60)

    def tearDown(self):
        self.engine.dispose()

    def session(self, now=1000):
        grant = self.store.issue_grant('qa', 'fixture-secret', now=now)
        return self.store.exchange(grant, now=now)

    def test_opaque_hashed_token_and_server_role(self):
        raw, verified = self.session()
        self.assertEqual(verified.account.role, 'HR Manager')
        self.assertNotEqual(raw, verified.id)
        with self.store._sessions() as db:
            row = db.scalar(select(BrowserSession))
            self.assertNotEqual(row.token_hash, raw)
            self.assertNotIn('fixture-secret', repr(row.__dict__))
        self.assertEqual(self.store.validate(raw, now=1001).account.username, 'qa')
        self.assertIsNone(self.store.validate(raw + 'x', now=1001))

    def test_grants_are_single_use_and_expire(self):
        grant = self.store.issue_grant('qa', 'fixture-secret', now=1000)
        self.assertIsNotNone(self.store.exchange(grant, now=1001))
        self.assertIsNone(self.store.exchange(grant, now=1001))
        other = self.store.issue_grant('qa', 'fixture-secret', now=1000)
        self.assertIsNone(self.store.exchange(other, now=1045))

    def test_absolute_expiry_and_revocation(self):
        raw, _ = self.session()
        self.assertIsNone(self.store.validate(raw, now=1060))
        raw, _ = self.session(now=1100)
        self.assertTrue(self.store.revoke(raw, now=1101))
        self.assertFalse(self.store.revoke(raw, now=1102))
        self.assertIsNone(self.store.validate(raw, now=1102))

    def test_password_change_and_account_removal_reject_sessions(self):
        raw, _ = self.session()
        self.accounts[('qa', 'db')] = Account('qa', 'HR Manager', 'QA User', credential_fingerprint('db', 'qa', 'changed'))
        self.assertIsNone(self.store.validate(raw, now=1001))
        grant = self.store.issue_grant('qa', 'changed', now=1002)
        raw, _ = self.store.exchange(grant, now=1002)
        self.accounts.clear()
        self.assertIsNone(self.store.validate(raw, now=1003))

    def test_roles_are_loaded_fresh_and_credential_source_is_bound(self):
        raw, _ = self.session()
        fingerprint = self.accounts[('qa', 'db')].credential_fingerprint
        self.accounts[('qa', 'db')] = Account('qa', 'Employee', 'Renamed', fingerprint)
        self.assertEqual(self.store.validate(raw, now=1001).account.role, 'Employee')
        self.accounts[('qa', 'config')] = Account('qa', 'IT Staff', 'System User', credential_fingerprint('config', 'qa', 'config-secret'))
        grant = self.store.issue_grant('qa', 'config-secret', now=1002)
        raw, _ = self.store.exchange(grant, now=1002)
        self.assertEqual(self.store.validate(raw, now=1003).account.role, 'IT Staff')

    def test_login_rotation_revokes_previous_cookie(self):
        old, _ = self.session()
        grant = self.store.issue_grant('qa', 'fixture-secret', now=1001)
        new, _ = self.store.exchange(grant, previous_token=old, now=1001)
        self.assertIsNone(self.store.validate(old, now=1002))
        self.assertIsNotNone(self.store.validate(new, now=1002))

    def test_concurrent_grant_exchange_is_single_use(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = create_engine('sqlite:///' + str(Path(folder) / 'auth.db'), connect_args={'check_same_thread': False})
            store = SessionStore(engine, lambda user, source: self.accounts.get((user, source)))
            grant = store.issue_grant('qa', 'fixture-secret')
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: store.exchange(grant), range(2)))
            self.assertEqual(sum(result is not None for result in results), 1)
            engine.dispose()

    def client(self, https=False):
        return TestClient(Starlette(routes=http.auth_routes()), base_url=('https' if https else 'http') + '://localhost')

    def nonce(self, client):
        response = client.get('/_office/auth/nonce')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        return {'Origin': str(client.base_url).rstrip('/'), 'X-Office-CSRF': response.json()['csrf']}

    def test_http_cookie_flags_and_client_claims_ignored(self):
        with patch.object(http, 'get_session_store', return_value=self.store), patch.object(http, '_record_login'):
            for https in (False, True):
                with self.client(https) as client:
                    headers = self.nonce(client)
                    grant = self.store.issue_grant('qa', 'fixture-secret')
                    response = client.post('/_office/auth/handshake', json={'grant': grant, 'username': 'admin', 'role': 'Admin'}, headers=headers)
                    self.assertEqual(response.status_code, 200)
                    cookie = response.headers['set-cookie'].lower()
                    self.assertIn('httponly', cookie)
                    self.assertIn('samesite=lax', cookie)
                    self.assertIn('expires=', cookie)
                    self.assertIn('max-age=', cookie)
                    self.assertNotIn('domain=', cookie)
                    self.assertEqual('; secure' in cookie, https)
                    token = client.cookies.get('office_session')
                    self.assertNotIn(token, response.text)
                    self.assertEqual(self.store.validate(token).account.role, 'HR Manager')
                    replay = client.post('/_office/auth/handshake', json={'grant': grant}, headers=headers)
                    self.assertEqual(replay.status_code, 401)

    def test_http_rejects_cross_origin_missing_csrf_and_forged_tokens(self):
        with patch.object(http, 'get_session_store', return_value=self.store), patch.object(http, '_record_login'):
            with self.client() as client:
                self.assertEqual(client.post('/_office/auth/handshake', json={'grant': 'fake'}).status_code, 403)
                headers = self.nonce(client)
                bad = dict(headers, Origin='https://attacker.example')
                self.assertEqual(client.post('/_office/auth/handshake', json={'grant': 'fake'}, headers=bad).status_code, 403)
                self.assertEqual(client.post('/_office/auth/handshake', json={'grant': 'fake'}, headers=headers).status_code, 401)
                self.assertEqual(client.get('/_office/auth/nonce', headers={'Origin': 'https://attacker.example'}).status_code, 403)
                self.assertEqual(client.get('/_office/auth/logout').status_code, 405)

    def test_logout_revokes_session_and_deletes_cookie(self):
        with patch.object(http, 'get_session_store', return_value=self.store), patch.object(http, '_record_login'), patch.object(http, '_record_logout'):
            with self.client() as client:
                headers = self.nonce(client)
                grant = self.store.issue_grant('qa', 'fixture-secret')
                client.post('/_office/auth/handshake', json={'grant': grant}, headers=headers)
                token = client.cookies.get('office_session')
                response = client.post('/_office/auth/logout', json={}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertIn('max-age=0', response.headers.get_list('set-cookie')[0].lower())
                self.assertIsNone(self.store.validate(token))
                self.assertIsNone(client.cookies.get('office_session'))

    def test_tls_proxy_origin_requires_secure_cookies(self):
        with patch.dict(os.environ, {'FYP_PUBLIC_ORIGIN': 'https://office.example.com'}):
            with self.client() as client:
                response = client.get('/_office/auth/nonce',
                    headers={'Origin': 'https://office.example.com'})
                self.assertEqual(response.status_code, 200)
                self.assertIn('; Secure', response.headers['set-cookie'])
                denied = client.get('/_office/auth/nonce',
                    headers={'Origin': 'http://localhost'})
                self.assertEqual(denied.status_code, 403)

    def test_auth_routes_support_configured_base_path(self):
        app = Starlette(routes=http.auth_routes('office'))
        with TestClient(app, base_url='https://localhost') as client:
            response = client.get('/office/_office/auth/nonce')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get('/_office/auth/nonce').status_code, 404)
            headers = {'Origin': 'https://localhost',
                       'X-Office-CSRF': response.json()['csrf']}
            with patch.object(http, 'get_session_store', return_value=self.store), patch.object(http, '_record_login'):
                grant = self.store.issue_grant('qa', 'fixture-secret')
                result = client.post('/office/_office/auth/handshake',
                    json={'grant': grant}, headers=headers)
                self.assertEqual(result.status_code, 200)


if __name__ == '__main__':
    unittest.main()
