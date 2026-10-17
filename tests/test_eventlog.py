import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.eventlog import EventLog


class EventLogTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_empty_log_has_no_entries(self):
        log = EventLog('events.json')
        self.assertEqual(log.count_within(), 0)

    def test_recorded_entry_is_counted(self):
        log = EventLog('events.json')
        log.record({'code': 'X'})
        self.assertEqual(log.count_within(), 1)

    def test_entries_persist_across_instances(self):
        log = EventLog('events.json')
        log.record({'code': 'A'})
        log.record({'code': 'B'})

        reloaded = EventLog('events.json')  # simulates a reboot
        self.assertEqual(reloaded.count_within(), 2)

    def test_entries_older_than_window_are_excluded(self):
        log = EventLog('events.json')
        with patch("WebServer.eventlog.time.time", return_value=1000.0):
            log.record({'code': 'old'})
        with patch("WebServer.eventlog.time.time", return_value=1000.0 + 40 * 24 * 60 * 60):
            # 40 days later - outside the default 30-day window
            self.assertEqual(log.count_within(30 * 24 * 60 * 60), 0)

    def test_entries_within_window_are_included(self):
        log = EventLog('events.json')
        with patch("WebServer.eventlog.time.time", return_value=1000.0):
            log.record({'code': 'recent'})
        with patch("WebServer.eventlog.time.time", return_value=1000.0 + 5 * 24 * 60 * 60):
            self.assertEqual(log.count_within(30 * 24 * 60 * 60), 1)

    def test_entry_count_is_capped_regardless_of_age(self):
        """Regression target: a crash loop or notification burst must not
        grow the log (and its JSON parse/dump cost) without bound."""
        log = EventLog('events.json')
        for i in range(250):
            log.record({'code': str(i)})

        reloaded = EventLog('events.json')
        self.assertLessEqual(len(reloaded.entries_within(10 ** 12)), 200)


if __name__ == "__main__":
    unittest.main()
