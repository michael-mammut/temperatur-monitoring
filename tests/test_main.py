import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

import aquarium as main


def _patch_hardware():
    """Replaces every hardware/network dependency of main.py with mocks so
    AquariumMonitor / main() can run under plain CPython."""
    return [
        patch("aquarium.ActorControl", return_value=MagicMock()),
        patch("aquarium.SetupAccessPoint", return_value=MagicMock(has_clients=MagicMock(return_value=False))),
        patch("aquarium.WlanConnection", return_value=MagicMock(isConnected=MagicMock(return_value=True))),
        patch("aquarium.Telegram", return_value=MagicMock(send_aquarium_notification=MagicMock(return_value=0))),
        patch("aquarium.Temperature", side_effect=lambda gpio, **kw: MagicMock(readCurrentAverage=MagicMock(return_value=21.5))),
        patch("aquarium.led_twinkle"),
        patch("aquarium.led_error_twinkle"),
        patch("aquarium.WebServer", return_value=MagicMock(handle_requests=MagicMock())),
    ]


class _IsolatedCwdTestCase(unittest.TestCase):
    """AquariumMonitor() constructs real Settings/WifiSettings/EventLog/
    LoginLog instances that read and write small JSON files in the current
    directory. Running from a throwaway tempdir keeps those out of the
    actual project directory instead of leaving stray *.json files behind."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()


class AquariumMonitorTests(_IsolatedCwdTestCase):
    def test_temperature_sensors_are_created_once_and_reused(self):
        """Regression test: main.py used to instantiate a new Temperature()
        object every 3-second loop iteration, churning the heap until it
        fragmented. Sensors must now be created once in __init__."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()
        temperature_ctor = main.Temperature

        for _ in range(5):
            monitor.run_iteration()

        self.assertEqual(temperature_ctor.call_count, 2)  # ambient + water, created once
        self.assertEqual(monitor.ambient_sensor.readCurrentAverage.call_count, 5)
        self.assertEqual(monitor.water_sensor.readCurrentAverage.call_count, 5)

    def test_notification_sent_when_wlan_connected(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()
        monitor.run_iteration()

        monitor.telegram.send_aquarium_notification.assert_called_once()

    def test_time_sync_is_retried_every_iteration_while_already_connected(self):
        """Regression test: ensure_time_synced() must be invoked from the
        loop itself (not just from connect()), otherwise a one-off NTP
        failure right after connecting left the clock wrong forever."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()
        for _ in range(3):
            monitor.run_iteration()

        self.assertEqual(monitor.wlan.ensure_time_synced.call_count, 3)


class FanControlTests(_IsolatedCwdTestCase):
    def _monitor_with_water_temperature(self, water_temperature):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()
        # ActorControl is patched with one shared mock for all relays; give the
        # fan its own so air-pump/WLAN switching cannot leak into the asserts.
        monitor.pin_K2_12_volt_fan = MagicMock()
        monitor.water_sensor.readCurrentAverage.return_value = water_temperature
        return monitor

    def test_sensor_error_does_not_switch_the_fan(self):
        """Regression test: the SENSOR_ERROR sentinel (-999) is below
        TEMPERATURE_MIN and used to switch the fan on every iteration
        based on a dead sensor instead of a real measurement."""
        monitor = self._monitor_with_water_temperature(main.SENSOR_ERROR)

        monitor.run_iteration()

        monitor.pin_K2_12_volt_fan.on.assert_not_called()
        monitor.pin_K2_12_volt_fan.off.assert_not_called()

    def test_temperature_above_max_switches_fan_off(self):
        monitor = self._monitor_with_water_temperature(main.temperature_config.TEMPERATURE_MAX + 0.5)

        monitor.run_iteration()

        monitor.pin_K2_12_volt_fan.off.assert_called_once()
        monitor.pin_K2_12_volt_fan.on.assert_not_called()

    def test_temperature_below_min_switches_fan_on(self):
        monitor = self._monitor_with_water_temperature(main.temperature_config.TEMPERATURE_MIN - 0.5)

        monitor.run_iteration()

        monitor.pin_K2_12_volt_fan.on.assert_called_once()
        monitor.pin_K2_12_volt_fan.off.assert_not_called()

    def test_temperature_within_range_leaves_fan_unchanged(self):
        monitor = self._monitor_with_water_temperature(
            (main.temperature_config.TEMPERATURE_MIN + main.temperature_config.TEMPERATURE_MAX) / 2)

        monitor.run_iteration()

        monitor.pin_K2_12_volt_fan.on.assert_not_called()
        monitor.pin_K2_12_volt_fan.off.assert_not_called()


class SensorAlertWiringTests(_IsolatedCwdTestCase):
    def test_both_sensors_are_reported_every_iteration(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()
        monitor.sensor_alert = MagicMock()
        monitor.water_sensor.readCurrentAverage.return_value = main.SENSOR_ERROR
        monitor.run_iteration()

        labels = [c.args[0] for c in monitor.sensor_alert.update.call_args_list]
        self.assertEqual(labels, ["Wassersensor", "Umgebungssensor"])
        water_call = monitor.sensor_alert.update.call_args_list[0]
        self.assertEqual(water_call.args[1], main.SENSOR_ERROR)
        self.assertTrue(water_call.args[2])  # online

    def test_sensor_alert_settings_are_passed_to_the_web_server(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        class StopLoop(Exception):
            pass

        with patch("aquarium.WDT"), patch("aquarium._sleep_serving_network_setup", side_effect=StopLoop):
            with self.assertRaises(StopLoop):
                main.main()

        self.assertIn("sensor_alert_settings", main.WebServer.call_args.kwargs)


class NetworkSetupWiringTests(_IsolatedCwdTestCase):
    def _monitor(self, connected):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()
        monitor.network_setup = MagicMock()
        monitor.wlan.isConnected.return_value = connected
        monitor.wlan.connect.return_value = False
        return monitor

    def test_setup_network_active_skips_the_normal_connect(self):
        monitor = self._monitor(connected=False)
        monitor.network_setup.is_active.return_value = True

        monitor.run_iteration()

        monitor.network_setup.update.assert_called_once()
        monitor.wlan.connect.assert_not_called()

    def test_failed_connect_is_reported_for_the_fallback_timer(self):
        monitor = self._monitor(connected=False)
        monitor.network_setup.is_active.return_value = False

        monitor.run_iteration()

        monitor.network_setup.mark_offline.assert_called_once()

    def test_connected_resets_the_fallback_timer(self):
        monitor = self._monitor(connected=True)
        monitor.network_setup.is_active.return_value = False

        monitor.run_iteration()

        monitor.network_setup.mark_online.assert_called_once()

    def test_double_reset_request_is_passed_to_network_setup(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        open('setup_request', 'w').close()

        with patch("aquarium.NetworkSetup") as network_setup_cls:
            main.AquariumMonitor()

        self.assertTrue(network_setup_cls.call_args.kwargs["setup_requested"])
        self.assertFalse(os.path.exists('setup_request'))


class StarterTests(unittest.TestCase):
    def test_starter_packs_the_modules_tightly_while_loading_them(self):
        """Regression test from real hardware (MicroPython 1.16): without
        gc.threshold() while loading, the heap was so fragmented that with
        ~38 KB free not even a 2 KB block was left for a web request."""
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")) as f:
            source = f.read()

        self.assertLess(source.index("gc.threshold(2048)"), source.index("from aquarium import main"))
        self.assertLess(source.index("from aquarium import main"), source.index("gc.threshold(-1)"))
        self.assertTrue(source.rstrip().endswith("main()"))


class LoopExceptionLoggingTests(unittest.TestCase):
    def test_failure_while_logging_does_not_escape(self):
        """Regression test: on real hardware a MemoryError while writing
        the log entry for a failed iteration escaped main() and stopped
        the program until the watchdog reset the board."""
        monitor = MagicMock()
        with patch("aquarium.record_exception", side_effect=MemoryError("memory allocation failed")):
            main._record_loop_exception(monitor, RuntimeError("original"))


class LoopSleepTests(unittest.TestCase):
    def test_sleep_polls_network_setup_in_short_slices(self):
        """One main loop iteration takes several seconds - far too slow
        to answer the setup network's DNS lookups. The loop's sleep must
        keep answering them meanwhile."""
        monitor = MagicMock()
        with patch("aquarium.time.sleep_ms") as sleep_ms:
            main._sleep_serving_network_setup(monitor, 3000)

        self.assertEqual(monitor.network_setup.poll.call_count, 30)
        self.assertEqual(sum(c.args[0] for c in sleep_ms.call_args_list), 3000)


class MainLoopWatchdogTests(_IsolatedCwdTestCase):
    """Regression tests for the missing watchdog: without WDT.feed(), any
    unhandled hang/exception used to require a manual hard reset."""

    def test_watchdog_is_fed_every_iteration(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        class StopLoop(Exception):
            pass

        wdt_instances = []

        def fake_wdt(*args, **kwargs):
            wdt = micropython_mocks.FakeWDT(*args, **kwargs)
            wdt_instances.append(wdt)
            return wdt

        with patch("aquarium.WDT", side_effect=fake_wdt), \
             patch("aquarium._sleep_serving_network_setup", side_effect=[None, None, StopLoop]), \
             patch("aquarium.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        self.assertEqual(len(wdt_instances), 1)
        # 3 iterations: once at the end of each, plus twice inside each
        # (after the WLAN step and before Telegram, see the next test).
        self.assertEqual(wdt_instances[0].feed_count, 9)

    def test_time_sync_after_connecting_gets_its_own_watchdog_window(self):
        """Measured on hardware: waiting for the WLAN (~5 s) plus NTP with
        an unanswered DNS lookup (~7 s) in one step came within ~2 s of the
        15 s watchdog."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        monitor = main.AquariumMonitor()
        calls = []
        monitor.wlan.isConnected.return_value = False
        monitor.wlan.connect.side_effect = lambda: calls.append('connect') or True
        monitor.wlan.ensure_time_synced.side_effect = lambda: calls.append('ntp')
        monitor.feed_watchdog = lambda: calls.append('feed')

        monitor.run_iteration()

        self.assertEqual(calls[:3], ['connect', 'feed', 'ntp'])

    def test_watchdog_is_fed_between_wlan_and_telegram_steps(self):
        """Regression test from real hardware: connecting (~5 s), NTP and a
        Telegram send in the same iteration shared one 15 s watchdog
        window, which a slow network could exceed - each slow step now gets
        its own window."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        monitor = main.AquariumMonitor()
        calls = []
        monitor.feed_watchdog = lambda: calls.append('feed')
        monitor.telegram.send_aquarium_notification.side_effect = lambda *a: calls.append('telegram') or 0
        monitor.wlan.ensure_time_synced.side_effect = lambda: calls.append('wlan')

        monitor.run_iteration()

        self.assertEqual(calls, ['wlan', 'feed', 'feed', 'telegram'])

    def test_web_server_is_served_every_iteration(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        class StopLoop(Exception):
            pass

        with patch("aquarium.WDT", side_effect=micropython_mocks.FakeWDT), \
             patch("aquarium._sleep_serving_network_setup", side_effect=[None, None, StopLoop]), \
             patch("aquarium.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        web_server = main.WebServer.return_value
        self.assertEqual(web_server.handle_requests.call_count, 3)

    def test_status_server_is_wired_with_settings_and_admin_password(self):
        """Regression test: the web server must actually be given the live
        Settings/WifiSettings instances and the admin password, otherwise
        auth silently falls back to a wrong/empty value."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        class StopLoop(Exception):
            pass

        with patch("aquarium.WDT", side_effect=micropython_mocks.FakeWDT), \
             patch("aquarium._sleep_serving_network_setup", side_effect=StopLoop), \
             patch("aquarium.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        args, kwargs = main.WebServer.call_args
        self.assertEqual(args[0], main.webserver_config.PORT)
        self.assertIsInstance(args[1], main.Settings)
        self.assertIsInstance(args[2], main.WifiSettings)
        self.assertEqual(args[3], main.webserver_config.ADMIN_PASSWORD)
        self.assertEqual(kwargs["reset_callback"], main.machine.reset)
        self.assertIsInstance(kwargs["error_log"], main.EventLog)
        self.assertIsInstance(kwargs["notification_log"], main.EventLog)
        self.assertIsInstance(kwargs["login_log"], main.LoginLog)
        self.assertIsInstance(kwargs["monitoring_settings"], main.MonitoringSettings)
        self.assertIsInstance(kwargs["logging_settings"], main.LoggingSettings)
        self.assertIsInstance(kwargs["datetime_settings"], main.DateTimeSettings)

    def test_error_log_is_passed_to_sensors_wlan_and_telegram(self):
        """Regression target: without this wiring, hardware/network/API
        failures would never show up on the /statistics page at all."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        monitor = main.AquariumMonitor()

        self.assertEqual(main.Temperature.call_args_list[0].kwargs["error_log"], monitor.error_log)
        self.assertEqual(main.WlanConnection.call_args.kwargs["error_log"], monitor.error_log)
        self.assertEqual(main.Telegram.call_args.kwargs["error_log"], monitor.error_log)
        self.assertEqual(main.Temperature.call_args_list[0].kwargs["logging_settings"], monitor.logging_settings)
        self.assertEqual(main.WlanConnection.call_args.kwargs["logging_settings"], monitor.logging_settings)
        self.assertEqual(main.Telegram.call_args.kwargs["logging_settings"], monitor.logging_settings)
        self.assertEqual(main.Telegram.call_args.kwargs["notification_log"], monitor.notification_log)

    def test_iteration_exception_does_not_stop_the_loop_and_watchdog_is_still_fed(self):
        """A single failing iteration (e.g. a sensor glitch) must not kill
        the whole script, and the watchdog must still be fed so a real hang
        elsewhere still gets caught."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        class StopLoop(Exception):
            pass

        call_count = {"n": 0}

        def flaky_run_iteration(self):
            call_count["n"] += 1
            raise RuntimeError("sensor glitch")

        wdt_instances = []

        def fake_wdt(*args, **kwargs):
            wdt = micropython_mocks.FakeWDT(*args, **kwargs)
            wdt_instances.append(wdt)
            return wdt

        with patch("aquarium.AquariumMonitor.run_iteration", flaky_run_iteration), \
             patch("aquarium.WDT", side_effect=fake_wdt), \
             patch("aquarium._sleep_serving_network_setup", side_effect=[None, StopLoop]), \
             patch("aquarium.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        self.assertEqual(call_count["n"], 2)  # loop kept going despite the exception
        self.assertEqual(wdt_instances[0].feed_count, 2)  # watchdog still fed each time


class ResourceUsageWarningTests(_IsolatedCwdTestCase):
    """Regression target: a near-exhausted RAM was the root cause of the
    original multi-week-crash bug. An early warning must fire once a
    resource drops below 20% free, without spamming every iteration."""

    def test_threshold_is_read_from_monitoring_settings_not_hardcoded(self):
        """Regression target: the warning threshold must come from
        MonitoringSettings (config.py default, overridable via /settings),
        not a hardcoded module constant."""
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.get_memory_stats", return_value={'used': 60, 'free': 40, 'total': 100}), \
             patch("aquarium.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.monitoring_settings.set_thresholds(ram_percent=50, storage_percent=20, log_storage_percent=15)
            monitor.run_iteration()

        # 40% free is above the hardcoded-default 20% but below the
        # custom 50% threshold that was just configured.
        monitor.telegram.notify.assert_called_once()

    def test_no_notification_when_resources_are_plentiful(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.get_memory_stats", return_value={'used': 20, 'free': 80, 'total': 100}), \
             patch("aquarium.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.run_iteration()

        monitor.telegram.notify.assert_not_called()

    def test_ram_below_20_percent_sends_one_notification(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.get_memory_stats", return_value={'used': 85, 'free': 15, 'total': 100}), \
             patch("aquarium.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.run_iteration()
            monitor.run_iteration()
            monitor.run_iteration()

        monitor.telegram.notify.assert_called_once()
        self.assertIn("RAM", monitor.telegram.notify.call_args[0][0])

    def test_storage_below_20_percent_sends_one_notification(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.get_memory_stats", return_value={'used': 20, 'free': 80, 'total': 100}), \
             patch("aquarium.get_storage_stats", return_value={'used': 85, 'free': 15, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.run_iteration()
            monitor.run_iteration()

        monitor.telegram.notify.assert_called_once()
        self.assertIn("Flash", monitor.telegram.notify.call_args[0][0])

    def test_notification_fires_again_after_recovering_and_dropping_again(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        low = {'used': 85, 'free': 15, 'total': 100}
        healthy = {'used': 20, 'free': 80, 'total': 100}

        with patch("aquarium.get_memory_stats", side_effect=[low, healthy, low]), \
             patch("aquarium.get_storage_stats", return_value=healthy):
            monitor = main.AquariumMonitor()
            monitor.run_iteration()  # low -> notify (1)
            monitor.run_iteration()  # healthy -> flag reset
            monitor.run_iteration()  # low again -> notify (2)

        self.assertEqual(monitor.telegram.notify.call_count, 2)

    def test_resource_check_only_runs_while_wlan_connected(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.get_memory_stats", return_value={'used': 95, 'free': 5, 'total': 100}) as get_memory:
            monitor = main.AquariumMonitor()
            monitor.wlan.isConnected.return_value = False
            monitor.run_iteration()

        get_memory.assert_not_called()
        monitor.telegram.notify.assert_not_called()


class LogStorageBudgetTests(_IsolatedCwdTestCase):
    """Regression target: logs must be kept under their configured share
    of available headroom (not total flash - see WebServer/eventlog.py),
    enforced every iteration regardless of WLAN state (it's pure
    filesystem housekeeping, not something that needs to send anything)."""

    def test_enforced_every_iteration_even_when_wlan_disconnected(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.enforce_storage_budget") as enforce_mock, \
             patch("aquarium.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.wlan.isConnected.return_value = False
            monitor.run_iteration()

        enforce_mock.assert_called_once_with(
            [monitor.error_log, monitor.notification_log],
            monitor.monitoring_settings.get_log_storage_percent(),
            80,  # free, not total - the budget must be based on headroom
        )

    def test_uses_the_configured_percent_not_a_hardcoded_value(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.enforce_storage_budget") as enforce_mock, \
             patch("aquarium.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.monitoring_settings.set_thresholds(ram_percent=20, storage_percent=20, log_storage_percent=7)
            monitor.run_iteration()

        self.assertEqual(enforce_mock.call_args[0][1], 7)

    def test_storage_stats_failure_does_not_crash_the_loop(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("aquarium.get_storage_stats", side_effect=OSError("no filesystem")):
            monitor = main.AquariumMonitor()
            monitor.run_iteration()  # must not raise


if __name__ == "__main__":
    unittest.main()
