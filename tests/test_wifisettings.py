import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WlanNetwork.wifisettings import WifiSettings, validate_password, validate_ssid


class WifiSettingsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_uses_defaults_when_no_file_exists_yet(self):
        settings = WifiSettings("DefaultSSID", "DefaultPassword")
        self.assertEqual(settings.get_ssid(), "DefaultSSID")
        self.assertEqual(settings.get_password(), "DefaultPassword")

    def test_set_credentials_persists_across_instances(self):
        settings = WifiSettings("DefaultSSID", "DefaultPassword")
        settings.set_credentials("NewNetwork", "NewPassword123")

        reloaded = WifiSettings("DefaultSSID", "DefaultPassword")  # simulates a reboot
        self.assertEqual(reloaded.get_ssid(), "NewNetwork")
        self.assertEqual(reloaded.get_password(), "NewPassword123")


class ValidateSsidTests(unittest.TestCase):
    def test_empty_ssid_is_rejected(self):
        self.assertIsNotNone(validate_ssid(""))

    def test_ssid_longer_than_32_bytes_is_rejected(self):
        self.assertIsNotNone(validate_ssid("x" * 33))

    def test_ssid_at_32_bytes_is_accepted(self):
        self.assertIsNone(validate_ssid("x" * 32))

    def test_normal_ssid_is_accepted(self):
        self.assertIsNone(validate_ssid("FRITZ!Box 4050 IQ"))

    def test_multibyte_ssid_is_measured_in_bytes_not_characters(self):
        """A 32-character SSID full of 2-byte UTF-8 characters is 64 bytes
        on the wire - must be rejected by byte length, not character count
        (the same class of bug fixed earlier in the Telegram client)."""
        ssid = "ö" * 32  # 32 chars, 64 UTF-8 bytes
        self.assertIsNotNone(validate_ssid(ssid))


class ValidatePasswordTests(unittest.TestCase):
    def test_empty_password_is_allowed_for_open_networks(self):
        self.assertIsNone(validate_password(""))

    def test_password_shorter_than_8_is_rejected(self):
        self.assertIsNotNone(validate_password("short"))

    def test_password_longer_than_63_is_rejected(self):
        self.assertIsNotNone(validate_password("x" * 64))

    def test_password_within_range_is_accepted(self):
        self.assertIsNone(validate_password("a-valid-password"))


if __name__ == "__main__":
    unittest.main()
