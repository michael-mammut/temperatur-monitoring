import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from Notification import config as notification_config
from Notification.telegram import Telegram


class NotifyClosesResponseTests(unittest.TestCase):
    """Regression tests for the socket/memory leak: every urequests response
    must be closed, on both the success and the failure path."""

    def test_successful_request_closes_response(self):
        telegram = Telegram("Vorzimmer")
        fake_response = MagicMock()
        fake_response.json.return_value = {"ok": True}

        with patch("Notification.telegram.urequests.post", return_value=fake_response) as post_mock:
            telegram.notify("hello")

        post_mock.assert_called_once()
        fake_response.close.assert_called_once()

    def test_message_is_sent_as_json_body_not_raw_query_string(self):
        """Regression test: the message used to be concatenated unescaped
        into a GET query string ('&text=' + message). Telegram's nginx
        front-end rejects a raw space/°/comma in the request line with a
        plain 400 Bad Request, so every single notification silently failed.
        Sending it as a POST JSON body avoids any URL-encoding issue."""
        telegram = Telegram("Vorzimmer")
        fake_response = MagicMock()
        fake_response.json.return_value = {"ok": True}

        with patch("Notification.telegram.urequests.post", return_value=fake_response) as post_mock:
            telegram.notify("Vorzimmer - Wassertemperatur: 21.5°C, Umgebungstemperatur 22.0°C")

        args, kwargs = post_mock.call_args
        self.assertNotIn(" ", args[0])  # URL itself has no query string at all
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        body = json.loads(kwargs["data"])
        self.assertEqual(
            body["text"],
            "Vorzimmer - Wassertemperatur: 21.5°C, Umgebungstemperatur 22.0°C",
        )

    def test_body_is_encoded_as_utf8_bytes_not_character_count(self):
        """Regression test found on real hardware: urequests' json= kwarg
        sizes Content-Length by character count, not UTF-8 byte count. A
        message with multi-byte characters like "°" then gets truncated at
        the transport layer, silently dropping the trailing chat_id field
        and making Telegram reject the request as "chat_id is empty".
        Encoding to bytes ourselves must make body length == UTF-8 byte
        length, not Python string length."""
        telegram = Telegram("Vorzimmer")
        fake_response = MagicMock()
        fake_response.json.return_value = {"ok": True}
        message = "Neustart - Vorzimmer - Wassertemperatur: -999°C, Umgebungstemperatur -999°C"

        with patch("Notification.telegram.urequests.post", return_value=fake_response) as post_mock:
            telegram.notify(message)

        _, kwargs = post_mock.call_args
        body = kwargs["data"]
        expected = {"chat_id": "-" + notification_config.CHAT_ID, "text": message}
        expected_str = json.dumps(expected, ensure_ascii=False)  # matches MicroPython's ujson.dumps
        self.assertIsInstance(body, bytes)
        self.assertEqual(len(body), len(expected_str.encode("utf-8")))
        self.assertNotEqual(len(body), len(expected_str))  # UTF-8 bytes != character count for "°"

    def test_failed_request_still_closes_response(self):
        telegram = Telegram("Vorzimmer")
        fake_response = MagicMock()
        fake_response.json.side_effect = ValueError("invalid json")

        with patch("Notification.telegram.urequests.post", return_value=fake_response):
            telegram.notify("hello")  # must not raise

        fake_response.close.assert_called_once()

    def test_connection_error_does_not_crash(self):
        telegram = Telegram("Vorzimmer")

        with patch("Notification.telegram.urequests.post", side_effect=OSError("no route to host")):
            telegram.notify("hello")  # must not raise, no response to close

    def test_successful_send_is_recorded_in_the_notification_log(self):
        fake_notification_log = MagicMock()
        telegram = Telegram("Vorzimmer", notification_log=fake_notification_log)
        fake_response = MagicMock()
        fake_response.json.return_value = {"ok": True}

        with patch("Notification.telegram.urequests.post", return_value=fake_response):
            telegram.notify("hello")

        fake_notification_log.record.assert_called_once()

    def test_failed_send_is_not_recorded_in_the_notification_log(self):
        fake_notification_log = MagicMock()
        telegram = Telegram("Vorzimmer", notification_log=fake_notification_log)

        with patch("Notification.telegram.urequests.post", side_effect=OSError("no route to host")):
            telegram.notify("hello")

        fake_notification_log.record.assert_not_called()

    def test_failed_send_is_recorded_in_the_error_log(self):
        fake_error_log = MagicMock()
        telegram = Telegram("Vorzimmer", error_log=fake_error_log)

        with patch("Notification.telegram.urequests.post", side_effect=OSError("no route to host")):
            telegram.notify("hello")

        fake_error_log.record.assert_called_once()
        self.assertEqual(fake_error_log.record.call_args[0][0]['category'], 'external_api')


class NotifyResultTests(unittest.TestCase):
    """SensorAlert retries a warning later only if it knows the send
    failed - notify() has to tell it."""

    def test_successful_send_returns_true(self):
        fake_response = MagicMock()
        fake_response.json.return_value = {"ok": True}
        with patch("Notification.telegram.urequests.post", return_value=fake_response):
            self.assertTrue(Telegram("Vorzimmer").notify("hello"))

    def test_failed_send_returns_false(self):
        with patch("Notification.telegram.urequests.post", side_effect=OSError("no route to host")):
            self.assertFalse(Telegram("Vorzimmer").notify("hello"))


class NotificationTimingTests(unittest.TestCase):
    def test_first_run_always_notifies(self):
        telegram = Telegram("Vorzimmer", morning_hour_message=6, afternoon_hour_message=14)
        with patch("Notification.telegram.time.gmtime", return_value=(2024, 1, 1, 3, 0, 0, 0, 0)):
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
