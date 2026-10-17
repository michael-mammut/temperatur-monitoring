import os
import socket
import sys
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.statusserver import StatusServer


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


def _fake_monitor(water=21.5, ambient=22.0, measured_at=(2024, 1, 1, 12, 30, 45, 0, 0), name="Vorzimmer"):
    return SimpleNamespace(
        telegram=_FakeTelegram(name),
        last_water_temperature=water,
        last_ambient_temperature=ambient,
        last_measurement_time=measured_at,
    )


class RenderTests(unittest.TestCase):
    def test_render_includes_project_name_status_and_temperatures(self):
        server = StatusServer(0, _FakeSettings())
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

    def test_render_shows_na_for_missing_readings(self):
        server = StatusServer(0, _FakeSettings())
        try:
            html = server.render(_fake_monitor(water=None, ambient=-999, measured_at=None))
        finally:
            server._socket.close()

        self.assertIn("n/a", html)
        self.assertNotIn("-999", html)  # sentinel value must not leak into the page

    def test_render_escapes_html_in_project_name(self):
        server = StatusServer(0, _FakeSettings())
        try:
            html = server.render(_fake_monitor(name='<script>alert(1)</script>'))
        finally:
            server._socket.close()

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class HandleRequestsTests(unittest.TestCase):
    def test_no_pending_connection_does_nothing(self):
        server = StatusServer(0, _FakeSettings())
        try:
            server.handle_requests(_fake_monitor())  # must not raise, no client connected
        finally:
            server._socket.close()

    def test_real_client_over_loopback_gets_the_status_page(self):
        server = StatusServer(0, _FakeSettings())
        port = server._socket.getsockname()[1]
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=2)
            try:
                client.send(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")

                # The TCP handshake is already complete by the time connect()
                # returns, so the connection should be in accept()'s backlog
                # immediately - but retry a few times with tiny sleeps to
                # absorb scheduler jitter instead of relying on a single try.
                for _ in range(10):
                    server.handle_requests(_fake_monitor())
                    time.sleep(0.05)

                response = client.recv(4096).decode("utf-8")
            finally:
                client.close()
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn("Content-Type: text/html", response)
        self.assertIn("21.5", response)

    def test_get_settings_shows_current_name(self):
        settings = _FakeSettings("Vorzimmer")
        server = StatusServer(0, settings)
        port = server._socket.getsockname()[1]
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=2)
            try:
                client.send(b"GET /settings HTTP/1.1\r\nHost: localhost\r\n\r\n")
                for _ in range(10):
                    server.handle_requests(_fake_monitor())
                    time.sleep(0.05)
                response = client.recv(4096).decode("utf-8")
            finally:
                client.close()
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertIn('value="Vorzimmer"', response)

    def test_post_settings_saves_new_name_and_updates_telegram(self):
        """Regression target: saving a new name via the form must update
        both persisted Settings and the already-constructed Telegram
        instance, without requiring a reboot."""
        settings = _FakeSettings("Vorzimmer")
        server = StatusServer(0, settings)
        port = server._socket.getsockname()[1]
        monitor = _fake_monitor(name="Vorzimmer")
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=2)
            try:
                body = b"name=Wohnzimmer"
                request = (
                    b"POST /settings HTTP/1.1\r\n"
                    b"Host: localhost\r\n"
                    b"Content-Type: application/x-www-form-urlencoded\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
                )
                client.send(request)
                for _ in range(10):
                    server.handle_requests(monitor)
                    time.sleep(0.05)
                response = client.recv(4096).decode("utf-8")
            finally:
                client.close()
        finally:
            server._socket.close()

        self.assertIn("200 OK", response)
        self.assertEqual(settings.get_name(), "Wohnzimmer")
        self.assertEqual(monitor.telegram._project_name, "Wohnzimmer")

    def test_post_settings_with_umlaut_and_space_is_decoded_correctly(self):
        settings = _FakeSettings("Vorzimmer")
        server = StatusServer(0, settings)
        port = server._socket.getsockname()[1]
        monitor = _fake_monitor(name="Vorzimmer")
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=2)
            try:
                # "Büro Zwei" form-urlencoded: ü -> %C3%BC, space -> +
                body = "name=B%C3%BCro+Zwei".encode("ascii")
                request = (
                    b"POST /settings HTTP/1.1\r\n"
                    b"Host: localhost\r\n"
                    b"Content-Type: application/x-www-form-urlencoded\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
                )
                client.send(request)
                for _ in range(10):
                    server.handle_requests(monitor)
                    time.sleep(0.05)
                client.recv(4096)
            finally:
                client.close()
        finally:
            server._socket.close()

        self.assertEqual(settings.get_name(), "Büro Zwei")


if __name__ == "__main__":
    unittest.main()
