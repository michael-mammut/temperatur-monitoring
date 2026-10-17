import base64
import os
import socket
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.statusserver import StatusServer

ADMIN_PASSWORD = "s3cret-admin-pw"


class _FakeTelegram:
    def __init__(self, project_name):
        self._project_name = project_name

    def set_project_name(self, project_name):
        self._project_name = project_name


class _FakeSettings:
    def __init__(self, name="Vorzimmer"):
        self._name = name

    def get_name(self):
        return self._name

    def set_name(self, name):
        self._name = name


class _FakeWifiSettings:
    def __init__(self, ssid="FRITZ!Box", password="old-password"):
        self._ssid = ssid
        self._password = password
        self.saved_credentials = None

    def get_ssid(self):
        return self._ssid

    def get_password(self):
        return self._password

    def set_credentials(self, ssid, password):
        self._ssid = ssid
        self._password = password
        self.saved_credentials = (ssid, password)


class _FakeWlan:
    def __init__(self, networks=("NetworkA", "NetworkB"), rssi=-55):
        self._networks = list(networks)
        self._rssi = rssi

    def scan_networks(self):
        return self._networks

    def get_rssi(self):
        return self._rssi


def _fake_monitor(water=21.5, ambient=22.0, measured_at=(2024, 1, 1, 12, 30, 45, 0, 0),
                   name="Vorzimmer", networks=("NetworkA", "NetworkB"), rssi=-55):
    return SimpleNamespace(
        telegram=_FakeTelegram(name),
        wlan=_FakeWlan(networks, rssi=rssi),
        last_water_temperature=water,
        last_ambient_temperature=ambient,
        last_measurement_time=measured_at,
    )


def _basic_auth_header(password, username="admin"):
    token = base64.b64encode("{}:{}".format(username, password).encode("utf-8")).decode("ascii")
    return "Basic " + token


class _FakeMonitoringSettings:
    def __init__(self, ram_percent=20, storage_percent=20):
        self._ram_percent = ram_percent
        self._storage_percent = storage_percent
        self.saved_thresholds = None

    def get_ram_percent(self):
        return self._ram_percent

    def get_storage_percent(self):
        return self._storage_percent

    def set_thresholds(self, ram_percent, storage_percent):
        self._ram_percent = ram_percent
        self._storage_percent = storage_percent
        self.saved_thresholds = (ram_percent, storage_percent)


def _new_server(settings=None, wifi_settings=None, admin_password=ADMIN_PASSWORD, reset_callback=None,
                 error_log=None, notification_log=None, login_log=None, monitoring_settings=None):
    return StatusServer(
        0,
        settings or _FakeSettings(),
        wifi_settings or _FakeWifiSettings(),
        admin_password,
        reset_callback or MagicMock(),
        error_log=error_log,
        notification_log=notification_log,
        login_log=login_log,
        monitoring_settings=monitoring_settings,
    )


def _request(server, raw_request_bytes, retries=10):
    port = server._socket.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        client.send(raw_request_bytes)
        for _ in range(retries):
            server.handle_requests(server._test_monitor)
            time.sleep(0.05)
        return client.recv(4096).decode("utf-8")
    finally:
        client.close()


class RenderTests(unittest.TestCase):
    def test_render_includes_project_name_status_and_temperatures(self):
        server = _new_server()
        try:
            html = server.render(_fake_monitor())
        finally:
            server._socket.close()

        self.assertIn("Vorzimmer", html)
        self.assertIn("online", html)
        self.assertIn("21.5", html)
        self.assertIn("22.0", html)
        self.assertIn("2024-01-01 12:30:45 UTC", html)
        self.assertIn('href="/settings"', html)
        self.assertIn('href="/wifi-settings"', html)

    def test_render_shows_na_for_missing_readings(self):
        server = _new_server()
        try:
            html = server.render(_fake_monitor(water=None, ambient=-999, measured_at=None))
        finally:
            server._socket.close()

        self.assertIn("n/a", html)
        self.assertNotIn("-999", html)

    def test_render_escapes_html_in_project_name(self):
        server = _new_server()
        try:
            html = server.render(_fake_monitor(name='<script>alert(1)</script>'))
        finally:
            server._socket.close()

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class StatusPageAuthTests(unittest.TestCase):
    """The read-only status page must stay public - only the pages that
    change configuration require authentication."""

    def test_get_status_page_requires_no_authentication(self):
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            response = _request(server, b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)


