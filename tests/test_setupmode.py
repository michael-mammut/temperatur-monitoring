import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WlanNetwork import setupmode
from WlanNetwork.setupmode import NetworkSetup


class _Clock:
    def __init__(self):
        self.now = 0

    def advance(self, ms):
        self.now += ms


class _SetupTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        p = patch("WlanNetwork.setupmode.time.ticks_ms", side_effect=lambda: self.clock.now)
        p.start()
        self.addCleanup(p.stop)
        self.wlan = MagicMock()
        self.wlan.connect.return_value = False
        self.access_point = MagicMock()
        self.access_point.has_clients.return_value = False

    def _setup(self, has_credentials=True, setup_requested=False):
        return NetworkSetup(self.wlan, self.access_point, has_credentials, setup_requested)


class StartConditionTests(_SetupTestCase):
    def test_normal_boot_with_credentials_does_not_open_setup_network(self):
        setup = self._setup()

        self.assertFalse(setup.is_active())
        self.access_point.start.assert_not_called()

    def test_no_credentials_opens_setup_network_immediately(self):
        setup = self._setup(has_credentials=False)

        self.assertTrue(setup.is_active())
        self.access_point.start.assert_called_once()

    def test_double_reset_opens_setup_network_immediately(self):
        setup = self._setup(setup_requested=True)

        self.assertTrue(setup.is_active())
        self.access_point.start.assert_called_once()

    def test_station_reconnect_attempts_are_stopped_when_setup_opens(self):
        """The ESP32 keeps retrying a failed station connection in the
        background, hopping channels - which keeps dropping clients of the
        setup network. Opening it must stop those attempts."""
        self._setup(has_credentials=False)

        self.wlan.disconnect.assert_called_once()


class DnsPollTests(_SetupTestCase):
    def test_poll_answers_dns_only_while_setup_network_is_up(self):
        setup = self._setup()
        setup.poll()
        self.access_point.poll_dns.assert_not_called()

        setup = self._setup(has_credentials=False)
        setup.poll()
        self.access_point.poll_dns.assert_called_once()


class NoCredentialsTests(_SetupTestCase):
    def test_stays_open_forever_and_never_tries_the_home_wlan(self):
        setup = self._setup(has_credentials=False)

        self.clock.advance(24 * 60 * 60 * 1000)
        setup.update()

        self.assertTrue(setup.is_active())
        self.wlan.connect.assert_not_called()
        self.access_point.stop.assert_not_called()


class ButtonSetupTests(_SetupTestCase):
    def test_does_not_try_the_old_wlan_during_the_setup_window(self):
        setup = self._setup(setup_requested=True)

        self.clock.advance(setupmode.BUTTON_SETUP_TIMEOUT_MS - 1)
        setup.update()

        self.assertTrue(setup.is_active())
        self.wlan.connect.assert_not_called()

    def test_closes_after_timeout_so_the_old_wlan_is_used_again(self):
        setup = self._setup(setup_requested=True)

        self.clock.advance(setupmode.BUTTON_SETUP_TIMEOUT_MS)
        setup.update()

        self.assertFalse(setup.is_active())
        self.access_point.stop.assert_called_once()

    def test_stays_open_past_timeout_while_someone_is_connected(self):
        setup = self._setup(setup_requested=True)
        self.access_point.has_clients.return_value = True

        self.clock.advance(setupmode.BUTTON_SETUP_TIMEOUT_MS + 60000)
        setup.update()

        self.assertTrue(setup.is_active())
        self.access_point.stop.assert_not_called()


class FallbackTests(_SetupTestCase):
    def test_opens_after_being_offline_for_the_fallback_time(self):
        setup = self._setup()

        setup.mark_offline()
        self.clock.advance(setupmode.FALLBACK_AFTER_MS - 1)
        setup.mark_offline()
        self.assertFalse(setup.is_active())

        self.clock.advance(1)
        setup.mark_offline()
        self.assertTrue(setup.is_active())

    def test_coming_online_resets_the_fallback_timer(self):
        setup = self._setup()

        setup.mark_offline()
        self.clock.advance(setupmode.FALLBACK_AFTER_MS - 1000)
        setup.mark_online()
        setup.mark_offline()
        self.clock.advance(2000)
        setup.mark_offline()

        self.assertFalse(setup.is_active())

    def _open_fallback(self):
        setup = self._setup()
        setup.mark_offline()
        self.clock.advance(setupmode.FALLBACK_AFTER_MS)
        setup.mark_offline()
        self.wlan.disconnect.reset_mock()
        return setup

    def test_home_wlan_is_retried_and_setup_closes_once_it_is_back(self):
        setup = self._open_fallback()
        self.wlan.connect.return_value = True

        setup.update()

        self.assertFalse(setup.is_active())
        self.access_point.stop.assert_called_once()

    def test_failed_retry_stops_the_background_reconnect_again(self):
        setup = self._open_fallback()

        setup.update()

        self.assertTrue(setup.is_active())
        self.wlan.disconnect.assert_called_once()

    def test_home_wlan_is_retried_at_most_once_per_interval(self):
        setup = self._open_fallback()

        setup.update()
        self.clock.advance(setupmode.HOME_RETRY_INTERVAL_MS - 1)
        setup.update()
        self.assertEqual(self.wlan.connect.call_count, 1)

        self.clock.advance(1)
        setup.update()
        self.assertEqual(self.wlan.connect.call_count, 2)

    def test_home_wlan_is_not_retried_while_someone_is_connected(self):
        """A station connection attempt makes the radio hop channels,
        which would kick out whoever is configuring the device."""
        setup = self._open_fallback()
        self.access_point.has_clients.return_value = True

        setup.update()

        self.wlan.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
