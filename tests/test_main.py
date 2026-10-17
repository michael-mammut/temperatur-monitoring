import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

import main


def _patch_hardware():
    """Replaces every hardware/network dependency of main.py with mocks so
    AquariumMonitor / main() can run under plain CPython."""
    return [
        patch("main.ActorControl", return_value=MagicMock()),
        patch("main.WlanConnection", return_value=MagicMock(isConnected=MagicMock(return_value=True))),
        patch("main.Telegram", return_value=MagicMock(send_aquarium_notification=MagicMock(return_value=0))),
        patch("main.Temperature", side_effect=lambda gpio, **kw: MagicMock(readCurrentAverage=MagicMock(return_value=21.5))),
        patch("main.led_twinkle"),
        patch("main.led_error_twinkle"),
        patch("main.StatusServer", return_value=MagicMock(handle_requests=MagicMock())),
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

        with patch("main.WDT", side_effect=fake_wdt), \
             patch("main.time.sleep_ms", side_effect=[None, None, StopLoop]), \
             patch("main.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        self.assertEqual(len(wdt_instances), 1)
        self.assertEqual(wdt_instances[0].feed_count, 3)

    def test_web_server_is_served_every_iteration(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        class StopLoop(Exception):
            pass

        with patch("main.WDT", side_effect=micropython_mocks.FakeWDT), \
             patch("main.time.sleep_ms", side_effect=[None, None, StopLoop]), \
             patch("main.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        web_server = main.StatusServer.return_value
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

        with patch("main.WDT", side_effect=micropython_mocks.FakeWDT), \
             patch("main.time.sleep_ms", side_effect=StopLoop), \
             patch("main.gc.collect"):
            with self.assertRaises(StopLoop):
                main.main()

        args, kwargs = main.StatusServer.call_args
        self.assertEqual(args[0], main.webserver_config.PORT)
        self.assertIsInstance(args[1], main.Settings)
        self.assertIsInstance(args[2], main.WifiSettings)
        self.assertEqual(args[3], main.webserver_config.ADMIN_PASSWORD)
        self.assertEqual(kwargs["reset_callback"], main.machine.reset)
        self.assertIsInstance(kwargs["error_log"], main.EventLog)
        self.assertIsInstance(kwargs["notification_log"], main.EventLog)
        self.assertIsInstance(kwargs["login_log"], main.LoginLog)
        self.assertIsInstance(kwargs["monitoring_settings"], main.MonitoringSettings)

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

        with patch("main.AquariumMonitor.run_iteration", flaky_run_iteration), \
             patch("main.WDT", side_effect=fake_wdt), \
             patch("main.time.sleep_ms", side_effect=[None, StopLoop]), \
             patch("main.gc.collect"):
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

        with patch("main.get_memory_stats", return_value={'used': 60, 'free': 40, 'total': 100}), \
             patch("main.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.monitoring_settings.set_thresholds(ram_percent=50, storage_percent=20)
            monitor.run_iteration()

        # 40% free is above the hardcoded-default 20% but below the
        # custom 50% threshold that was just configured.
        monitor.telegram.notify.assert_called_once()

    def test_no_notification_when_resources_are_plentiful(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("main.get_memory_stats", return_value={'used': 20, 'free': 80, 'total': 100}), \
             patch("main.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
            monitor = main.AquariumMonitor()
            monitor.run_iteration()

        monitor.telegram.notify.assert_not_called()

    def test_ram_below_20_percent_sends_one_notification(self):
        patches = _patch_hardware()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("main.get_memory_stats", return_value={'used': 85, 'free': 15, 'total': 100}), \
             patch("main.get_storage_stats", return_value={'used': 20, 'free': 80, 'total': 100}):
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

        with patch("main.get_memory_stats", return_value={'used': 20, 'free': 80, 'total': 100}), \
             patch("main.get_storage_stats", return_value={'used': 85, 'free': 15, 'total': 100}):
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

        with patch("main.get_memory_stats", side_effect=[low, healthy, low]), \
             patch("main.get_storage_stats", return_value=healthy):
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

        with patch("main.get_memory_stats", return_value={'used': 95, 'free': 5, 'total': 100}) as get_memory:
            monitor = main.AquariumMonitor()
            monitor.wlan.isConnected.return_value = False
            monitor.run_iteration()

        get_memory.assert_not_called()
        monitor.telegram.notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