class SettingsAuthTests(unittest.TestCase):
    def test_get_settings_without_auth_is_rejected(self):
        settings = _FakeSettings("Vorzimmer")
        server = _new_server(settings=settings)
        server._test_monitor = _fake_monitor()
        try:
            response = _request(server, b"GET /settings HTTP/1.1\r\nHost: localhost\r\n\r\n")
        finally:
            server._socket.close()

        self.assertIn("401", response)
        self.assertIn("WWW-Authenticate", response)

    def test_get_settings_with_wrong_password_is_rejected(self):
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header("totally-wrong") + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("401", response)

    def test_get_settings_with_correct_password_succeeds(self):
        settings = _FakeSettings("Vorzimmer")
        server = _new_server(settings=settings)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn('value="Vorzimmer"', response)

    def test_post_settings_without_auth_does_not_change_name(self):
        settings = _FakeSettings("Vorzimmer")
        server = _new_server(settings=settings)
        server._test_monitor = _fake_monitor(name="Vorzimmer")
        try:
            body = b"name=Hijacked"
            request = (
                b"POST /settings HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("401", response)
        self.assertEqual(settings.get_name(), "Vorzimmer")

    def test_post_settings_with_auth_changes_name(self):
        settings = _FakeSettings("Vorzimmer")
        server = _new_server(settings=settings)
        monitor = _fake_monitor(name="Vorzimmer")
        server._test_monitor = monitor
        try:
            body = b"name=Wohnzimmer"
            request = (
                "POST /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertEqual(settings.get_name(), "Wohnzimmer")
        self.assertEqual(monitor.telegram._project_name, "Wohnzimmer")


class MonitoringThresholdsOnSettingsPageTests(unittest.TestCase):
    def test_get_settings_shows_current_thresholds(self):
        monitoring_settings = _FakeMonitoringSettings(ram_percent=25, storage_percent=30)
        server = _new_server(monitoring_settings=monitoring_settings)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn('name="ram_percent" value="25"', response)
        self.assertIn('name="storage_percent" value="30"', response)

    def test_settings_page_without_monitoring_settings_omits_threshold_fields(self):
        """Backward compatible: callers that don't pass monitoring_settings
        (e.g. existing simpler tests/deployments) must not break."""
        server = _new_server(monitoring_settings=None)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertNotIn("ram_percent", response)

    def test_post_settings_saves_name_and_thresholds_together(self):
        settings = _FakeSettings("Vorzimmer")
        monitoring_settings = _FakeMonitoringSettings(ram_percent=20, storage_percent=20)
        server = _new_server(settings=settings, monitoring_settings=monitoring_settings)
        server._test_monitor = _fake_monitor(name="Vorzimmer")
        try:
            body = b"name=Wohnzimmer&ram_percent=15&storage_percent=10"
            request = (
                "POST /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn("Gespeichert", response)
        self.assertEqual(settings.get_name(), "Wohnzimmer")
        self.assertEqual(monitoring_settings.saved_thresholds, (15.0, 10.0))

    def test_post_settings_with_out_of_range_threshold_saves_nothing(self):
        """Regression target: validation failure must be atomic - a bad
        threshold value must not silently let the name change through."""
        settings = _FakeSettings("Vorzimmer")
        monitoring_settings = _FakeMonitoringSettings(ram_percent=20, storage_percent=20)
        server = _new_server(settings=settings, monitoring_settings=monitoring_settings)
        server._test_monitor = _fake_monitor(name="Vorzimmer")
        try:
            body = b"name=Wohnzimmer&ram_percent=99&storage_percent=20"
            request = (
                "POST /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Fehler", response)
        self.assertEqual(settings.get_name(), "Vorzimmer")  # unchanged
        self.assertIsNone(monitoring_settings.saved_thresholds)

    def test_post_settings_with_non_numeric_threshold_is_rejected(self):
        monitoring_settings = _FakeMonitoringSettings()
        server = _new_server(monitoring_settings=monitoring_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"name=Vorzimmer&ram_percent=abc&storage_percent=20"
            request = (
                "POST /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Fehler", response)
        self.assertIsNone(monitoring_settings.saved_thresholds)


class WifiSettingsPageTests(unittest.TestCase):
    def test_get_wifi_settings_lists_scanned_networks(self):
        wifi_settings = _FakeWifiSettings(ssid="OldNetwork")
        server = _new_server(wifi_settings=wifi_settings)
        server._test_monitor = _fake_monitor(networks=("NetworkA", "NetworkB"))
        try:
            request = (
                "GET /wifi-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn("OldNetwork", response)  # currently configured, shown but not pre-filled as password
        self.assertIn('value="NetworkA"', response)
        self.assertIn('value="NetworkB"', response)
        self.assertNotIn("old-password", response)  # password must never be echoed back

    def test_scanned_ssid_with_html_is_escaped(self):
        """A nearby network can name itself anything, including HTML/JS -
        this must not inject into the page of whoever views the dropdown."""
        wifi_settings = _FakeWifiSettings()
        server = _new_server(wifi_settings=wifi_settings)
        server._test_monitor = _fake_monitor(networks=('<script>evil()</script>',))
        try:
            request = (
                "GET /wifi-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertNotIn("<script>evil()</script>", response)
        self.assertIn("&lt;script&gt;", response)

    def test_post_wifi_settings_without_auth_does_not_save_or_reset(self):
        wifi_settings = _FakeWifiSettings()
        reset_callback = MagicMock()
        server = _new_server(wifi_settings=wifi_settings, reset_callback=reset_callback)
        server._test_monitor = _fake_monitor()
        try:
            body = b"ssid=NetworkA&password=NewPassword123"
            request = (
                b"POST /wifi-settings HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("401", response)
        self.assertIsNone(wifi_settings.saved_credentials)
        reset_callback.assert_not_called()

    def test_post_wifi_settings_with_valid_credentials_saves_and_resets(self):
        wifi_settings = _FakeWifiSettings()
        reset_callback = MagicMock()
        server = _new_server(wifi_settings=wifi_settings, reset_callback=reset_callback)
        server._test_monitor = _fake_monitor()
        try:
            body = "ssid=NetworkA&password=NewPassword123".encode()
            request = (
                "POST /wifi-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertEqual(wifi_settings.saved_credentials, ("NetworkA", "NewPassword123"))
        reset_callback.assert_called_once()

    def test_post_wifi_settings_with_empty_ssid_is_rejected(self):
        wifi_settings = _FakeWifiSettings()
        reset_callback = MagicMock()
        server = _new_server(wifi_settings=wifi_settings, reset_callback=reset_callback)
        server._test_monitor = _fake_monitor()
        try:
            body = "ssid=&password=NewPassword123".encode()
            request = (
                "POST /wifi-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)  # the form page itself still renders...
        self.assertIn("Fehler", response)  # ...but shows a validation error
        self.assertIsNone(wifi_settings.saved_credentials)
        reset_callback.assert_not_called()

    def test_post_wifi_settings_with_too_short_password_is_rejected(self):
        wifi_settings = _FakeWifiSettings()
        reset_callback = MagicMock()
        server = _new_server(wifi_settings=wifi_settings, reset_callback=reset_callback)
        server._test_monitor = _fake_monitor()
        try:
            body = "ssid=NetworkA&password=abc".encode()
            request = (
                "POST /wifi-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Fehler", response)
        self.assertIsNone(wifi_settings.saved_credentials)
        reset_callback.assert_not_called()


class StatisticsPageTests(unittest.TestCase):
    def test_get_statistics_without_auth_is_rejected(self):
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            response = _request(server, b"GET /statistics HTTP/1.1\r\nHost: localhost\r\n\r\n")
        finally:
            server._socket.close()

        self.assertIn("401", response)

    def test_statistics_page_shows_memory_rssi_and_notification_count(self):
        notification_log = MagicMock()
        notification_log.count_within.return_value = 7
        server = _new_server(notification_log=notification_log)
        server._test_monitor = _fake_monitor(rssi=-42)
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn("-42 dBm", response)
        self.assertIn("7", response)  # notification count
        self.assertIn('http-equiv="refresh" content="30"', response)

    def test_statistics_page_shows_previous_login_not_the_current_one(self):
        """Regression target: visiting /statistics is itself a login - the
        page must show the login BEFORE this one, not trivially "just now"."""
        login_log = MagicMock()
        login_log.record_login.return_value = 1700000000  # some earlier timestamp
        server = _new_server(login_log=login_log)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        login_log.record_login.assert_called_once()
        self.assertNotIn("noch nie", response)

    def test_statistics_page_shows_never_logged_in_when_no_login_log(self):
        server = _new_server(login_log=None)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("noch nie", response)

    def test_statistics_page_shows_error_chart_and_table(self):
        error_log = MagicMock()
        error_log.entries_within.return_value = [
            {'timestamp': 1700000000, 'category': 'hardware', 'code': 'OSError', 'message': 'sensor missing'},
            {'timestamp': 1700000100, 'category': 'network', 'code': 'OSError', 'message': 'no AP found'},
        ]
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("<svg", response)
        self.assertIn("sensor missing", response)
        self.assertIn("no AP found", response)
        self.assertIn("OSError", response)

    def test_statistics_page_caps_displayed_rows_to_avoid_large_allocation(self):
        """Regression test found on real hardware: joining up to 200 rows
        into one HTML string needs a single large contiguous allocation,
        which failed with a MemoryError on the ESP32's fragmented heap even
        though gc.mem_free() reported plenty of *total* free memory."""
        error_log = MagicMock()
        error_log.entries_within.return_value = [
            {'timestamp': 1700000000 + i, 'category': 'hardware', 'code': 'OSError', 'message': 'entry %d' % i}
            for i in range(150)
        ]
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertEqual(response.count("<tr>"), 1 + 20 + 1)  # header + 20 rows + "...n more" row
        self.assertIn("letzten 20 von 150", response)
        self.assertIn("entry 149", response)  # newest entry is shown
        self.assertNotIn("entry 0", response)  # oldest entry got truncated away

    def test_statistics_page_error_message_is_html_escaped(self):
        """Error messages ultimately come from exception text - if one ever
        contains attacker-influenced data (e.g. a malformed response body
        echoed into an error message), it must not inject into the page."""
        error_log = MagicMock()
        error_log.entries_within.return_value = [
            {'timestamp': 1700000000, 'category': 'network', 'code': 'OSError',
             'message': '<script>alert(1)</script>'},
        ]
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertNotIn("<script>alert(1)</script>", response)
        self.assertIn("&lt;script&gt;", response)

    def test_statistics_page_shows_no_errors_message_when_log_empty(self):
        error_log = MagicMock()
        error_log.entries_within.return_value = []
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Keine Fehler", response)


class RequestSizeLimitTests(unittest.TestCase):
    def test_oversized_body_does_not_crash_the_server(self):
        """A client lying about (or abusing) body size must not be able to
        make the device allocate unbounded memory - recv() is hard-capped
        regardless of what Content-Length claims."""
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            huge_body = b"name=" + (b"A" * 100000)
            request = (
                b"POST /settings HTTP/1.1\r\nHost: localhost\r\n"
                b"Authorization: " + _basic_auth_header(ADMIN_PASSWORD).encode() + b"\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                b"Content-Length: " + str(len(huge_body)).encode() + b"\r\n\r\n" + huge_body
            )
            response = _request(server, request)  # must not raise / hang
        finally:
            server._socket.close()

        self.assertTrue(response)  # server stayed alive and answered something


if __name__ == "__main__":
    unittest.main()
