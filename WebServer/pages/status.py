from WebServer.datetimeformat import format_datetime
from WebServer.webstyle import STYLE


def render(server, monitor):
    water = _format_temperature(monitor.last_water_temperature)
    ambient = _format_temperature(monitor.last_ambient_temperature)
    name = server._escape_html(monitor.telegram._project_name)
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
{style}
<title>{name}</title>
</head>
<body>
<div class="card">
<h1>{name}</h1>
<p>Status: online</p>
<p>Wassertemperatur: {water} &deg;C</p>
<p>Umgebungstemperatur: {ambient} &deg;C</p>
<p>Letzte Messung: {updated}</p>
<p class="nav"><a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a> | <a href="/datetime-settings">Datum/Zeit</a> | <a href="/statistics">Statistik</a></p>
</div>
</body>
</html>
""".format(
        style=STYLE,
        name=name,
        water=water,
        ambient=ambient,
        updated=_format_time(server, monitor.last_measurement_time),
    )


def _format_temperature(value):
    if value is None or value == -999:
        return "n/a"
    return str(value)


def _format_time(server, value):
    if value is None:
        return "n/a"
    return format_datetime(value, server._current_culture(), server._current_utc_offset(),
                            server._current_eu_summer_time())
