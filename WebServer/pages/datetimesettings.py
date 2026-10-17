from WebServer.datetimeformat import CULTURES, UTC_OFFSETS, VALID_OFFSET_MINUTES
from WebServer.webstyle import STYLE

_NAV = '<p class="nav"><a href="/">Status</a> | <a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a> | <a href="/statistics">Statistik</a></p>'


def handle_post(server, body):
    if server._datetime_settings is None:
        return render(server)

    culture = server._parse_form_field(body, 'culture')
    try:
        utc_offset_minutes = int(server._parse_form_field(body, 'utc_offset_minutes'))
    except (TypeError, ValueError):
        utc_offset_minutes = None
    eu_summer_time = server._parse_form_field(body, 'eu_summer_time') is not None

    if culture not in CULTURES or utc_offset_minutes not in VALID_OFFSET_MINUTES:
        error = 'Ungültiges Datum-/Zeit-Format oder Zeitzone.'
    else:
        error = None
        server._datetime_settings.set(culture, utc_offset_minutes, eu_summer_time)

    return render(server, saved=(error is None), error=error)


def render(server, saved=False, error=None):
    if server._datetime_settings is None:
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
{style}
<title>Datum/Zeit</title>
</head>
<body>
<div class="card">
<h1>Datum/Zeit</h1>
<p>Nicht konfiguriert.</p>
{nav}
</div>
</body>
</html>
""".format(style=STYLE, nav=_NAV)

    if error:
        message = '<p class="msg err">Fehler: {}</p>'.format(server._escape_html(error))
    elif saved:
        message = '<p class="msg">Gespeichert.</p>'
    else:
        message = ''

    current_culture = server._datetime_settings.get_culture()
    culture_options = []
    for code, label in CULTURES.items():
        selected = ' selected' if code == current_culture else ''
        culture_options.append('<option value="{0}"{1}>{2}</option>'.format(
            code, selected, server._escape_html(label)))

    current_offset = server._datetime_settings.get_utc_offset_minutes()
    offset_options = []
    for minutes, label in UTC_OFFSETS:
        selected = ' selected' if minutes == current_offset else ''
        offset_options.append('<option value="{0}"{1}>{2}</option>'.format(
            minutes, selected, server._escape_html(label)))

    eu_summer_time_checked = ' checked' if server._datetime_settings.get_eu_summer_time() else ''

    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
{style}
<title>Datum/Zeit</title>
</head>
<body>
<div class="card">
<h1>Datum/Zeit</h1>
{message}
<form method="POST" action="/datetime-settings">
<label>Datum-/Zeit-Format:
<select name="culture">
{culture_options}
</select>
</label>
<label>Zeitzone:
<select name="utc_offset_minutes">
{offset_options}
</select>
</label>
<label class="check"><input type="checkbox" name="eu_summer_time" value="1"{eu_dst_checked}> Automatische Sommerzeit (EU-Regel: letzter Sonntag im März/Oktober)</label>
<button type="submit">Speichern</button>
</form>
{nav}
</div>
</body>
</html>
""".format(style=STYLE, message=message, culture_options='\n'.join(culture_options),
           offset_options='\n'.join(offset_options), eu_dst_checked=eu_summer_time_checked, nav=_NAV)
