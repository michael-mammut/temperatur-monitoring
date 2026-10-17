import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WlanNetwork.wlanconnection import WlanConnection


class ConnectHostnameTests(unittest.TestCase):
    def test_dhcp_hostname_is_set_before_connecting(self):
        """Regression test: wlan.config(dhcp_hostname=...) used to be
        commented out, so the router never learned the device's name and
        it was unreachable by hostname no matter what was configured."""
        with patch("WlanNetwork.wlanconnection.WLAN") as wlan_cls, \
             patch("WlanNetwork.wlanconnection.led_twinkle"), \
             patch("WlanNetwork.wlanconnection.led_error_twinkle"), \
             patch("WlanNetwork.wlanconnection.machine.idle"), \
             patch("WlanNetwork.wlanconnection.ntptime.settime"):
            fake_wlan = wlan_cls.return_value
            call_count = {"n": 0}

            def isconnected_side_effect():
                call_count["n"] += 1
                return call_count["n"] > 1  # not yet connected on the first (guard) check

            fake_wlan.isconnected.side_effect = isconnected_side_effect

            wlan = WlanConnection("my-ssid", "my-key", "captain-nemo")
            wlan.connect()

        fake_wlan.config.assert_called_once_with(dhcp_hostname="captain-nemo")

        config_index = [c[0] for c in fake_wlan.method_calls].index("config")
        connect_index = [c[0] for c in fake_wlan.method_calls].index("connect")
        self.assertLess(config_index, connect_index, "hostname must be set before connect() sends the DHCP request")


class EnsureTimeSyncedTests(unittest.TestCase):
    def test_skips_sync_when_clock_already_looks_real(self):
        wlan = WlanConnection("ssid", "key", "host")
        with patch("WlanNetwork.wlanconnection.time.gmtime", return_value=(2026, 10, 17, 8, 0, 0, 0, 0)), \
             patch("WlanNetwork.wlanconnection.ntptime.settime") as settime_mock:
            wlan.ensure_time_synced()

        settime_mock.assert_not_called()

    def test_syncs_when_clock_is_still_at_the_esp32_default(self):
        wlan = WlanConnection("ssid", "key", "host")
        with patch("WlanNetwork.wlanconnection.time.gmtime", return_value=(2000, 1, 1, 0, 0, 29, 0, 0)), \
             patch("WlanNetwork.wlanconnection.ntptime.settime") as settime_mock:
            wlan.ensure_time_synced()

        settime_mock.assert_called_once()

    def test_failed_sync_does_not_crash_and_can_be_retried_later(self):
        """Regression test: a single NTP failure right after connecting used
        to leave the clock stuck at 2000-01-01 for the rest of the boot,
        because this was only ever attempted once from connect() - and
        connect() is skipped entirely once isConnected() is already True.
        ensure_time_synced() must be safe to call every loop iteration."""
        wlan = WlanConnection("ssid", "key", "host")
        with patch("WlanNetwork.wlanconnection.time.gmtime", return_value=(2000, 1, 1, 0, 0, 29, 0, 0)), \
             patch("WlanNetwork.wlanconnection.ntptime.settime", side_effect=OSError("NTP timeout")):
            wlan.ensure_time_synced()  # must not raise

        # a later iteration, once the network recovers, must retry and succeed
        with patch("WlanNetwork.wlanconnection.time.gmtime", return_value=(2000, 1, 1, 0, 0, 32, 0, 0)), \
             patch("WlanNetwork.wlanconnection.ntptime.settime") as settime_mock:
            wlan.ensure_time_synced()

        settime_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
