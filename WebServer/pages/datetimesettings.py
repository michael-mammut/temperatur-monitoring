from WebServer.datetimeformat import CULTURES, UTC_OFFSETS, VALID_OFFSET_MINUTES
from WebServer.webstyle import STYLE, html_parts

_NAV = '<p class="nav"><a href="/">Status</a> | <a href="/settings">Einstellungen</a> | <a href="/wifi-settings">WLAN</a> | <a href="/statistics">Statistik</a></p>'


def handle_post(server, body):
    if server._datetime_settings is None:
        return render_parts(server)

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

    return render_parts(server, saved=(error is None), error=error)


def render(server, saved=False, error=None):
    return ''.join(render_parts(server, saved=saved, error=error))


def render_parts(server, saved=False, error=None):
    """The page as a list of pieces the web server sends one after another.
    Built as one string (~45 dropdown options) it needs ~6 KB in one piece,
    which the ESP32's fragmented heap could not provide on MicroPython 1.16
    (reproduced on real hardware) - as pieces, the largest is the shared
    STYLE constant, which is already in memory anyway."""
    if server._datetime_settings is None:
        return html_parts("""<!DOCTYPE html>
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
""", nav=_NAV)

    if error:
        message = '<p class="msg err">Fehler: {}</p>'.format(server._escape_html(error))
    elif saved:
        message = '<p class="msg">Gespeichert.</p>'
    else:
        message = ''

    parts = ['<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n', STYLE,
             '\n<title>Datum/Zeit</title>\n</head>\n<body>\n<div class="card">\n<h1>Datum/Zeit</h1>\n',
             message,
             '\n<form method="POST" action="/datetime-settings">\n'
             '<label>Datum-/Zeit-Format:\n<select name="culture">\n']

    current_culture = server._datetime_settings.get_culture()
    for code, label in CULTURES.items():
        selected = ' selected' if code == current_culture else ''
        parts.append('<option value="{0}"{1}>{2}</option>\n'.format(code, selected, server._escape_html(label)))

    parts.append('</select>\n</label>\n<label>Zeitzone:\n<select name="utc_offset_minutes">\n')
    current_offset = server._datetime_settings.get_utc_offset_minutes()
    for minutes, label in UTC_OFFSETS:
        selected = ' selected' if minutes == current_offset else ''
        parts.append('<option value="{0}"{1}>{2}</option>\n'.format(minutes, selected, server._escape_html(label)))

    eu_summer_time_checked = ' checked' if server._datetime_settings.get_eu_summer_time() else ''
    parts.append('</select>\n</label>\n'
                 '<label class="check"><input type="checkbox" name="eu_summer_time" value="1"{}> '
                 'Automatische Sommerzeit (EU-Regel: letzter Sonntag im März/Oktober)</label>\n'
                 '<button type="submit">Speichern</button>\n</form>\n'.format(eu_summer_time_checked))
    parts.append(_NAV + '\n</div>\n</body>\n</html>\n')
    return parts
