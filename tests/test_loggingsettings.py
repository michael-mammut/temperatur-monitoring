import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.errorlog import ALL_CATEGORIES, CATEGORY_HARDWARE, CATEGORY_NETWORK
from WebServer.loggingsettings import LoggingSettings


class LoggingSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_all_categories_enabled_by_default(self):
        settings = LoggingSettings()
        for category in ALL_CATEGORIES:
            self.assertTrue(settings.is_enabled(category))

    def test_set_enabled_disables_only_the_given_category(self):
        settings = LoggingSettings()
        settings.set_enabled({CATEGORY_HARDWARE: False})

        self.assertFalse(settings.is_enabled(CATEGORY_HARDWARE))
        self.assertTrue(settings.is_enabled(CATEGORY_NETWORK))

    def test_setting_persists_across_instances(self):
        settings = LoggingSettings()
        settings.set_enabled({CATEGORY_HARDWARE: False})

        reloaded = LoggingSettings()  # simulates a reboot
        self.assertFalse(reloaded.is_enabled(CATEGORY_HARDWARE))
        self.assertTrue(reloaded.is_enabled(CATEGORY_NETWORK))

    def test_can_be_re_enabled(self):
        settings = LoggingSettings()
        settings.set_enabled({CATEGORY_HARDWARE: False})
        settings.set_enabled({CATEGORY_HARDWARE: True})

        self.assertTrue(settings.is_enabled(CATEGORY_HARDWARE))


if __name__ == "__main__":
    unittest.main()
