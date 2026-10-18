import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from Monitoring import sensoralert
from Monitoring.sensoralert import SensorAlert, SensorAlertSettings
from Temperature.temperature import SENSOR_ERROR

_LOOP_MS = 5000  # roughly one main loop iteration


class _SensorAlertTestCase(unittest.TestCase):
    def setUp(self):
        self.now = 0
        p = patch("Monitoring.sensoralert.time.ticks_ms", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)
        self.telegram = MagicMock(_project_name="Vorzimmer")
        self.telegram.notify.return_value = True
        self.settings = MagicMock()
        self.settings.is_enabled.return_value = True
        self.alert = SensorAlert(self.telegram, self.settings)

    def _read(self, value, times=1, online=True):
        for _ in range(times):
            self.alert.update("Wassersensor", value, online, hint=" Hinweis.")
            self.now += _LOOP_MS

    def _messages(self):
        return [c.args[0] for c in self.telegram.notify.call_args_list]

    def _fail(self):
        self._read(SENSOR_ERROR, times=sensoralert.FAILURE_CONFIRM_READINGS)


class FailureTests(_SensorAlertTestCase):
    def test_confirmed_failure_sends_a_warning_immediately(self):
        self._fail()

        self.assertEqual(len(self._messages()), 1)
        self.assertIn("Vorzimmer - Warnung: Wassersensor liefert keine Messwerte", self._messages()[0])
        self.assertIn("Hinweis.", self._messages()[0])

    def test_single_bad_read_is_not_reported(self):
        self._read(SENSOR_ERROR, times=sensoralert.FAILURE_CONFIRM_READINGS - 1)
        self._read(21.5)

        self.telegram.notify.assert_not_called()

    def test_reminder_every_12_hours_while_failed(self):
        self._fail()
        self.now += sensoralert.REMINDER_INTERVAL_MS - 2 * _LOOP_MS
        self._read(SENSOR_ERROR)
        self.assertEqual(len(self._messages()), 1)

        self.now += 2 * _LOOP_MS
        self._read(SENSOR_ERROR)
        self.assertEqual(len(self._messages()), 2)

    def test_warning_is_sent_later_when_offline_at_failure(self):
        self._read(SENSOR_ERROR, times=sensoralert.FAILURE_CONFIRM_READINGS, online=False)
        self.telegram.notify.assert_not_called()

        self._read(SENSOR_ERROR, online=True)
        self.assertEqual(len(self._messages()), 1)

    def test_failed_send_is_retried_after_a_pause_not_every_iteration(self):
        self.telegram.notify.return_value = False
        self._fail()
        self._read(SENSOR_ERROR, times=10)
        self.assertEqual(self.telegram.notify.call_count, 1)

        self.now += sensoralert.RETRY_AFTER_FAILURE_MS
        self.telegram.notify.return_value = True
        self._read(SENSOR_ERROR)
        self.assertEqual(self.telegram.notify.call_count, 2)

    def test_disabled_setting_sends_nothing(self):
        self.settings.is_enabled.return_value = False

        self._fail()

        self.telegram.notify.assert_not_called()

    def test_sensors_are_tracked_independently(self):
        for _ in range(sensoralert.FAILURE_CONFIRM_READINGS):
            self.alert.update("Wassersensor", SENSOR_ERROR, True)
            self.alert.update("Umgebungssensor", 22.0, True)

        self.assertEqual(len(self._messages()), 1)
        self.assertIn("Wassersensor", self._messages()[0])


class RecoveryTests(_SensorAlertTestCase):
    def test_all_clear_after_values_are_stable_again(self):
        self._fail()
        self._read(21.5, times=sensoralert.RECOVERY_STABLE_MS // _LOOP_MS + 1)

        self.assertEqual(len(self._messages()), 2)
        self.assertIn("Vorzimmer - Entwarnung: Wassersensor liefert wieder Messwerte (21.5°C)", self._messages()[1])

    def test_flaky_sensor_does_not_send_all_clear_on_every_good_read(self):
        """A loose connector alternating good and bad reads must not send
        warning + all-clear every few loop iterations."""
        self._fail()
        for _ in range(50):
            self._read(21.5, times=2)
            self._read(SENSOR_ERROR)

        self.assertEqual(len(self._messages()), 1)  # just the first warning

    def test_new_failure_after_recovery_warns_again_immediately(self):
        self._fail()
        self._read(21.5, times=sensoralert.RECOVERY_STABLE_MS // _LOOP_MS + 1)
        self._fail()

        self.assertEqual(len(self._messages()), 3)
        self.assertIn("Warnung", self._messages()[2])

    def test_no_all_clear_if_no_warning_was_sent(self):
        self.settings.is_enabled.return_value = False
        self._fail()
        self.settings.is_enabled.return_value = True
        # setting switched on while the sensor already works again
        self.now += sensoralert.REMINDER_INTERVAL_MS
        self.telegram.notify.reset_mock()
        self.settings.is_enabled.return_value = False
        self._read(21.5, times=sensoralert.RECOVERY_STABLE_MS // _LOOP_MS + 1)
        self.settings.is_enabled.return_value = True
        self._read(21.5)

        self.telegram.notify.assert_not_called()


class SensorAlertSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_enabled_by_default_without_file(self):
        self.assertTrue(SensorAlertSettings().is_enabled())

    def test_setting_persists_across_instances(self):
        SensorAlertSettings().set_enabled(False)

        self.assertFalse(SensorAlertSettings().is_enabled())

    def test_non_bool_is_rejected_and_not_saved(self):
        settings = SensorAlertSettings()
        with self.assertRaises(ValueError):
            settings.set_enabled("no")

        self.assertTrue(SensorAlertSettings().is_enabled())

    def test_corrupt_file_falls_back_to_enabled(self):
        with open('sensor_alert_settings.json', 'w') as f:
            f.write('{not json')

        self.assertTrue(SensorAlertSettings().is_enabled())

    def test_wrong_value_type_in_file_falls_back_to_enabled(self):
        with open('sensor_alert_settings.json', 'w') as f:
            f.write('{"enabled": "false"}')

        self.assertTrue(SensorAlertSettings().is_enabled())

    def test_wrong_root_type_in_file_falls_back_to_enabled(self):
        with open('sensor_alert_settings.json', 'w') as f:
            f.write('[1, 2]')

        self.assertTrue(SensorAlertSettings().is_enabled())


if __name__ == "__main__":
    unittest.main()
