import socket
import time


class StatusServer:
    def __init__(self, port, settings):
        self._settings = settings
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

        try:
            client.settimeout(2)
            method, path, body = self._parse_request(client.recv(2048))

            if path == '/settings' and method == 'POST':
                name = self._parse_form_field(body, 'name')
                if name and name.strip():
                    self._settings.set_name(name.strip())
                    monitor.telegram.set_project_name(name.strip())
                html = self.render_settings(saved=True)
            elif path == '/settings':
                html = self.render_settings()
            else:
                html = self.render(monitor)

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Connection: close\r\n\r\n" + html
            )
            client.send(response.encode('utf-8'))
        except Exception as exc:
            print("StatusServer request failed:", exc)
        finally:
            client.close()

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
<p><a href="/settings">Einstellungen</a></p>
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
<label>Aquarium-Name: <input type="text" name="name" value="{name}"></label>
<button type="submit">Speichern</button>
</form>
<p><a href="/">Zur Status-Seite</a></p>
</body>
</html>
""".format(message=message, name=name)

    def _parse_request(self, raw):
        text = raw.decode('utf-8', 'ignore')
        head, _, body = text.partition('\r\n\r\n')
        request_line = head.split('\r\n', 1)[0]
        parts = request_line.split(' ')
        method = parts[0] if len(parts) > 0 else 'GET'
        path = parts[1] if len(parts) > 1 else '/'
        return method, path, body

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
