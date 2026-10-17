import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.loginlog import LoginLog


class LoginLogTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_no_login_yet_returns_none(self):
        log = LoginLog()
        self.assertIsNone(log.get_last_login())

    def test_record_login_returns_previous_value_not_the_new_one(self):
        """Regression target: the page showing 'last login' is itself
        loaded via a login - it must show the PREVIOUS login, not the one
        happening right now (which would trivially always say 'just now')."""
        log = LoginLog()
        with patch("WebServer.loginlog.time.time", return_value=1000.0):
            first_previous = log.record_login()
        self.assertIsNone(first_previous)  # no login before the very first one

        with patch("WebServer.loginlog.time.time", return_value=2000.0):
            second_previous = log.record_login()
        self.assertEqual(second_previous, 1000.0)
        self.assertEqual(log.get_last_login(), 2000.0)

    def test_login_persists_across_instances(self):
        log = LoginLog()
        with patch("WebServer.loginlog.time.time", return_value=1234.0):
            log.record_login()

        reloaded = LoginLog()  # simulates a reboot
        self.assertEqual(reloaded.get_last_login(), 1234.0)


if __name__ == "__main__":
    unittest.main()
