import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WlanNetwork import accesspoint
from WlanNetwork.accesspoint import SetupAccessPoint


class SetupAccessPointTests(unittest.TestCase):
    def setUp(self):
        p = patch("WlanNetwork.accesspoint.network.WLAN")
        self.wlan_cls = p.start()
        self.addCleanup(p.stop)
        self.ap = self.wlan_cls.return_value
        p = patch("WlanNetwork.accesspoint.CatchAllDnsServer")
        self.dns = p.start().return_value
        self.addCleanup(p.stop)

    def test_start_opens_wpa2_network_with_default_password(self):
        SetupAccessPoint().start()

        self.wlan_cls.assert_called_with("AP_IF")
        self.ap.active.assert_called_with(True)
        self.ap.config.assert_called_once_with(
            essid="Captain-Nemo-Setup", password="12345678", authmode=3)

    def test_password_is_long_enough_for_wpa2(self):
        """WPA2 needs at least 8 characters - a shorter one would leave the
        setup network open or fail to start."""
        self.assertGreaterEqual(len(accesspoint.AP_PASSWORD), 8)

    def test_config_is_applied_after_activating(self):
        SetupAccessPoint().start()

        names = [c[0] for c in self.ap.method_calls]
        self.assertLess(names.index("active"), names.index("config"))

    def test_led_blinks_once_per_second_while_active(self):
        point = SetupAccessPoint()
        point.start()

        led = point._led
        timer = point._timer
        values = []
        for _ in range(4):
            timer.callback(timer)
            values.append(led.value())

        self.assertEqual(values, [1, 0, 1, 0])

    def test_stop_turns_network_and_led_off(self):
        point = SetupAccessPoint()
        point.start()
        led = point._led
        point._timer.callback(point._timer)

        point.stop()

        self.ap.active.assert_called_with(False)
        self.assertEqual(led.value(), 0)
        self.assertIsNone(point._timer)
        self.assertFalse(point.is_active())

    def test_dns_server_runs_only_while_active(self):
        point = SetupAccessPoint()
        point.start()
        self.dns.start.assert_called_once()
        self.dns.stop.assert_not_called()

        point.stop()
        self.dns.stop.assert_called_once()

    def test_has_clients_reports_connected_stations(self):
        self.ap.status.return_value = [(b"\x01\x02\x03\x04\x05\x06",)]
        self.assertTrue(SetupAccessPoint().has_clients())

        self.ap.status.return_value = []
        self.assertFalse(SetupAccessPoint().has_clients())

    def test_has_clients_failure_counts_as_no_clients(self):
        self.ap.status.side_effect = OSError("not supported")

        self.assertFalse(SetupAccessPoint().has_clients())


if __name__ == "__main__":
    unittest.main()
