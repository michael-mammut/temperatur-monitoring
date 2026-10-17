import socket
import time
import ubinascii

# Hard cap on how much of a request we ever read into memory. This alone
# defends against a memory-exhaustion DoS from a huge/lying Content-Length -
# no matter what a client claims, we never allocate more than this many
# bytes for a request, so the rest is simply never read.
_MAX_REQUEST_BYTES = 2048

_PROTECTED_PATHS = ('/settings', '/wifi-settings')


class StatusServer:
    def __init__(self, port, settings, wifi_settings, admin_password, reset_callback):
        self._settings = settings
        self._wifi_settings = wifi_settings
        self._admin_password = admin_password
        self._reset_callback = reset_callback
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

            if path in _PROTECTED_PATHS and not self._is_authorized(headers):
                response = self._unauthorized_response()
            elif path == '/settings' and method == 'POST':
                response = self._html_response(self._handle_settings_post(monitor, body))
            elif path == '/settings':
                response = self._html_response(self.render_settings())
            elif path == '/wifi-settings' and method == 'POST':
                html, should_reset = self._handle_wifi_settings_post(monitor, body)
                response = self._html_response(html)
            elif path == '/wifi-settings':
                response = self._html_response(self.render_wifi_settings(monitor))
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
            print("StatusServer request failed:", exc)
        finally:
            client.close()

    # -- request handlers --------------------------------------------------

    def _handle_settings_post(self, monitor, body):
        name = self._parse_form_field(body, 'name')
        if name and name.strip():
            name = name.strip()[:64]
            self._settings.set_name(name)
            monitor.telegram.set_project_name(name)
        return self.render_settings(saved=True)

    def _handle_wifi_settings_post(self, monitor, body):
        from WlanNetwork.wifisettings import validate_ssid, validate_password

        ssid = self._parse_form_field(body, 'ssid') or ''
        password = self._parse_form_field(body, 'password') or ''

        error = validate_ssid(ssid) or validate_password(password)
        if error:
            return self.render_wifi_settings(monitor, error=error, ssid=ssid), False

        self._wifi_settings.set_credentials(ssid, password)
        html = self.render_wifi_settings(monitor, saved=True, ssid=ssid)
        return html, True

    # -- rendering -----------------------------------------------------

    def render(self, monitor):
        water = self._format_temperature(monitor.last_water_temperature)
        ambient = self._format_temperature(monitor.last_ambient_temperature)
        name = self._escape_html(monitor.telegram._project_name)
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>{name}</title>
</head>
<body>
<h1>{name}</h1>
<p>Status: online</p>
<p>Wassertemperatur: {water} &deg;C</p>
<p>Umgebungstemperatur: {ambient} &deg;C</p>
<p>Letzte Messung: {updated}</p>
<p><a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a></p>
</body>
</html>
""".format(
            name=name,
            water=water,
            ambient=ambient,
            updated=self._format_time(monitor.last_measurement_time),
        )

    def render_settings(self, saved=False):
        name = self._escape_html(self._settings.get_name())
        message = '<p>Gespeichert.</p>' if saved else ''
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Einstellungen</title>
</head>
<body>
<h1>Einstellungen</h1>
{message}
<form method="POST" action="/settings">
<label>Aquarium-Name: <input type="text" name="name" value="{name}" maxlength="64"></label>
<button type="submit">Speichern</button>
</form>
<p><a href="/">Zur Status-Seite</a></p>
</body>
</html>
""".format(message=message, name=name)

    def render_wifi_settings(self, monitor, saved=False, error=None, ssid=None):
        current_ssid = self._escape_html(self._wifi_settings.get_ssid())
        options = self._render_network_options(monitor, selected=ssid)
        if saved:
            message = ('<p>Gespeichert. Das Gerät verbindet sich jetzt neu - '
                        'sollte das fehlschlagen, muss es per USB neu konfiguriert werden.</p>')
        elif error:
            message = '<p>Fehler: {}</p>'.format(self._escape_html(error))
        else:
            message = ''
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>WLAN-Einstellungen</title>
</head>
<body>
<h1>WLAN-Einstellungen</h1>
<p>Aktuell konfiguriert: {current_ssid}</p>
{message}
<form method="POST" action="/wifi-settings">
<label>Netzwerk:
<select name="ssid">
{options}
</select>
</label><br>
<label>Passwort: <input type="password" name="password" maxlength="63" autocomplete="new-password"></label>
<button type="submit">Verbinden</button>
</form>
<p><a href="/">Zur Status-Seite</a></p>
</body>
</html>
""".format(current_ssid=current_ssid, options=options, message=message)

    def _render_network_options(self, monitor, selected=None):
        try:
            ssids = monitor.wlan.scan_networks()
        except Exception:
            ssids = []
        if not ssids:
            return '<option value="">Keine Netzwerke gefunden</option>'
        options = []
        for ssid in ssids:
            escaped = self._escape_html(ssid)
            is_selected = ' selected' if ssid == selected else ''
            options.append('<option value="{0}"{1}>{0}</option>'.format(escaped, is_selected))
        return '\n'.join(options)

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

    def _escape_html(self, value):
        return (value.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;'))

    def _format_temperature(self, value):
        if value is None or value == -999:
            return "n/a"
        return str(value)

    def _format_time(self, value):
        if value is None:
            return "n/a"
        year, month, day, hour, minute, second = value[0:6]
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d} UTC".format(year, month, day, hour, minute, second)
