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
from Notification import telegram as telegram_module
from Notification.telegram import Telegram


def _response(status=200):
    response = MagicMock()
    response.status_code = status
    return response


class _Patched:
    """Patches the reachability check and urequests.post for one test."""

    def __init__(self, post_side_effect=None, status=200, reachable_error=None):
        self.post_side_effect = post_side_effect
        self.status = status
        self.reachable_error = reachable_error

    def __enter__(self):
        self.response = _response(self.status)
        self._check = patch("Notification.telegram.check_reachable", side_effect=self.reachable_error)
        self._post = patch("Notification.telegram.urequests.post", return_value=self.response,
                           side_effect=self.post_side_effect)
        self.check = self._check.start()
        self.post = self._post.start()
        return self

    def __exit__(self, *exc):
        self._post.stop()
        self._check.stop()


class NotifyRequestTests(unittest.TestCase):
    def test_message_is_sent_as_json_body_not_raw_query_string(self):
        """Regression test: the message used to be concatenated unescaped
        into a GET query string ('&text=' + message). Telegram's nginx
        front-end rejects a raw space/°/comma in the request line with a
        plain 400 Bad Request, so every single notification silently failed.
        Sending it as a POST JSON body avoids any URL-encoding issue."""
        with _Patched() as p:
            Telegram("Vorzimmer").notify("Vorzimmer - Wassertemperatur: 21.5°C, Umgebungstemperatur 22.0°C")

        args, kwargs = p.post.call_args
        self.assertTrue(args[0].startswith("https://api.telegram.org/bot"))
        self.assertNotIn(" ", args[0])  # no query string at all
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(json.loads(kwargs["data"])["text"],
                         "Vorzimmer - Wassertemperatur: 21.5°C, Umgebungstemperatur 22.0°C")

    def test_body_is_encoded_as_utf8_bytes_not_character_count(self):
        """Regression test found on real hardware: urequests' json= kwarg
        sizes Content-Length by character count, not UTF-8 byte count. A
        message with "°" then got truncated, silently dropping chat_id."""
        message = "Neustart - Vorzimmer - Wassertemperatur: -999°C, Umgebungstemperatur -999°C"
        with _Patched() as p:
            Telegram("Vorzimmer").notify(message)

        body = p.post.call_args[1]["data"]
        expected = json.dumps({"chat_id": "-" + notification_config.CHAT_ID, "text": message}, ensure_ascii=False)
        self.assertIsInstance(body, bytes)
        self.assertEqual(len(body), len(expected.encode("utf-8")))
        self.assertNotEqual(len(body), len(expected))

    def test_response_is_closed(self):
        with _Patched() as p:
            Telegram("Vorzimmer").notify("hello")

        p.response.close.assert_called_once()

    def test_connection_error_does_not_crash(self):
        with _Patched(post_side_effect=OSError("no route to host")):
            Telegram("Vorzimmer").notify("hello")  # must not raise

    def test_successful_send_is_recorded_in_the_notification_log(self):
        fake_notification_log = MagicMock()
        with _Patched():
            Telegram("Vorzimmer", notification_log=fake_notification_log).notify("hello")

        fake_notification_log.record.assert_called_once()

    def test_failed_send_is_not_recorded_in_the_notification_log(self):
        fake_notification_log = MagicMock()
        with _Patched(post_side_effect=OSError("no route to host")):
            Telegram("Vorzimmer", notification_log=fake_notification_log).notify("hello")

        fake_notification_log.record.assert_not_called()

    def test_failed_send_is_recorded_in_the_error_log(self):
        fake_error_log = MagicMock()
        with _Patched(post_side_effect=OSError("no route to host")):
            Telegram("Vorzimmer", error_log=fake_error_log).notify("hello")

        fake_error_log.record.assert_called_once()
        self.assertEqual(fake_error_log.record.call_args[0][0]['category'], 'external_api')

    def test_non_200_answer_counts_as_failure(self):
        """E.g. a wrong chat id: Telegram answers 400 - that used to be
        treated as a successful send."""
        fake_error_log = MagicMock()
        with _Patched(status=400):
            result = Telegram("Vorzimmer", error_log=fake_error_log).notify("hello")

        self.assertFalse(result)
        self.assertIn("400", fake_error_log.record.call_args[0][0]['message'])

    def test_unreachable_telegram_is_not_requested_at_all(self):
        """The time-limited check runs first - urequests itself would block
        for 18 s in connect() (measured on the device)."""
        with _Patched(reachable_error=OSError("Telegram: keine Verbindung")) as p:
            result = Telegram("Vorzimmer").notify("hello")

        self.assertFalse(result)
        p.post.assert_not_called()


