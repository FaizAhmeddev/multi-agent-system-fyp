"""Authentication boundary regressions without production data or browser flags."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth.persistent_sessions import Account, VerifiedSession
from ui import auth_session


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class AuthenticationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.store = Mock()
        self.ui = SimpleNamespace(session_state=self.state,
            context=SimpleNamespace(cookies={}), error=Mock(), rerun=Mock())
        self.patches = [patch.object(auth_session, 'st', self.ui),
            patch.object(auth_session, 'get_session_store', return_value=self.store)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.verified = VerifiedSession('server-session',
            Account('qa', 'HR Manager', 'QA User', 'fingerprint'), 9999999999)

    def test_session_state_without_cookie_cannot_authorize(self):
        self.state.update(logged_in=True, username='admin', user_role='Admin',
                          private_result='previous account data')
        auth_session.restore_authentication()
        self.assertEqual(self.state, {'logged_in': False})
        self.store.validate.assert_not_called()

    def test_valid_cookie_restores_only_server_identity(self):
        self.ui.context.cookies['office_session'] = 'opaque-token'
        self.store.validate.return_value = self.verified
        self.state.update(logged_in=True, username='admin', user_role='Admin')
        auth_session.restore_authentication()
        self.store.validate.assert_called_once_with('opaque-token')
        self.assertEqual(self.state.username, 'qa')
        self.assertEqual(self.state.user_role, 'HR Manager')
        self.assertEqual(self.state.auth_session_id, 'server-session')

    def test_rejected_cookie_clears_authenticated_workspace(self):
        self.ui.context.cookies['office_session'] = 'expired-or-revoked'
        self.store.validate.return_value = None
        self.state.update(logged_in=True, private_result='sensitive')
        auth_session.restore_authentication()
        self.assertEqual(self.state, {'logged_in': False})

    def test_validation_outage_fails_closed(self):
        self.ui.context.cookies['office_session'] = 'opaque-token'
        self.store.validate.side_effect = RuntimeError('database unavailable')
        self.state.update(logged_in=True, username='qa')
        auth_session.restore_authentication()
        self.assertEqual(self.state, {'logged_in': False})

    def test_different_browser_session_discards_previous_workspace(self):
        self.ui.context.cookies['office_session'] = 'new-token'
        self.store.validate.return_value = self.verified
        self.state.update(logged_in=True, auth_session_id='old-session',
                          private_result='old account result')
        auth_session.restore_authentication()
        self.assertNotIn('private_result', self.state)
        self.assertEqual(self.state.auth_session_id, 'server-session')

    def test_login_does_not_authorize_before_cookie_exchange(self):
        self.store.issue_grant.return_value = 'one-use-grant'
        auth_session.begin_login('qa', 'fixture-password')
        self.store.issue_grant.assert_called_once_with('qa', 'fixture-password')
        self.assertEqual(self.state, {'_auth_login_grant': 'one-use-grant'})
        self.ui.rerun.assert_called_once()

    def test_failed_grant_does_not_start_transition(self):
        self.store.issue_grant.return_value = None
        auth_session.begin_login('qa', 'fixture-password')
        self.assertFalse(self.state)
        self.ui.error.assert_called_once()
        self.ui.rerun.assert_not_called()

    def test_logout_revokes_before_clearing_and_retry_transition(self):
        self.ui.context.cookies['office_session'] = 'opaque-token'
        self.state.update(logged_in=True, private_result='sensitive')
        with patch('auth.http_routes.revoke_browser_session') as revoke:
            revoke.side_effect = lambda token: self.assertTrue(self.state.logged_in)
            auth_session.begin_logout()
            revoke.assert_called_once_with('opaque-token')
        self.assertEqual(self.state, {'_auth_logout_pending': True})
        self.ui.rerun.assert_called_once()


if __name__ == '__main__':
    unittest.main()
