import ujson

from WebServer.jsonfile import load_dict

_PATH = 'monitoring_settings.json'

MIN_WARNING_PERCENT = 5
MAX_WARNING_PERCENT = 50


class MonitoringSettings:
    """Persists the RAM/Flash free-space warning thresholds and the max.
    log storage share entered via the /settings page to a JSON file on
    flash, so a change survives a reboot without re-flashing
    Monitoring/config.py."""

    def __init__(self, default_ram_percent, default_storage_percent, default_log_storage_percent):
        self._ram_percent = default_ram_percent
        self._storage_percent = default_storage_percent
        self._log_storage_percent = default_log_storage_percent
        data = load_dict(_PATH)  # None: no override file yet, or unreadable
        if data is None:
            return
        # Same check as for values entered on /settings - a non-number here
        # would make every RAM/Flash check of the main loop fail.
        self._ram_percent = _valid_or(data.get('ram_percent'), default_ram_percent)
        self._storage_percent = _valid_or(data.get('storage_percent'), default_storage_percent)
        self._log_storage_percent = _valid_or(data.get('log_storage_percent'), default_log_storage_percent)

    def get_ram_percent(self):
        return self._ram_percent

    def get_storage_percent(self):
        return self._storage_percent

    def get_log_storage_percent(self):
        return self._log_storage_percent

    def set_thresholds(self, ram_percent, storage_percent, log_storage_percent):
        self._ram_percent = ram_percent
        self._storage_percent = storage_percent
        self._log_storage_percent = log_storage_percent
        with open(_PATH, 'w') as f:
            ujson.dump({
                'ram_percent': ram_percent,
                'storage_percent': storage_percent,
                'log_storage_percent': log_storage_percent,
            }, f)


def _valid_or(value, default):
    error, number = validate_percent(value)
    return default if error else number


def validate_percent(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Wert muss eine Zahl sein.", None
    if number < MIN_WARNING_PERCENT or number > MAX_WARNING_PERCENT:
        return "Wert muss zwischen {} und {} liegen.".format(MIN_WARNING_PERCENT, MAX_WARNING_PERCENT), None
    return None, number
