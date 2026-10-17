import gc
import socket
import time
import ubinascii

from WebServer.datetimeformat import DEFAULT_CULTURE, DEFAULT_UTC_OFFSET_MINUTES
from WebServer.pages import settings as settings_page
from WebServer.pages import statistics as statistics_page
from WebServer.pages import status as status_page
from WebServer.pages import wifisettings as wifisettings_page

# Hard cap on how much of a request we ever read into memory. This alone
# defends against a memory-exhaustion DoS from a huge/lying Content-Length -
# no matter what a client claims, we never allocate more than this many
# bytes for a request, so the rest is simply never read.
_MAX_REQUEST_BYTES = 2048

_PROTECTED_PATHS = ('/settings', '/wifi-settings', '/statistics')


class WebServer:
    """The device's HTTP server: routing/transport, authentication and
    request parsing live here; each page's rendering and form-handling
    logic lives in its own module under WebServer/pages/."""

    def __init__(self, port, settings, wifi_settings, admin_password, reset_callback,
                 error_log=None, notification_log=None, login_log=None, monitoring_settings=None,
                 logging_settings=None, datetime_settings=None):
        self._settings = settings
        self._wifi_settings = wifi_settings
        self._admin_password = admin_password
        self._reset_callback = reset_callback
        self._error_log = error_log
        self._notification_log = notification_log
        self._login_log = login_log
        self._monitoring_settings = monitoring_settings
        self._logging_settings = logging_settings
        self._datetime_settings = datetime_settings
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(('0.0.0.0', port))
        self._socket.listen(1)
        self._socket.settimeout(0)

    def handle_requests(self, monitor):
        try:
            client, _ = self._socket.accept()
        except OSError:
            return  # no pending connection, this is the normal case

        should_reset = False
        try:
            client.settimeout(2)
            method, path, headers, body = self._parse_request(client.recv(_MAX_REQUEST_BYTES))

            # Rendering a page needs one contiguous allocation of a few KB
            # for the final HTML string. main.py's own gc.collect() only
            # runs *after* handle_requests() returns, so whatever the rest
            # of the loop iteration (sensors, WLAN, Telegram) fragmented
            # the heap with since then is still there - collecting here,
            # right before the heaviest allocation, is what actually
            # matters. Reproduced on real hardware: /settings (the biggest
            # page) failed with MemoryError without this, even with tens
            # of KB of total free RAM - a fragmentation problem, not a
            # total-memory one.
            gc.collect()

            if path in _PROTECTED_PATHS and not self._is_authorized(headers):
                response = self._unauthorized_response()
            elif path == '/settings' and method == 'POST':
                self._record_login()
                response = self._html_response(settings_page.handle_post(self, monitor, body))
            elif path == '/settings':
                self._record_login()
                response = self._html_response(self.render_settings())
            elif path == '/wifi-settings' and method == 'POST':
                self._record_login()
                html, should_reset = wifisettings_page.handle_post(self, monitor, body)
                response = self._html_response(html)
            elif path == '/wifi-settings':
                self._record_login()
                response = self._html_response(self.render_wifi_settings(monitor))
            elif path == '/statistics' and method == 'POST':
                previous_login = self._record_login()
                response = self._html_response(statistics_page.handle_post(self, monitor, body, previous_login))
            elif path == '/statistics':
                previous_login = self._record_login()
                response = self._html_response(self.render_statistics(monitor, previous_login))
            else:
                response = self._html_response(self.render(monitor))

            client.send(response.encode('utf-8'))
            if should_reset:
                # Give the socket a moment to actually flush the confirmation
                # page to the client before the device reboots to apply the
                # new WiFi credentials.
                time.sleep_ms(500)
                client.close()
                self._reset_callback()
        except Exception as exc:
            print("WebServer request failed:", exc)
        finally:
            client.close()

    # -- page rendering (thin delegators to WebServer/pages/*) -------------

    def render(self, monitor):
        return status_page.render(self, monitor)

    def render_settings(self, saved=False, error=None):
        return settings_page.render(self, saved=saved, error=error)

    def render_wifi_settings(self, monitor, saved=False, error=None, ssid=None):
        return wifisettings_page.render(self, monitor, saved=saved, error=error, ssid=ssid)

    def render_statistics(self, monitor, previous_login, message=None):
        return statistics_page.render(self, monitor, previous_login, message=message)

    # -- helpers shared by more than one page -------------------------------

    def _current_culture(self):
        return self._datetime_settings.get_culture() if self._datetime_settings is not None else DEFAULT_CULTURE

    def _current_utc_offset(self):
        return (self._datetime_settings.get_utc_offset_minutes()
                if self._datetime_settings is not None else DEFAULT_UTC_OFFSET_MINUTES)

    def _record_login(self):
        if self._login_log is None:
            return None
        return self._login_log.record_login()

    def _escape_html(self, value):
        return (value.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;'))

    # -- authentication --------------------------------------------------

    def _is_authorized(self, headers):
        auth_header = headers.get('authorization', '')
        if not auth_header.startswith('Basic '):
            return False
        try:
            decoded = ubinascii.a2b_base64(auth_header[6:]).decode('utf-8')
        except Exception:
            return False
        _, _, password = decoded.partition(':')
        return self._constant_time_equals(password, self._admin_password)

    def _constant_time_equals(self, a, b):
        if len(a) != len(b):
            return False
        result = 0
        for x, y in zip(a, b):
            result |= ord(x) ^ ord(y)
        return result == 0

    def _unauthorized_response(self):
        body = "Nicht autorisiert."
        return (
            "HTTP/1.1 401 Unauthorized\r\n"
            "WWW-Authenticate: Basic realm=\"Captain Nemo\"\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "Connection: close\r\n\r\n" + body
        )

    def _html_response(self, body):
        return (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Connection: close\r\n\r\n" + body
        )

    # -- request parsing --------------------------------------------------

    def _parse_request(self, raw):
        text = raw.decode('utf-8', 'ignore')
        head, _, body = text.partition('\r\n\r\n')
        lines = head.split('\r\n')
        request_line = lines[0] if lines else ''
        parts = request_line.split(' ')
        method = parts[0] if len(parts) > 0 else 'GET'
        path = parts[1] if len(parts) > 1 else '/'
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                key, _, value = line.partition(':')
                headers[key.strip().lower()] = value.strip()
        return method, path, headers, body

    def _parse_form_field(self, body, field_name):
        for pair in body.split('&'):
            key, _, value = pair.partition('=')
            if self._url_decode(key) == field_name:
                return self._url_decode(value)
        return None

    def _url_decode(self, value):
        raw = bytearray()
        i = 0
        while i < len(value):
            c = value[i]
            if c == '+':
                raw.append(0x20)
                i += 1
            elif c == '%' and i + 2 < len(value):
                try:
                    raw.append(int(value[i + 1:i + 3], 16))
                    i += 3
                except ValueError:
                    raw.append(ord(c))
                    i += 1
            else:
                raw.append(ord(c))
                i += 1
        return bytes(raw).decode('utf-8', 'ignore')