class NotifyResultTests(unittest.TestCase):
    """SensorAlert retries a warning later only if it knows the send
    failed - notify() has to tell it."""

    def test_successful_send_returns_true(self):
        with _Patched():
            self.assertTrue(Telegram("Vorzimmer").notify("hello"))

    def test_failed_send_returns_false(self):
        with _Patched(post_side_effect=OSError("no route to host")):
            self.assertFalse(Telegram("Vorzimmer").notify("hello"))


class RetryPauseTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        p = patch("Notification.telegram.time.ticks_ms", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)

    def test_no_new_attempt_within_the_pause_after_a_failure(self):
        """Otherwise every notification in the same loop iteration would
        wait out its own timeout while the internet is down."""
        telegram = Telegram("Vorzimmer")
        with _Patched(reachable_error=OSError("timeout")) as p:
            telegram.notify("a")
            self.now += telegram_module.RETRY_AFTER_FAILURE_MS - 1
            self.assertFalse(telegram.notify("b"))
        self.assertEqual(p.check.call_count, 1)

    def test_tries_again_after_the_pause(self):
        telegram = Telegram("Vorzimmer")
        with _Patched(reachable_error=OSError("timeout")):
            telegram.notify("a")
        self.now += telegram_module.RETRY_AFTER_FAILURE_MS
        with _Patched() as p:
            self.assertTrue(telegram.notify("b"))
        p.post.assert_called_once()


class _FakeSocket:
    def __init__(self, connect_error=None):
        self.connect_error = connect_error
        self.closed = False

    def setblocking(self, flag):
        pass

    def connect(self, address):
        if self.connect_error is not None:
            raise self.connect_error

    def close(self):
        self.closed = True


class CheckReachableTests(unittest.TestCase):
    def setUp(self):
        telegram_module._address_cache.clear()
        self.addCleanup(telegram_module._address_cache.clear)
        self.sock = _FakeSocket(connect_error=OSError(telegram_module.errno.EINPROGRESS))
        self.poller = MagicMock()
        self.poller.poll.return_value = [(self.sock, telegram_module.select.POLLOUT)]
        for target, kwargs in (
                ("Notification.telegram.socket.socket", {"return_value": self.sock}),
                ("Notification.telegram.socket.getaddrinfo", {"return_value": [(0, 0, 0, "", ("1.2.3.4", 443))]}),
                ("Notification.telegram.select.poll", {"return_value": self.poller})):
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_reachable_host_passes_and_socket_is_closed(self):
        telegram_module.check_reachable("api.telegram.org")

        self.assertTrue(self.sock.closed)

    def test_waits_at_most_the_connect_timeout(self):
        """Regression test from real hardware: with the internet down, a
        blocking connect() took 18 s (settimeout() is ignored there) -
        longer than the 15 s watchdog, so the board rebooted every ~22 s."""
        self.poller.poll.return_value = []  # nothing within the timeout

        with self.assertRaises(OSError):
            telegram_module.check_reachable("api.telegram.org")

        self.poller.poll.assert_called_once_with(telegram_module.CONNECT_TIMEOUT_MS)
        self.assertTrue(self.sock.closed)

    def test_address_is_resolved_once_and_reused(self):
        telegram_module.check_reachable("api.telegram.org")
        telegram_module.check_reachable("api.telegram.org")

        self.assertEqual(telegram_module.socket.getaddrinfo.call_count, 1)

    def test_failure_drops_the_cached_address(self):
        self.poller.poll.return_value = []
        with self.assertRaises(OSError):
            telegram_module.check_reachable("api.telegram.org")

        self.assertNotIn("api.telegram.org", telegram_module._address_cache)

    def test_immediate_connect_error_is_raised(self):
        self.sock.connect_error = OSError(113)  # EHOSTUNREACH, not "in progress"

        with self.assertRaises(OSError):
            telegram_module.check_reachable("api.telegram.org")


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
