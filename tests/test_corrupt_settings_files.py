"""Code review findings #2-#4: a corrupt or unexpected JSON file must never
stop the boot. Each class that loads a file in its constructor has to fall
back to its defaults instead - otherwise the board can only be recovered
via USB (no WLAN, no web interface, no setup network)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from Monitoring.sensoralert import SensorAlertSettings
from Monitoring.settings import MonitoringSettings
from WebServer.datetimeformat import DEFAULT_CULTURE, DEFAULT_UTC_OFFSET_MINUTES
from WebServer.datetimesettings import DateTimeSettings
from WebServer.eventlog import EventLog
from WebServer.jsonfile import load_dict
from WebServer.loggingsettings import LoggingSettings
from WebServer.loginlog import LoginLog
from WebServer.settings import Settings
from WlanNetwork.wifisettings import WifiSettings

# Half-written file (power cut while saving), valid JSON of the wrong
# shape, and an empty file.
BROKEN_CONTENTS = ['{"ssid": "Heim', 'null', '[1, 2, 3]', '"text"', '42', '']


class _TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _write(self, path, content):
        with open(path, 'w') as f:
            f.write(content)


class LoadDictTests(_TempDirTestCase):
    def test_returns_the_object(self):
        self._write('x.json', '{"a": 1}')
        self.assertEqual(load_dict('x.json'), {'a': 1})

    def test_missing_file_gives_none(self):
        self.assertIsNone(load_dict('missing.json'))

    def test_broken_or_wrong_shaped_content_gives_none(self):
        for content in BROKEN_CONTENTS:
            self._write('x.json', content)
            self.assertIsNone(load_dict('x.json'), content)


class BrokenFileFallsBackToDefaultsTests(_TempDirTestCase):
    def test_wifi_settings(self):
        """Review #2: wifi_settings.json is written right before the reboot
        that applies new credentials - a real window for a torn write."""
        for content in BROKEN_CONTENTS:
            self._write('wifi_settings.json', content)
            settings = WifiSettings('default-ssid', 'default-pw')
            self.assertEqual((settings.get_ssid(), settings.get_password()), ('default-ssid', 'default-pw'), content)

    def test_aquarium_name(self):
        """Review #3."""
        for content in BROKEN_CONTENTS:
            self._write('aquarium_settings.json', content)
            self.assertEqual(Settings('Vorzimmer').get_name(), 'Vorzimmer', content)

    def test_datetime_settings(self):
        """Review #4: a valid root of the wrong type (e.g. null) raised
        AttributeError despite the existing except clause."""
        for content in BROKEN_CONTENTS:
            self._write('datetime_settings.json', content)
            settings = DateTimeSettings()
            self.assertEqual(settings.get_culture(), DEFAULT_CULTURE, content)
            self.assertEqual(settings.get_utc_offset_minutes(), DEFAULT_UTC_OFFSET_MINUTES, content)

    def test_monitoring_settings(self):
        """Review #4."""
        for content in BROKEN_CONTENTS:
            self._write('monitoring_settings.json', content)
            settings = MonitoringSettings(20, 25, 15)
            self.assertEqual(
                (settings.get_ram_percent(), settings.get_storage_percent(), settings.get_log_storage_percent()),
                (20, 25, 15), content)

    def test_logging_settings(self):
        for content in BROKEN_CONTENTS:
            self._write('logging_settings.json', content)
            self.assertTrue(LoggingSettings().is_enabled('hardware'), content)

    def test_login_log(self):
        for content in BROKEN_CONTENTS:
            self._write('last_login.json', content)
            self.assertIsNone(LoginLog().get_last_login(), content)

    def test_sensor_alert_settings(self):
        for content in BROKEN_CONTENTS:
            self._write('sensor_alert_settings.json', content)
            self.assertTrue(SensorAlertSettings().is_enabled(), content)

    def test_event_log(self):
        for content in BROKEN_CONTENTS:
            self._write('error_log.json', content)
            log = EventLog('error_log.json')
            self.assertEqual(log.count_within(), 0, content)
            log.record({'code': 'X'})  # must still work afterwards
            self.assertEqual(log.count_within(), 1, content)


class WrongValueTypesTests(_TempDirTestCase):
    """A valid object with values of the wrong type would boot fine but
    break later (WLAN connect, RAM check in every loop iteration)."""

    def test_wifi_settings_with_non_string_values(self):
        self._write('wifi_settings.json', '{"ssid": 123, "password": null}')
        settings = WifiSettings('default-ssid', 'default-pw')
        self.assertEqual(settings.get_ssid(), 'default-ssid')

    def test_wifi_settings_keep_an_open_network(self):
        self._write('wifi_settings.json', '{"ssid": "Gast", "password": ""}')
        settings = WifiSettings('default-ssid', 'default-pw')
        self.assertEqual((settings.get_ssid(), settings.get_password()), ('Gast', ''))

    def test_aquarium_name_must_be_a_non_empty_string(self):
        for content in ('{"name": 7}', '{"name": "   "}'):
            self._write('aquarium_settings.json', content)
            self.assertEqual(Settings('Vorzimmer').get_name(), 'Vorzimmer', content)

    def test_monitoring_thresholds_must_be_numbers_in_range(self):
        self._write('monitoring_settings.json', '{"ram_percent": "viel", "storage_percent": 99, "log_storage_percent": 10}')
        settings = MonitoringSettings(20, 25, 15)
        self.assertEqual(settings.get_ram_percent(), 20)
        self.assertEqual(settings.get_storage_percent(), 25)
        self.assertEqual(settings.get_log_storage_percent(), 10)

    def test_summer_time_flag_must_be_a_real_bool(self):
        """bool("false") is True - a string must not switch it on."""
        self._write('datetime_settings.json', '{"eu_summer_time": "false"}')
        self.assertFalse(DateTimeSettings().get_eu_summer_time())

    def test_logging_flag_must_be_a_real_bool(self):
        self._write('logging_settings.json', '{"hardware": "false"}')
        self.assertTrue(LoggingSettings().is_enabled('hardware'))

    def test_event_log_drops_entries_that_are_not_objects(self):
        self._write('error_log.json', '[{"code": "A", "timestamp": 0}, 5, "x", null]')
        self.assertEqual(len(EventLog('error_log.json')._entries), 1)


if __name__ == "__main__":
    unittest.main()
