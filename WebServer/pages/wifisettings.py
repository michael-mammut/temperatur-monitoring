from WebServer.webstyle import STYLE


def handle_post(server, monitor, body):
    from WlanNetwork.wifisettings import validate_ssid, validate_password

    ssid = server._parse_form_field(body, 'ssid') or ''
    password = server._parse_form_field(body, 'password') or ''

    error = validate_ssid(ssid) or validate_password(password)
    if error:
        return render(server, monitor, error=error, ssid=ssid), False

    server._wifi_settings.set_credentials(ssid, password)
    html = render(server, monitor, saved=True, ssid=ssid)
    return html, True


def render(server, monitor, saved=False, error=None, ssid=None):
    current_ssid = server._escape_html(server._wifi_settings.get_ssid())
    options = _render_network_options(server, monitor, selected=ssid)
    if saved:
        message = ('<p class="msg">Gespeichert. Das Gerät verbindet sich jetzt neu - '
                    'sollte das fehlschlagen, muss es per USB neu konfiguriert werden.</p>')
    elif error:
        message = '<p class="msg err">Fehler: {}</p>'.format(server._escape_html(error))
    else:
        message = ''
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
{style}
<title>WLAN-Einstellungen</title>
</head>
<body>
<div class="card">
<h1>WLAN-Einstellungen</h1>
<p>Aktuell konfiguriert: {current_ssid}</p>
{message}
<form method="POST" action="/wifi-settings">
<label>Netzwerk:
<select name="ssid">
{options}
</select>
</label>
<label>Passwort: <input type="password" name="password" maxlength="63" autocomplete="new-password"></label>
<button type="submit">Verbinden</button>
</form>
<p class="nav"><a href="/">Status</a> | <a href="/settings">Einstellungen</a> | <a href="/datetime-settings">Datum/Zeit</a> | <a href="/statistics">Statistik</a></p>
</div>
</body>
</html>
""".format(style=STYLE, current_ssid=current_ssid, options=options, message=message)


def _render_network_options(server, monitor, selected=None):
    try:
        ssids = monitor.wlan.scan_networks()
    except Exception:
        ssids = []
    if not ssids:
        return '<option value="">Keine Netzwerke gefunden</option>'
    options = []
    for ssid in ssids:
        escaped = server._escape_html(ssid)
        is_selected = ' selected' if ssid == selected else ''
        options.append('<option value="{0}"{1}>{0}</option>'.format(escaped, is_selected))
    return '\n'.join(options)
