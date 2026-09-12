import os
import sys
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
        patch("main.Temperature", side_effect=lambda gpio: MagicMock(readCurrentAverage=MagicMock(return_value=21.5))),
        patch("main.led_twinkle"),
        patch("main.led_error_twinkle"),
    ]


class AquariumMonitorTests(unittest.TestCase):
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


class MainLoopWatchdogTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
