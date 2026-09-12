import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from Notification.telegram import Telegram


class NotifyClosesResponseTests(unittest.TestCase):
    """Regression tests for the socket/memory leak: every urequests response
    must be closed, on both the success and the failure path."""

    def test_successful_request_closes_response(self):
        telegram = Telegram("Vorzimmer")
        fake_response = MagicMock()
        fake_response.json.return_value = {"ok": True}

        with patch("Notification.telegram.urequests.get", return_value=fake_response) as get_mock:
            telegram.notify("hello")

        get_mock.assert_called_once()
        fake_response.close.assert_called_once()

    def test_failed_request_still_closes_response(self):
        telegram = Telegram("Vorzimmer")
        fake_response = MagicMock()
        fake_response.json.side_effect = ValueError("invalid json")

        with patch("Notification.telegram.urequests.get", return_value=fake_response):
            telegram.notify("hello")  # must not raise

        fake_response.close.assert_called_once()

    def test_connection_error_does_not_crash(self):
        telegram = Telegram("Vorzimmer")

        with patch("Notification.telegram.urequests.get", side_effect=OSError("no route to host")):
            telegram.notify("hello")  # must not raise, no response to close


class NotificationTimingTests(unittest.TestCase):
    def test_first_run_always_notifies(self):
        telegram = Telegram("Vorzimmer", morning_hour_message=6, afternoon_hour_message=14)
        with patch.object(telegram, "notify") as notify_mock:
            counter = telegram.send_aquarium_notification(20.0, 21.0, first_run=True, message_send_counter=0)
        notify_mock.assert_called_once()
        self.assertEqual(counter, 0)

    def test_notifies_at_morning_hour_only_once(self):
        telegram = Telegram("Vorzimmer", morning_hour_message=6, afternoon_hour_message=14)
        with patch("Notification.telegram.time.gmtime", return_value=(2024, 1, 1, 6, 0, 0, 0, 0)):
            with patch.object(telegram, "notify") as notify_mock:
                counter = telegram.send_aquarium_notification(20.0, 21.0, first_run=False, message_send_counter=0)
        notify_mock.assert_called_once()
        self.assertEqual(counter, 1)

    def test_does_not_notify_twice_at_same_hour(self):
        telegram = Telegram("Vorzimmer", morning_hour_message=6, afternoon_hour_message=14)
        with patch("Notification.telegram.time.gmtime", return_value=(2024, 1, 1, 6, 0, 0, 0, 0)):
            with patch.object(telegram, "notify") as notify_mock:
                counter = telegram.send_aquarium_notification(20.0, 21.0, first_run=False, message_send_counter=1)
        notify_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
