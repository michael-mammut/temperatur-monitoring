import socket
import time
import ubinascii

from WebServer.errorlog import ALL_CATEGORIES, CATEGORY_LABELS, CATEGORY_SYSTEM
from WebServer.systemstats import format_bytes, get_memory_stats, get_storage_stats

# Hard cap on how much of a request we ever read into memory. This alone
# defends against a memory-exhaustion DoS from a huge/lying Content-Length -
# no matter what a client claims, we never allocate more than this many
# bytes for a request, so the rest is simply never read.
_MAX_REQUEST_BYTES = 2048

_THIRTY_DAYS_SECONDS = 30 * 24 * 60 * 60

_PROTECTED_PATHS = ('/settings', '/wifi-settings', '/statistics')

_CHART_CATEGORIES = ALL_CATEGORIES

# Rendering more rows than this in one go risks a MemoryError from heap
# fragmentation on the ESP32 (see _render_error_table).
_MAX_DISPLAYED_ERRORS = 20


class StatusServer:
    def __init__(self, port, settings, wifi_settings, admin_password, reset_callback,
                 error_log=None, notification_log=None, login_log=None, monitoring_settings=None,
                 logging_settings=None):
        self._settings = settings
        self._wifi_settings = wifi_settings
        self._admin_password = admin_password
        self._reset_callback = reset_callback
        self._error_log = error_log
        self._notification_log = notification_log
        self._login_log = login_log
        self._monitoring_settings = monitoring_settings
        self._logging_settings = logging_settings
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
                self._record_login()
                response = self._html_response(self._handle_settings_post(monitor, body))
            elif path == '/settings':
                self._record_login()
                response = self._html_response(self.render_settings())
            elif path == '/wifi-settings' and method == 'POST':
                self._record_login()
                html, should_reset = self._handle_wifi_settings_post(monitor, body)
                response = self._html_response(html)
            elif path == '/wifi-settings':
                self._record_login()
                response = self._html_response(self.render_wifi_settings(monitor))
            elif path == '/statistics' and method == 'POST':
                previous_login = self._record_login()
                response = self._html_response(self._handle_statistics_post(monitor, body, previous_login))
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
            print("StatusServer request failed:", exc)
        finally:
            client.close()

    # -- request handlers --------------------------------------------------

    def _handle_settings_post(self, monitor, body):
        name = self._parse_form_field(body, 'name')
        ram_value = storage_value = log_storage_value = None
        error = None

        if self._monitoring_settings is not None:
            from Monitoring.settings import validate_percent
            ram_error, ram_value = validate_percent(self._parse_form_field(body, 'ram_percent'))
            storage_error, storage_value = validate_percent(self._parse_form_field(body, 'storage_percent'))
            log_storage_error, log_storage_value = validate_percent(
                self._parse_form_field(body, 'log_storage_percent'))
            error = ram_error or storage_error or log_storage_error

        if not error:
            if name and name.strip():
                name = name.strip()[:64]
                self._settings.set_name(name)
                monitor.telegram.set_project_name(name)
            if self._monitoring_settings is not None:
                self._monitoring_settings.set_thresholds(ram_value, storage_value, log_storage_value)
            if self._logging_settings is not None:
                enabled_by_category = {
                    category: self._parse_form_field(body, 'log_' + category) is not None
                    for category in ALL_CATEGORIES
                }
                self._logging_settings.set_enabled(enabled_by_category)

        return self.render_settings(saved=(error is None), error=error)

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
<p><a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a> | <a href="/statistics">Statistik</a></p>
</body>
</html>
""".format(
            name=name,
            water=water,
            ambient=ambient,
            updated=self._format_time(monitor.last_measurement_time),
        )

    def render_settings(self, saved=False, error=None):
        name = self._escape_html(self._settings.get_name())
        if error:
            message = '<p>Fehler: {}</p>'.format(self._escape_html(error))
        elif saved:
            message = '<p>Gespeichert.</p>'
        else:
            message = ''

        monitoring_fields = ''
        if self._monitoring_settings is not None:
            from Monitoring.settings import MAX_WARNING_PERCENT, MIN_WARNING_PERCENT
            monitoring_fields = (
                '<label>RAM-Warnschwelle (% frei): '
                '<input type="number" name="ram_percent" value="{ram}" min="{min}" max="{max}"></label><br>\n'
                '<label>Flash-Warnschwelle (% frei): '
                '<input type="number" name="storage_percent" value="{storage}" min="{min}" max="{max}"></label><br>\n'
                '<label>Log-Speicher-Deckel (% vom Flash): '
                '<input type="number" name="log_storage_percent" value="{log_storage}" min="{min}" max="{max}">'
                '</label><br>\n'
            ).format(
                ram=self._monitoring_settings.get_ram_percent(),
                storage=self._monitoring_settings.get_storage_percent(),
                log_storage=self._monitoring_settings.get_log_storage_percent(),
                min=MIN_WARNING_PERCENT, max=MAX_WARNING_PERCENT,
            )

        logging_fields = ''
        if self._logging_settings is not None:
            checkboxes = []
            for category in ALL_CATEGORIES:
                checked = ' checked' if self._logging_settings.is_enabled(category) else ''
                checkboxes.append(
                    '<label><input type="checkbox" name="log_{cat}" value="1"{checked}> {label}</label><br>'.format(
                        cat=category, checked=checked, label=self._escape_html(CATEGORY_LABELS[category])))
            logging_fields = '<p>Fehlerprotokollierung:</p>\n' + '\n'.join(checkboxes)

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
<label>Aquarium-Name: <input type="text" name="name" value="{name}" maxlength="64"></label><br>
{monitoring_fields}
{logging_fields}
<button type="submit">Speichern</button>
</form>
<p><a href="/">Status</a> | <a href="/wifi-settings">WLAN</a> | <a href="/statistics">Statistik</a></p>
</body>
</html>
""".format(message=message, name=name, monitoring_fields=monitoring_fields, logging_fields=logging_fields)

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
<p><a href="/">Status</a> | <a href="/settings">Einstellungen</a> | <a href="/statistics">Statistik</a></p>
</body>
</html>
""".format(current_ssid=current_ssid, options=options, message=message)

    def _handle_statistics_post(self, monitor, body, previous_login):
        minutes_raw = self._parse_form_field(body, 'minutes')
        try:
            minutes = float(minutes_raw)
            if minutes <= 0:
                raise ValueError("must be positive")
        except (TypeError, ValueError):
            message = 'Ungültige Angabe - bitte eine positive Zahl eingeben.'
        else:
            removed = 0
            if self._error_log is not None:
                removed += self._error_log.delete_older_than(minutes * 60)
            if self._notification_log is not None:
                removed += self._notification_log.delete_older_than(minutes * 60)
            message = '{} Log-Einträge gelöscht (älter als {:g} Minuten).'.format(removed, minutes)
        return self.render_statistics(monitor, previous_login, message=message)

    def render_statistics(self, monitor, previous_login, message=None):
        memory = get_memory_stats()
        try:
            storage = get_storage_stats()
        except Exception:
            storage = None
        rssi = monitor.wlan.get_rssi() if hasattr(monitor.wlan, 'get_rssi') else None
        notification_count = (
            self._notification_log.count_within(_THIRTY_DAYS_SECONDS)
            if self._notification_log is not None else 0
        )
        counts_by_category = self._error_counts_by_category()
        chart = self._render_error_chart(counts_by_category)
        error_rows = self._render_error_table()
        log_storage = self._format_log_storage(storage)
        message_html = '<p>{}</p>'.format(self._escape_html(message)) if message else ''

        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Statistik</title>
</head>
<body>
<h1>Statistik</h1>

<h2>Speicher (RAM)</h2>
<p>Belegt: {mem_used} &mdash; Frei: {mem_free} &mdash; Gesamt: {mem_total}</p>

<h2>Speicher (Flash)</h2>
<p>{storage}</p>
<p>Logs: {log_storage}</p>

<h2>Zugriff</h2>
<p>Letzter Login: {last_login}</p>
<p>WLAN-Signalstärke: {rssi}</p>

<h2>Benachrichtigungen</h2>
<p>Gesendet in den letzten 30 Tagen: {notification_count}</p>

<h2>Fehler der letzten 30 Tage</h2>
{chart}
<table border="1" cellpadding="4">
<tr><th>Zeitpunkt (UTC)</th><th>Kategorie</th><th>Fehlercode</th><th>Fehlermeldung</th></tr>
{error_rows}
</table>

<h2>Logs bereinigen</h2>
{message_html}
<form method="POST" action="/statistics">
<label>Lösche Log-Einträge älter als <input type="number" name="minutes" value="60" min="1" step="1"> Minuten</label>
<button type="submit">Löschen</button>
</form>

<p><a href="/">Status</a> | <a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a></p>
</body>
</html>
""".format(
            mem_used=format_bytes(memory['used']),
            mem_free=format_bytes(memory['free']),
            mem_total=format_bytes(memory['total']),
            storage=self._format_storage(storage),
            log_storage=log_storage,
            last_login=self._format_login_time(previous_login),
            rssi=self._format_rssi(rssi),
            notification_count=notification_count,
            chart=chart,
            error_rows=error_rows,
            message_html=message_html,
        )

    def _format_log_storage(self, storage):
        used = 0
        if self._error_log is not None:
            used += self._error_log.file_size()
        if self._notification_log is not None:
            used += self._notification_log.file_size()
        if storage is None or self._monitoring_settings is None:
            return format_bytes(used)
        budget_percent = self._monitoring_settings.get_log_storage_percent()
        budget_bytes = storage['total'] * budget_percent / 100
        return '{} von {} ({:.0f}% Deckel)'.format(format_bytes(used), format_bytes(budget_bytes), budget_percent)

    def _error_counts_by_category(self):
        counts = {}
        if self._error_log is None:
            return counts
        for entry in self._error_log.entries_within(_THIRTY_DAYS_SECONDS):
            category = entry.get('category', CATEGORY_SYSTEM)
            counts[category] = counts.get(category, 0) + 1
        return counts

    def _render_error_table(self):
        if self._error_log is None:
            return '<tr><td colspan="4">Keine Daten</td></tr>'
        entries = self._error_log.entries_within(_THIRTY_DAYS_SECONDS)
        if not entries:
            return '<tr><td colspan="4">Keine Fehler in den letzten 30 Tagen</td></tr>'

        total = len(entries)
        # Building one big string for every entry (up to 200) needs a single
        # large contiguous allocation, which fails with a MemoryError on the
        # ESP32's fragmented heap even when the *total* free memory would be
        # enough. Capping how many rows get rendered keeps the join small.
        shown = entries[-_MAX_DISPLAYED_ERRORS:]
        rows = []
        for entry in reversed(shown):  # newest first
            timestamp = self._format_epoch(entry.get('timestamp'))
            category = self._escape_html(CATEGORY_LABELS.get(entry.get('category'), entry.get('category', '')))
            code = self._escape_html(str(entry.get('code', '')))
            message = self._escape_html(str(entry.get('message', '')))
            rows.append(
                '<tr><td>{ts}</td><td>{cat}</td><td>{code}</td><td>{msg}</td></tr>'.format(
                    ts=timestamp, cat=category, code=code, msg=message))
        if total > len(shown):
            rows.append(
                '<tr><td colspan="4">… zeigt die letzten {} von {} Fehlern</td></tr>'.format(len(shown), total))
        return '\n'.join(rows)

    def _render_error_chart(self, counts):
        bar_width = 50
        gap = 20
        chart_height = 100
        max_count = max([counts.get(c, 0) for c in _CHART_CATEGORIES] + [1])
        bars = []
        for i, category in enumerate(_CHART_CATEGORIES):
            count = counts.get(category, 0)
            height = int((count / max_count) * chart_height)
            x = gap + i * (bar_width + gap)
            y = chart_height - height
            bars.append(
                '<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#c0392b"/>'
                '<text x="{tx}" y="{count_y}" font-size="12" text-anchor="middle">{count}</text>'
                '<text x="{tx}" y="{label_y}" font-size="11" text-anchor="middle">{label}</text>'.format(
                    x=x, y=y, w=bar_width, h=height,
                    tx=x + bar_width / 2,
                    count_y=(y - 5) if height > 0 else (chart_height - 5),
                    count=count,
                    label_y=chart_height + 15,
                    label=self._escape_html(CATEGORY_LABELS[category]),
                )
            )
        svg_width = gap + len(_CHART_CATEGORIES) * (bar_width + gap)
        return '<svg width="{w}" height="140" xmlns="http://www.w3.org/2000/svg">{bars}</svg>'.format(
            w=svg_width, bars=''.join(bars))

    def _format_storage(self, storage):
        if storage is None:
            return "nicht verfügbar"
        return "Belegt: {} &mdash; Frei: {} &mdash; Gesamt: {}".format(
            format_bytes(storage['used']), format_bytes(storage['free']), format_bytes(storage['total']))

    def _format_rssi(self, rssi):
        if rssi is None:
            return "nicht verfügbar"
        return "{} dBm".format(rssi)

    def _format_login_time(self, timestamp):
        if timestamp is None:
            return "noch nie"
        return self._format_epoch(timestamp)

    def _format_epoch(self, timestamp):
        if timestamp is None:
            return "n/a"
        year, month, day, hour, minute, second = time.gmtime(int(timestamp))[0:6]
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second)

    def _record_login(self):
        if self._login_log is None:
            return None
        return self._login_log.record_login()

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
