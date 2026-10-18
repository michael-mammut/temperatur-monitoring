import base64
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.webserver import WebServer

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
    def __init__(self, ram_percent=20, storage_percent=20, log_storage_percent=15):
        self._ram_percent = ram_percent
        self._storage_percent = storage_percent
        self._log_storage_percent = log_storage_percent
        self.saved_thresholds = None

    def get_ram_percent(self):
        return self._ram_percent

    def get_storage_percent(self):
        return self._storage_percent

    def get_log_storage_percent(self):
        return self._log_storage_percent

    def set_thresholds(self, ram_percent, storage_percent, log_storage_percent):
        self._ram_percent = ram_percent
        self._storage_percent = storage_percent
        self._log_storage_percent = log_storage_percent
        self.saved_thresholds = (ram_percent, storage_percent, log_storage_percent)


class _FakeDateTimeSettings:
    def __init__(self, culture='iso', utc_offset_minutes=0, eu_summer_time=False):
        self._culture = culture
        self._utc_offset_minutes = utc_offset_minutes
        self._eu_summer_time = eu_summer_time
        self.saved_culture = None
        self.saved_utc_offset_minutes = None
        self.saved_eu_summer_time = None

    def get_culture(self):
        return self._culture

    def get_utc_offset_minutes(self):
        return self._utc_offset_minutes

    def get_eu_summer_time(self):
        return self._eu_summer_time

    def set(self, culture, utc_offset_minutes, eu_summer_time):
        self._culture = culture
        self._utc_offset_minutes = utc_offset_minutes
        self._eu_summer_time = eu_summer_time
        self.saved_culture = culture
        self.saved_utc_offset_minutes = utc_offset_minutes
        self.saved_eu_summer_time = eu_summer_time


class _FakeLoggingSettings:
    def __init__(self, enabled=None):
        from WebServer.errorlog import ALL_CATEGORIES
        self._enabled = {category: True for category in ALL_CATEGORIES}
        if enabled:
            self._enabled.update(enabled)
        self.saved_enabled = None

    def is_enabled(self, category):
        return self._enabled.get(category, True)

    def set_enabled(self, enabled_by_category):
        self._enabled.update(enabled_by_category)
        self.saved_enabled = dict(enabled_by_category)


def _new_server(settings=None, wifi_settings=None, admin_password=ADMIN_PASSWORD, reset_callback=None,
                 error_log=None, notification_log=None, login_log=None, monitoring_settings=None,
                 logging_settings=None, datetime_settings=None):
    return WebServer(
        0,
        settings or _FakeSettings(),
        wifi_settings or _FakeWifiSettings(),
        admin_password,
        reset_callback or MagicMock(),
        error_log=error_log,
        notification_log=notification_log,
        login_log=login_log,
        monitoring_settings=monitoring_settings,
        logging_settings=logging_settings,
        datetime_settings=datetime_settings,
    )


def _request(server, raw_request_bytes, retries=10):
    port = server._socket.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        client.send(raw_request_bytes)
        for _ in range(retries):
            server.handle_requests(server._test_monitor)
            time.sleep(0.05)
        chunks = []
        while True:
            try:
                chunk = client.recv(4096)
            except ConnectionResetError:
                # The server may close the socket before the client has
                # drained an oversized/unread request body; the OS then
                # answers further reads with RST instead of a clean EOF.
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
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
            body = b"name=Wohnzimmer&ram_percent=15&storage_percent=10&log_storage_percent=12"
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
        self.assertEqual(monitoring_settings.saved_thresholds, (15.0, 10.0, 12.0))

    def test_post_settings_with_out_of_range_threshold_saves_nothing(self):
        """Regression target: validation failure must be atomic - a bad
        threshold value must not silently let the name change through."""
        settings = _FakeSettings("Vorzimmer")
        monitoring_settings = _FakeMonitoringSettings(ram_percent=20, storage_percent=20)
        server = _new_server(settings=settings, monitoring_settings=monitoring_settings)
        server._test_monitor = _fake_monitor(name="Vorzimmer")
        try:
            body = b"name=Wohnzimmer&ram_percent=99&storage_percent=20&log_storage_percent=15"
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


