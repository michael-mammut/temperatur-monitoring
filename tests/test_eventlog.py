import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.eventlog import EventLog, enforce_storage_budget


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


class FileSizeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_empty_log_has_zero_size(self):
        log = EventLog('events.json')
        self.assertEqual(log.file_size(), 0)

    def test_size_grows_after_recording(self):
        log = EventLog('events.json')
        log.record({'code': 'X', 'message': 'something happened'})
        self.assertGreater(log.file_size(), 0)


class DeleteOlderThanTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_removes_only_entries_older_than_given_seconds(self):
        log = EventLog('events.json')
        with patch("WebServer.eventlog.time.time", return_value=1000.0):
            log.record({'code': 'old'})
        with patch("WebServer.eventlog.time.time", return_value=1000.0 + 3600):
            log.record({'code': 'recent'})
            removed = log.delete_older_than(1800)  # 30 minutes

        self.assertEqual(removed, 1)
        remaining = log.entries_within(10 ** 12)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['code'], 'recent')

    def test_persists_the_deletion(self):
        log = EventLog('events.json')
        with patch("WebServer.eventlog.time.time", return_value=1000.0):
            log.record({'code': 'old'})
        with patch("WebServer.eventlog.time.time", return_value=1000.0 + 3600):
            log.delete_older_than(1800)

        reloaded = EventLog('events.json')
        self.assertEqual(reloaded.count_within(10 ** 12), 0)

    def test_nothing_removed_returns_zero(self):
        log = EventLog('events.json')
        log.record({'code': 'fresh'})
        self.assertEqual(log.delete_older_than(10 ** 9), 0)


class EnforceStorageBudgetTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_does_nothing_when_under_budget(self):
        log = EventLog('events.json')
        log.record({'code': 'X'})
        size_before = log.file_size()

        enforce_storage_budget([log], max_percent=50, free_bytes=10 ** 9)

        self.assertEqual(log.file_size(), size_before)

    def test_trims_oldest_entries_when_over_budget(self):
        """Regression target: 'logs should take up at most N% of the
        available headroom' - a log that grew past its budget must
        shrink, oldest entries first, until it fits again."""
        log = EventLog('events.json')
        for i in range(50):
            log.record({'code': str(i), 'message': 'padding' * 5})

        # Solve for the percent (from the actually measured size) that
        # makes the budget exactly half the current size, forcing
        # meaningful but not complete trimming - independent of exact
        # JSON serialization overhead.
        size_before = log.file_size()
        desired_overshoot = size_before / 2
        free_bytes = size_before  # arbitrary baseline; max_percent is solved below
        headroom = free_bytes + size_before
        max_percent = (size_before - desired_overshoot) / headroom * 100

        enforce_storage_budget([log], max_percent=max_percent, free_bytes=free_bytes)

        remaining = log.entries_within(10 ** 12)
        self.assertGreater(len(remaining), 0)
        self.assertLess(len(remaining), 50)
        # newest entries must survive, oldest got dropped
        self.assertEqual(remaining[-1]['code'], '49')

    def test_shrinking_free_space_shrinks_the_allowed_log_footprint(self):
        """This is the whole point of basing the budget on headroom
        instead of total capacity: if free space drops (e.g. other, non-
        log data grew), the log budget must shrink too, instead of still
        allowing a fixed share of total capacity that may no longer
        actually be free."""
        log = EventLog('events.json')
        for i in range(50):
            log.record({'code': str(i), 'message': 'padding' * 5})
        size_before = log.file_size()

        # Plenty of free space -> well under budget, nothing trimmed.
        enforce_storage_budget([log], max_percent=10, free_bytes=size_before * 100)
        self.assertEqual(log.file_size(), size_before)

        # Free space has collapsed (as if something else filled the
        # flash) -> the same log, same percentage, now gets trimmed.
        enforce_storage_budget([log], max_percent=10, free_bytes=0)
        self.assertLess(log.file_size(), size_before)

    def test_largest_log_is_trimmed_first_across_several_logs(self):
        small_log = EventLog('small.json')
        small_log.record({'code': 'only-one'})

        big_log = EventLog('big.json')
        for i in range(50):
            big_log.record({'code': str(i), 'message': 'padding' * 5})

        # Pick a budget that is only slightly below the combined size, so
        # trimming a couple of entries off the big log alone covers it -
        # computed from the actually measured sizes rather than a guessed
        # byte count, so this doesn't depend on exact JSON overhead.
        combined = small_log.file_size() + big_log.file_size()
        free_bytes = combined * 100
        desired_overshoot = 50
        headroom = free_bytes + combined
        max_percent = (combined - desired_overshoot) / headroom * 100

        enforce_storage_budget([small_log, big_log], max_percent=max_percent, free_bytes=free_bytes)

        # the small log should be left alone since trimming the big one a
        # little is enough to get under budget
        self.assertEqual(small_log.count_within(10 ** 12), 1)
        self.assertLess(big_log.count_within(10 ** 12), 50)


if __name__ == "__main__":
    unittest.main()
