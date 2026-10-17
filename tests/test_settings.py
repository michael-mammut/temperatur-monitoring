import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.settings import Settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_uses_default_when_no_file_exists_yet(self):
        settings = Settings("Vorzimmer")
        self.assertEqual(settings.get_name(), "Vorzimmer")

    def test_set_name_persists_across_instances(self):
        """Regression target: a name change via the /settings page must
        survive a reboot, not just live in memory until power loss."""
        settings = Settings("Vorzimmer")
        settings.set_name("Wohnzimmer")

        reloaded = Settings("Vorzimmer")  # simulates a fresh boot
        self.assertEqual(reloaded.get_name(), "Wohnzimmer")

    def test_set_name_handles_umlauts(self):
        settings = Settings("Vorzimmer")
        settings.set_name("Büro-Aquarium")

        reloaded = Settings("Vorzimmer")
        self.assertEqual(reloaded.get_name(), "Büro-Aquarium")


if __name__ == "__main__":
    unittest.main()