class LoggingSettingsOnSettingsPageTests(unittest.TestCase):
    def test_get_settings_shows_checkboxes_reflecting_current_state(self):
        from WebServer.errorlog import CATEGORY_HARDWARE
        logging_settings = _FakeLoggingSettings(enabled={CATEGORY_HARDWARE: False})
        server = _new_server(logging_settings=logging_settings)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        # hardware is disabled -> no "checked" on that checkbox
        self.assertIn('name="log_hardware" value="1">', response)
        # network stayed enabled -> "checked" present
        self.assertIn('name="log_network" value="1" checked>', response)

    def test_settings_page_without_logging_settings_omits_checkboxes(self):
        server = _new_server(logging_settings=None)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertNotIn("log_hardware", response)

    def test_post_settings_unchecking_a_category_disables_it(self):
        """Regression target: HTML checkboxes send nothing at all when
        unchecked - the handler must treat an absent field as "disabled",
        not crash or silently keep the old value."""
        from WebServer.errorlog import CATEGORY_EXTERNAL_API, CATEGORY_HARDWARE, CATEGORY_NETWORK, CATEGORY_SYSTEM
        logging_settings = _FakeLoggingSettings()
        server = _new_server(logging_settings=logging_settings)
        server._test_monitor = _fake_monitor()
        try:
            # only log_network is checked; the other three are left out,
            # exactly like a real browser submitting unchecked checkboxes
            body = b"name=Vorzimmer&log_network=1"
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
        self.assertEqual(logging_settings.saved_enabled, {
            CATEGORY_SYSTEM: False,
            CATEGORY_HARDWARE: False,
            CATEGORY_NETWORK: True,
            CATEGORY_EXTERNAL_API: False,
        })

    def test_post_settings_with_validation_error_does_not_change_logging_settings(self):
        """Atomic with the other /settings fields: an invalid threshold
        must not let the logging checkboxes through either."""
        monitoring_settings = _FakeMonitoringSettings()
        logging_settings = _FakeLoggingSettings()
        server = _new_server(monitoring_settings=monitoring_settings, logging_settings=logging_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"name=Vorzimmer&ram_percent=99&storage_percent=20"
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
        self.assertIsNone(logging_settings.saved_enabled)

    def test_render_formats_last_measurement_using_configured_culture(self):
        datetime_settings = _FakeDateTimeSettings(culture='de_AT', utc_offset_minutes=0)
        server = _new_server(datetime_settings=datetime_settings)
        try:
            html = server.render(_fake_monitor(measured_at=(2026, 10, 17, 6, 5, 9, 0, 0)))
        finally:
            server._socket.close()

        self.assertIn("17.10.2026 06:05:09 UTC", html)

    def test_render_applies_configured_utc_offset_including_day_rollover(self):
        """+10h on 2026-10-17 23:30 UTC must roll over into the next day,
        not just add 10 to the hour field."""
        datetime_settings = _FakeDateTimeSettings(culture='iso', utc_offset_minutes=600)
        server = _new_server(datetime_settings=datetime_settings)
        try:
            html = server.render(_fake_monitor(measured_at=(2026, 10, 17, 23, 30, 0, 0, 0)))
        finally:
            server._socket.close()

        self.assertIn("2026-10-18 09:30:00 UTC+10", html)

    def test_render_without_datetime_settings_defaults_to_iso(self):
        server = _new_server(datetime_settings=None)
        try:
            html = server.render(_fake_monitor(measured_at=(2026, 10, 17, 6, 5, 9, 0, 0)))
        finally:
            server._socket.close()

        self.assertIn("2026-10-17 06:05:09 UTC", html)


class ErrorLogDownloadTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(self._restore_cwd)

    def _restore_cwd(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _get(self, path, error_log=None, authorized=True):
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        auth = "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n" if authorized else ""
        try:
            return _request(server, ("GET " + path + " HTTP/1.1\r\nHost: localhost\r\n" + auth + "\r\n").encode())
        finally:
            server._socket.close()

    def _log_with_entries(self):
        from WebServer.eventlog import EventLog
        log = EventLog('error_log.json')
        log.record({'category': 'hardware', 'code': 'OneWireError', 'message': ''}, merge_within_seconds=3600)
        log.record({'category': 'hardware', 'code': 'OneWireError', 'message': ''}, merge_within_seconds=3600)
        return log

    def test_requires_authentication(self):
        response = self._get("/error-log.json", error_log=self._log_with_entries(), authorized=False)

        self.assertIn("401 Unauthorized", response)
        self.assertNotIn("OneWireError", response)

    def test_query_string_does_not_bypass_authentication(self):
        response = self._get("/error-log.json?download=1", error_log=self._log_with_entries(), authorized=False)

        self.assertIn("401 Unauthorized", response)

    def test_returns_the_raw_json_file(self):
        response = self._get("/error-log.json", error_log=self._log_with_entries())

        head, _, body = response.partition("\r\n\r\n")
        self.assertIn("200 OK", head)
        self.assertIn("Content-Type: application/json; charset=utf-8", head)
        entries = json.loads(body)
        self.assertEqual(entries[0]['code'], 'OneWireError')
        self.assertEqual(entries[0]['count'], 2)

    def test_is_never_rendered_as_html(self):
        """Error messages can contain text from outside (e.g. a server
        response) - the browser must not sniff it as HTML."""
        response = self._get("/error-log.json", error_log=self._log_with_entries())

        self.assertIn("X-Content-Type-Options: nosniff", response)

    def test_shown_inline_by_default(self):
        response = self._get("/error-log.json", error_log=self._log_with_entries())

        self.assertNotIn("Content-Disposition", response)

    def test_download_parameter_saves_as_file(self):
        response = self._get("/error-log.json?download=1", error_log=self._log_with_entries())

        self.assertIn('Content-Disposition: attachment; filename="error_log.json"', response)

    def test_without_error_log_returns_empty_list(self):
        response = self._get("/error-log.json", error_log=None)

        self.assertEqual(response.partition("\r\n\r\n")[2], "[]")

    def test_statistics_page_links_to_raw_data(self):
        server = _new_server()
        try:
            html = server.render_statistics(_fake_monitor(), None)
        finally:
            server._socket.close()

        self.assertIn('href="/error-log.json"', html)
        self.assertIn('href="/error-log.json?download=1"', html)


class _FakeSensorAlertSettings:
    def __init__(self, enabled=True):
        self._enabled = enabled
        self.saved = None

    def is_enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        self._enabled = enabled
        self.saved = enabled


class SensorAlertOnSettingsPageTests(unittest.TestCase):
    def _post(self, server, body):
        request = (
            "POST /settings HTTP/1.1\r\nHost: localhost\r\n"
            "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n"
            "Content-Length: " + str(len(body)) + "\r\n\r\n"
        ).encode() + body
        return _request(server, request)

    def _server(self, alert_settings, monitoring_settings=None):
        server = _new_server(monitoring_settings=monitoring_settings)
        server._sensor_alert_settings = alert_settings
        server._test_monitor = _fake_monitor()
        return server

    def test_checkbox_reflects_current_state(self):
        for enabled, expected in ((True, 'name="sensor_alert" value="1" checked>'),
                                  (False, 'name="sensor_alert" value="1">')):
            server = self._server(_FakeSensorAlertSettings(enabled=enabled))
            try:
                html = server.render_settings()
            finally:
                server._socket.close()
            self.assertIn(expected, html)

    def test_checked_box_enables_and_unchecked_box_disables(self):
        alert_settings = _FakeSensorAlertSettings(enabled=False)
        server = self._server(alert_settings)
        try:
            self._post(server, b"name=Vorzimmer&sensor_alert=1")
            self.assertIs(alert_settings.saved, True)
            # unchecked checkboxes are simply missing from the form body
            self._post(server, b"name=Vorzimmer")
            self.assertIs(alert_settings.saved, False)
        finally:
            server._socket.close()

    def test_validation_error_does_not_change_the_setting(self):
        """Atomic with the other /settings fields."""
        alert_settings = _FakeSensorAlertSettings(enabled=True)
        server = self._server(alert_settings, monitoring_settings=_FakeMonitoringSettings())
        try:
            response = self._post(server, b"name=Vorzimmer&ram_percent=99&storage_percent=20")
        finally:
            server._socket.close()

        self.assertIn("Fehler", response)
        self.assertIsNone(alert_settings.saved)

    def test_page_without_sensor_alert_settings_omits_the_checkbox(self):
        server = self._server(None)
        try:
            html = server.render_settings()
        finally:
            server._socket.close()

        self.assertNotIn("sensor_alert", html)


class DateTimeSettingsPageTests(unittest.TestCase):
    """/datetime-settings - split off from /settings so the biggest
    single chunk of that page (culture + ~38 timezone options) doesn't
    have to be part of every /settings render; see MemoryManagementTests
    for why that mattered."""

    def test_get_datetime_settings_shows_dropdowns_with_current_selection(self):
        datetime_settings = _FakeDateTimeSettings(culture='de_AT', utc_offset_minutes=60, eu_summer_time=True)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn('name="culture"', response)
        self.assertIn('<option value="de_AT" selected>', response)
        self.assertIn('<option value="iso">', response)  # not selected
        self.assertIn('name="utc_offset_minutes"', response)
        self.assertIn('<option value="60" selected>', response)
        self.assertIn('<option value="0">', response)  # not selected
        self.assertIn('name="eu_summer_time"', response)
        self.assertIn('name="eu_summer_time" value="1" checked', response)

    def test_datetime_settings_page_without_datetime_settings_shows_not_configured(self):
        """Backward compatible: callers that don't pass datetime_settings
        must not break."""
        server = _new_server(datetime_settings=None)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertNotIn('name="culture"', response)
        self.assertNotIn('name="utc_offset_minutes"', response)
        self.assertIn("Nicht konfiguriert", response)

    def test_settings_page_no_longer_has_datetime_fields(self):
        """Regression target for the page split: /settings must stay
        small - culture/timezone/EU-summer-time belong on their own
        page now."""
        datetime_settings = _FakeDateTimeSettings(culture='de_AT', utc_offset_minutes=60, eu_summer_time=True)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertNotIn('name="culture"', response)
        self.assertNotIn('name="utc_offset_minutes"', response)
        self.assertNotIn('name="eu_summer_time"', response)
        self.assertIn('href="/datetime-settings"', response)

    def test_post_datetime_settings_saves_culture_timezone_and_eu_summer_time(self):
        datetime_settings = _FakeDateTimeSettings(culture='iso', utc_offset_minutes=0, eu_summer_time=False)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"culture=en_US&utc_offset_minutes=-480&eu_summer_time=1"
            request = (
                "POST /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn("Gespeichert", response)
        self.assertEqual(datetime_settings.saved_culture, 'en_US')
        self.assertEqual(datetime_settings.saved_utc_offset_minutes, -480)
        self.assertTrue(datetime_settings.saved_eu_summer_time)

    def test_post_datetime_settings_without_eu_summer_time_checkbox_disables_it(self):
        """A real browser omits an unchecked checkbox entirely from the
        POST body - must be treated as False, not as a missing/invalid
        field."""
        datetime_settings = _FakeDateTimeSettings(culture='iso', utc_offset_minutes=0, eu_summer_time=True)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"culture=de_AT&utc_offset_minutes=60"
            request = (
                "POST /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertFalse(datetime_settings.saved_eu_summer_time)

    def test_post_datetime_settings_with_unknown_culture_saves_nothing(self):
        """Defense against a crafted request sending a culture value that
        was never offered in the dropdown."""
        datetime_settings = _FakeDateTimeSettings(culture='iso', utc_offset_minutes=0)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"culture=fr_FR&utc_offset_minutes=0"
            request = (
                "POST /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Fehler", response)
        self.assertIsNone(datetime_settings.saved_culture)

    def test_post_datetime_settings_with_unknown_utc_offset_saves_nothing(self):
        """Defense against a crafted request sending an offset that was
        never offered in the dropdown (e.g. a bogus 37-minute offset)."""
        datetime_settings = _FakeDateTimeSettings(culture='iso', utc_offset_minutes=0)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"culture=iso&utc_offset_minutes=37"
            request = (
                "POST /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Fehler", response)
        self.assertIsNone(datetime_settings.saved_utc_offset_minutes)

    def test_post_datetime_settings_without_auth_does_not_save(self):
        datetime_settings = _FakeDateTimeSettings(culture='iso', utc_offset_minutes=0)
        server = _new_server(datetime_settings=datetime_settings)
        server._test_monitor = _fake_monitor()
        try:
            body = b"culture=en_US&utc_offset_minutes=-480&eu_summer_time=1"
            request = (
                "POST /datetime-settings HTTP/1.1\r\nHost: localhost\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("401", response)
        self.assertIsNone(datetime_settings.saved_culture)


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
        notification_log.file_size.return_value = 0
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
        error_log.file_size.return_value = 0
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

    def test_statistics_page_counts_merged_errors_with_their_count(self):
        """Identical errors within 12 h are merged into one entry with a
        count - the page must still show how often they happened."""
        error_log = MagicMock()
        error_log.file_size.return_value = 0
        error_log.entries_within.return_value = [
            {'timestamp': 1700000000, 'category': 'hardware', 'code': 'OneWireError', 'message': '', 'count': 37},
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

        self.assertIn("OneWireError &times;37", response)
        self.assertIn(">37<", response)  # chart bar label for the hardware category

    def test_statistics_page_caps_displayed_rows_to_avoid_large_allocation(self):
        """Regression test found on real hardware: joining up to 200 rows
        into one HTML string needs a single large contiguous allocation,
        which failed with a MemoryError on the ESP32's fragmented heap even
        though gc.mem_free() reported plenty of *total* free memory."""
        error_log = MagicMock()
        error_log.file_size.return_value = 0
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
        error_log.file_size.return_value = 0
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
        error_log.file_size.return_value = 0
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

    def test_statistics_page_shows_log_storage_usage_against_budget(self):
        """The displayed budget must match main.py's actual enforcement
        formula: a share of headroom (free space + what the logs already
        use), not of total flash capacity - see WebServer/eventlog.py."""
        error_log = MagicMock()
        error_log.file_size.return_value = 1024
        error_log.entries_within.return_value = []
        notification_log = MagicMock()
        notification_log.file_size.return_value = 0
        notification_log.count_within.return_value = 0
        monitoring_settings = _FakeMonitoringSettings(log_storage_percent=15)
        server = _new_server(error_log=error_log, notification_log=notification_log,
                              monitoring_settings=monitoring_settings)
        server._test_monitor = _fake_monitor()
        try:
            with patch("WebServer.pages.statistics.get_storage_stats",
                       return_value={'used': 9000, 'free': 1000, 'total': 10000}):
                request = (
                    "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                    "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
                ).encode()
                response = _request(server, request)
        finally:
            server._socket.close()

        # headroom = free(1000) + used-by-logs(1024) = 2024; budget = 15% of that = 303.6 B
        self.assertIn("1.0 KB", response)
        self.assertIn("303.6 B", response)
        self.assertIn("15% des verfügbaren Speichers", response)

    def test_get_statistics_shows_delete_logs_form(self):
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            request = (
                "GET /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n\r\n"
            ).encode()
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn('action="/statistics"', response)
        self.assertIn('name="minutes"', response)

    def test_post_statistics_deletes_log_entries_older_than_given_minutes(self):
        error_log = MagicMock()
        error_log.file_size.return_value = 0
        error_log.entries_within.return_value = []
        error_log.delete_older_than.return_value = 3
        notification_log = MagicMock()
        notification_log.file_size.return_value = 0
        notification_log.count_within.return_value = 0
        notification_log.delete_older_than.return_value = 2
        server = _new_server(error_log=error_log, notification_log=notification_log)
        server._test_monitor = _fake_monitor()
        try:
            body = b"minutes=60"
            request = (
                "POST /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        error_log.delete_older_than.assert_called_once_with(60 * 60)
        notification_log.delete_older_than.assert_called_once_with(60 * 60)
        self.assertIn("5 Log-Einträge gelöscht", response)

    def test_post_statistics_without_auth_does_not_delete_anything(self):
        error_log = MagicMock()
        error_log.file_size.return_value = 0
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            body = b"minutes=60"
            request = (
                b"POST /statistics HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Type: application/x-www-form-urlencoded\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("401", response)
        error_log.delete_older_than.assert_not_called()

    def test_post_statistics_with_invalid_minutes_shows_error_and_deletes_nothing(self):
        error_log = MagicMock()
        error_log.file_size.return_value = 0
        error_log.entries_within.return_value = []
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            body = b"minutes=abc"
            request = (
                "POST /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Ungültige Angabe", response)
        error_log.delete_older_than.assert_not_called()

    def test_post_statistics_with_zero_minutes_is_rejected(self):
        error_log = MagicMock()
        error_log.file_size.return_value = 0
        error_log.entries_within.return_value = []
        server = _new_server(error_log=error_log)
        server._test_monitor = _fake_monitor()
        try:
            body = b"minutes=0"
            request = (
                "POST /statistics HTTP/1.1\r\nHost: localhost\r\n"
                "Authorization: " + _basic_auth_header(ADMIN_PASSWORD) + "\r\n"
                "Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode() + body
            response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("Ungültige Angabe", response)
        error_log.delete_older_than.assert_not_called()


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


class MemoryManagementTests(unittest.TestCase):
    def test_handle_requests_collects_garbage_before_building_the_response(self):
        """Regression target: on real hardware, rendering /settings (the
        biggest page) failed with a MemoryError even with tens of KB of
        free RAM - heap fragmentation, not a lack of total memory. gc.collect()
        normally only runs *after* handle_requests() returns (main.py's loop),
        so whatever the rest of the loop iteration fragmented since then is
        still there when a request comes in - collecting right here, before
        the heaviest allocation, is what actually fixes it."""
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            with patch("WebServer.webserver.gc.collect") as mock_collect:
                request = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
                _request(server, request)
        finally:
            server._socket.close()

        mock_collect.assert_called()

    def test_memory_error_during_rendering_is_retried_once_after_gc_collect(self):
        """Regression target: /settings kept growing (culture + timezone +
        EU-summer-time fields) and the single gc.collect() at the top of
        handle_requests() stopped being reliably enough, because the heap
        keeps fragmenting *while* a page is built (e.g. iterating ~45
        dropdown options). Rather than chase that with more and more
        manually-placed collect() calls, a MemoryError during rendering is
        now treated as transient and retried once after another
        gc.collect() - this must turn a transient failure into a normal
        200 response instead of an empty one."""
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            with patch("WebServer.webserver.status_page.render",
                       side_effect=[MemoryError("simulated fragmentation"), "<html>ok</html>"]) as mock_render, \
                 patch("WebServer.webserver.gc.collect") as mock_collect:
                request = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
                response = _request(server, request)
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn("<html>ok</html>", response)
        self.assertEqual(mock_render.call_count, 2)
        self.assertEqual(mock_collect.call_count, 2)

    def test_memory_error_on_both_attempts_does_not_crash_the_server(self):
        """If even the retry fails, the connection must still be closed
        cleanly (no response, same as any other unhandled exception) -
        not leave the server stuck or the socket hanging."""
        server = _new_server()
        server._test_monitor = _fake_monitor()
        try:
            with patch("WebServer.webserver.status_page.render",
                       side_effect=MemoryError("simulated fragmentation")):
                request = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
                response = _request(server, request)  # must not raise/hang

            # server must still be alive and answer a normal follow-up request
            request2 = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
            response2 = _request(server, request2)
        finally:
            server._socket.close()

        self.assertEqual(response, "")  # first request got no response at all
        self.assertIn("200 OK", response2)


if __name__ == "__main__":
    unittest.main()
