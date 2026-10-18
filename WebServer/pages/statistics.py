import time

from WebServer.datetimeformat import format_datetime
from WebServer.errorlog import ALL_CATEGORIES, CATEGORY_LABELS, CATEGORY_SYSTEM
from WebServer.systemstats import format_bytes, get_memory_stats, get_storage_stats
from WebServer.webstyle import html_parts

_THIRTY_DAYS_SECONDS = 30 * 24 * 60 * 60

_CHART_CATEGORIES = ALL_CATEGORIES

# Rendering more rows than this in one go risks a MemoryError from heap
# fragmentation on the ESP32 (see _render_error_table).
_MAX_DISPLAYED_ERRORS = 20


def handle_post(server, monitor, body, previous_login):
    minutes_raw = server._parse_form_field(body, 'minutes')
    try:
        minutes = float(minutes_raw)
        if minutes <= 0:
            raise ValueError("must be positive")
    except (TypeError, ValueError):
        message = 'Ungültige Angabe - bitte eine positive Zahl eingeben.'
    else:
        removed = 0
        if server._error_log is not None:
            removed += server._error_log.delete_older_than(minutes * 60)
        if server._notification_log is not None:
            removed += server._notification_log.delete_older_than(minutes * 60)
        message = '{} Log-Einträge gelöscht (älter als {:g} Minuten).'.format(removed, minutes)
    return render(server, monitor, previous_login, message=message)


def render(server, monitor, previous_login, message=None):
    memory = get_memory_stats()
    try:
        storage = get_storage_stats()
    except Exception:
        storage = None
    rssi = monitor.wlan.get_rssi() if hasattr(monitor.wlan, 'get_rssi') else None
    notification_count = (
        server._notification_log.count_within(_THIRTY_DAYS_SECONDS)
        if server._notification_log is not None else 0
    )
    counts_by_category = _error_counts_by_category(server)
    chart = _render_error_chart(server, counts_by_category)
    error_rows = _render_error_table(server)
    log_storage = _format_log_storage(server, storage)
    message_html = '<p class="msg">{}</p>'.format(server._escape_html(message)) if message else ''

    return html_parts("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Statistik</title>
{style}
</head>
<body>
<div class="card">
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
<p>Rohdaten: <a href="/error-log.json">anzeigen</a> | <a href="/error-log.json?download=1">als JSON herunterladen</a></p>

<h2>Logs bereinigen</h2>
{message_html}
<form method="POST" action="/statistics">
<label>Lösche Log-Einträge älter als <input type="number" name="minutes" value="60" min="1" step="1"> Minuten</label>
<button type="submit">Löschen</button>
</form>

<p class="nav"><a href="/">Status</a> | <a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a> | <a href="/datetime-settings">Datum/Zeit</a></p>
</div>
</body>
</html>
""",
        mem_used=format_bytes(memory['used']),
        mem_free=format_bytes(memory['free']),
        mem_total=format_bytes(memory['total']),
        storage=_format_storage(storage),
        log_storage=log_storage,
        last_login=_format_login_time(server, previous_login),
        rssi=_format_rssi(rssi),
        notification_count=notification_count,
        chart=chart,
        error_rows=error_rows,
        message_html=message_html,
    )


def _format_log_storage(server, storage):
    used = 0
    if server._error_log is not None:
        used += server._error_log.file_size()
    if server._notification_log is not None:
        used += server._notification_log.file_size()
    if storage is None or server._monitoring_settings is None:
        return format_bytes(used)
    # Mirrors main.py's enforce_storage_budget(): the budget is a share
    # of headroom (current free space + what the logs already use),
    # not of total flash capacity - see WebServer/eventlog.py for why.
    budget_percent = server._monitoring_settings.get_log_storage_percent()
    headroom = storage['free'] + used
    budget_bytes = headroom * budget_percent / 100
    return '{} von {} ({:.0f}% des verfügbaren Speichers)'.format(
        format_bytes(used), format_bytes(budget_bytes), budget_percent)


def _error_counts_by_category(server):
    counts = {}
    if server._error_log is None:
        return counts
    for entry in server._error_log.entries_within(_THIRTY_DAYS_SECONDS):
        category = entry.get('category', CATEGORY_SYSTEM)
        counts[category] = counts.get(category, 0) + entry.get('count', 1)
    return counts


def _render_error_table(server):
    if server._error_log is None:
        return '<tr><td colspan="4">Keine Daten</td></tr>'
    entries = server._error_log.entries_within(_THIRTY_DAYS_SECONDS)
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
        timestamp = _format_epoch(server, entry.get('timestamp'))
        category = server._escape_html(CATEGORY_LABELS.get(entry.get('category'), entry.get('category', '')))
        code = server._escape_html(str(entry.get('code', '')))
        if entry.get('count', 1) > 1:
            code += ' &times;{}'.format(int(entry['count']))
        message = server._escape_html(str(entry.get('message', '')))
        rows.append(
            '<tr><td>{ts}</td><td>{cat}</td><td>{code}</td><td>{msg}</td></tr>'.format(
                ts=timestamp, cat=category, code=code, msg=message))
    if total > len(shown):
        rows.append(
            '<tr><td colspan="4">… zeigt die letzten {} von {} Fehlern</td></tr>'.format(len(shown), total))
    return '\n'.join(rows)


def _render_error_chart(server, counts):
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
                label=server._escape_html(CATEGORY_LABELS[category]),
            )
        )
    svg_width = gap + len(_CHART_CATEGORIES) * (bar_width + gap)
    return '<svg width="{w}" height="140" xmlns="http://www.w3.org/2000/svg">{bars}</svg>'.format(
        w=svg_width, bars=''.join(bars))


def _format_storage(storage):
    if storage is None:
        return "nicht verfügbar"
    return "Belegt: {} &mdash; Frei: {} &mdash; Gesamt: {}".format(
        format_bytes(storage['used']), format_bytes(storage['free']), format_bytes(storage['total']))


def _format_rssi(rssi):
    if rssi is None:
        return "nicht verfügbar"
    return "{} dBm".format(rssi)


def _format_login_time(server, timestamp):
    if timestamp is None:
        return "noch nie"
    return _format_epoch(server, timestamp)


def _format_epoch(server, timestamp):
    if timestamp is None:
        return "n/a"
    return format_datetime(time.gmtime(int(timestamp)), server._current_culture(), server._current_utc_offset(),
                            server._current_eu_summer_time())
