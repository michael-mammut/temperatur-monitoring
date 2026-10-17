import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.datetimeformat import DEFAULT_CULTURE, DEFAULT_UTC_OFFSET_MINUTES
from WebServer.datetimesettings import DEFAULT_EU_SUMMER_TIME, DateTimeSettings


class DateTimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_defaults_to_iso_and_utc(self):
        settings = DateTimeSettings()
        self.assertEqual(settings.get_culture(), DEFAULT_CULTURE)
        self.assertEqual(settings.get_utc_offset_minutes(), DEFAULT_UTC_OFFSET_MINUTES)
        self.assertEqual(settings.get_eu_summer_time(), DEFAULT_EU_SUMMER_TIME)

    def test_set_changes_culture_offset_and_eu_summer_time(self):
        settings = DateTimeSettings()
        settings.set('de_AT', 60, True)
        self.assertEqual(settings.get_culture(), 'de_AT')
        self.assertEqual(settings.get_utc_offset_minutes(), 60)
        self.assertTrue(settings.get_eu_summer_time())

    def test_setting_persists_across_instances(self):
        settings = DateTimeSettings()
        settings.set('en_US', -480, True)

        reloaded = DateTimeSettings()  # simulates a reboot
        self.assertEqual(reloaded.get_culture(), 'en_US')
        self.assertEqual(reloaded.get_utc_offset_minutes(), -480)
        self.assertTrue(reloaded.get_eu_summer_time())

    def test_unknown_culture_is_rejected_and_changes_nothing(self):
        settings = DateTimeSettings()
        with self.assertRaises(ValueError):
            settings.set('not_a_real_culture', 60, False)
        self.assertEqual(settings.get_culture(), DEFAULT_CULTURE)
        self.assertEqual(settings.get_utc_offset_minutes(), DEFAULT_UTC_OFFSET_MINUTES)
        self.assertEqual(settings.get_eu_summer_time(), DEFAULT_EU_SUMMER_TIME)

    def test_unknown_offset_is_rejected_and_changes_nothing(self):
        """Only the fixed, offered offsets are valid - e.g. a made-up
        37-minute offset must not be accepted."""
        settings = DateTimeSettings()
        with self.assertRaises(ValueError):
            settings.set('iso', 37, False)
        self.assertEqual(settings.get_culture(), DEFAULT_CULTURE)
        self.assertEqual(settings.get_utc_offset_minutes(), DEFAULT_UTC_OFFSET_MINUTES)
        self.assertEqual(settings.get_eu_summer_time(), DEFAULT_EU_SUMMER_TIME)

    def test_corrupt_or_stale_stored_culture_falls_back_to_default(self):
        with open('datetime_settings.json', 'w') as f:
            f.write('{"culture": "no_longer_offered", "utc_offset_minutes": 60}')

        settings = DateTimeSettings()
        self.assertEqual(settings.get_culture(), DEFAULT_CULTURE)
        self.assertEqual(settings.get_utc_offset_minutes(), 60)  # still valid, kept independently

    def test_corrupt_or_stale_stored_offset_falls_back_to_default(self):
        with open('datetime_settings.json', 'w') as f:
            f.write('{"culture": "de_AT", "utc_offset_minutes": 37}')

        settings = DateTimeSettings()
        self.assertEqual(settings.get_culture(), 'de_AT')  # still valid, kept independently
        self.assertEqual(settings.get_utc_offset_minutes(), DEFAULT_UTC_OFFSET_MINUTES)

    def test_missing_eu_summer_time_in_stored_file_falls_back_to_default(self):
        """A file written before this setting existed (no 'eu_summer_time'
        key at all) must not break loading."""
        with open('datetime_settings.json', 'w') as f:
            f.write('{"culture": "de_AT", "utc_offset_minutes": 60}')

        settings = DateTimeSettings()
        self.assertEqual(settings.get_eu_summer_time(), DEFAULT_EU_SUMMER_TIME)


if __name__ == "__main__":
    unittest.main()
