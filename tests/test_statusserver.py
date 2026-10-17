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
    def __init__(self, networks=("NetworkA", "NetworkB")):
        self._networks = list(networks)

    def scan_networks(self):
        return self._networks


def _fake_monitor(water=21.5, ambient=22.0, measured_at=(2024, 1, 1, 12, 30, 45, 0, 0),
                   name="Vorzimmer", networks=("NetworkA", "NetworkB")):
    return SimpleNamespace(
        telegram=_FakeTelegram(name),
        wlan=_FakeWlan(networks),
        last_water_temperature=water,
        last_ambient_temperature=ambient,
        last_measurement_time=measured_at,
    )


def _basic_auth_header(password, username="admin"):
    token = base64.b64encode("{}:{}".format(username, password).encode("utf-8")).decode("ascii")
    return "Basic " + token


def _new_server(settings=None, wifi_settings=None, admin_password=ADMIN_PASSWORD, reset_callback=None):
    return StatusServer(
        0,
        settings or _FakeSettings(),
        wifi_settings or _FakeWifiSettings(),
        admin_password,
        reset_callback or MagicMock(),
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
