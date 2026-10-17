import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from Monitoring.settings import MonitoringSettings, validate_percent


class MonitoringSettingsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_uses_defaults_when_no_file_exists_yet(self):
        settings = MonitoringSettings(20, 20)
        self.assertEqual(settings.get_ram_percent(), 20)
        self.assertEqual(settings.get_storage_percent(), 20)

    def test_set_thresholds_persists_across_instances(self):
        settings = MonitoringSettings(20, 20)
        settings.set_thresholds(15, 10)

        reloaded = MonitoringSettings(20, 20)  # simulates a reboot
        self.assertEqual(reloaded.get_ram_percent(), 15)
        self.assertEqual(reloaded.get_storage_percent(), 10)


class ValidatePercentTests(unittest.TestCase):
    def test_non_numeric_value_is_rejected(self):
        error, value = validate_percent("abc")
        self.assertIsNotNone(error)
        self.assertIsNone(value)

    def test_none_value_is_rejected(self):
        error, value = validate_percent(None)
        self.assertIsNotNone(error)

    def test_value_below_minimum_is_rejected(self):
        error, value = validate_percent("1")
        self.assertIsNotNone(error)

    def test_value_above_maximum_is_rejected(self):
        error, value = validate_percent("99")
        self.assertIsNotNone(error)

    def test_value_within_range_is_accepted(self):
        error, value = validate_percent("20")
        self.assertIsNone(error)
        self.assertEqual(value, 20.0)


if __name__ == "__main__":
    unittest.main()
