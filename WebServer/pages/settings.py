from WebServer.errorlog import ALL_CATEGORIES, CATEGORY_LABELS
from WebServer.webstyle import STYLE


def handle_post(server, monitor, body):
    name = server._parse_form_field(body, 'name')
    ram_value = storage_value = log_storage_value = None
    error = None

    if server._monitoring_settings is not None:
        from Monitoring.settings import validate_percent
        ram_error, ram_value = validate_percent(server._parse_form_field(body, 'ram_percent'))
        storage_error, storage_value = validate_percent(server._parse_form_field(body, 'storage_percent'))
        log_storage_error, log_storage_value = validate_percent(
            server._parse_form_field(body, 'log_storage_percent'))
        error = ram_error or storage_error or log_storage_error

    if not error:
        if name and name.strip():
            name = name.strip()[:64]
            server._settings.set_name(name)
            monitor.telegram.set_project_name(name)
        if server._monitoring_settings is not None:
            server._monitoring_settings.set_thresholds(ram_value, storage_value, log_storage_value)
        if server._logging_settings is not None:
            enabled_by_category = {
                category: server._parse_form_field(body, 'log_' + category) is not None
                for category in ALL_CATEGORIES
            }
            server._logging_settings.set_enabled(enabled_by_category)

    return render(server, saved=(error is None), error=error)


def render(server, saved=False, error=None):
    name = server._escape_html(server._settings.get_name())
    if error:
        message = '<p class="msg err">Fehler: {}</p>'.format(server._escape_html(error))
    elif saved:
        message = '<p class="msg">Gespeichert.</p>'
    else:
        message = ''

    monitoring_fields = ''
    if server._monitoring_settings is not None:
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
            ram=server._monitoring_settings.get_ram_percent(),
            storage=server._monitoring_settings.get_storage_percent(),
            log_storage=server._monitoring_settings.get_log_storage_percent(),
            min=MIN_WARNING_PERCENT, max=MAX_WARNING_PERCENT,
        )

    logging_fields = ''
    if server._logging_settings is not None:
        checkboxes = []
        for category in ALL_CATEGORIES:
            checked = ' checked' if server._logging_settings.is_enabled(category) else ''
            checkboxes.append(
                '<label class="check"><input type="checkbox" name="log_{cat}" value="1"{checked}> {label}</label>'.format(
                    cat=category, checked=checked, label=server._escape_html(CATEGORY_LABELS[category])))
        logging_fields = '<p>Fehlerprotokollierung:</p>\n' + '\n'.join(checkboxes)

    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
{style}
<title>Einstellungen</title>
</head>
<body>
<div class="card">
<h1>Einstellungen</h1>
{message}
<form method="POST" action="/settings">
<label>Aquarium-Name: <input type="text" name="name" value="{name}" maxlength="64"></label>
{monitoring_fields}
{logging_fields}
<button type="submit">Speichern</button>
</form>
<p class="nav"><a href="/">Status</a> | <a href="/wifi-settings">WLAN</a> | <a href="/datetime-settings">Datum/Zeit</a> | <a href="/statistics">Statistik</a></p>
</div>
</body>
</html>
""".format(style=STYLE, message=message, name=name, monitoring_fields=monitoring_fields,
           logging_fields=logging_fields)
