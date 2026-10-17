import ujson

from WebServer.datetimeformat import (
    CULTURES, DEFAULT_CULTURE, DEFAULT_UTC_OFFSET_MINUTES, VALID_OFFSET_MINUTES,
)

_PATH = 'datetime_settings.json'


class DateTimeSettings:
    """Persists the Country/Culture date & time display format and the
    fixed UTC offset used throughout the web interface (/settings), so
    both survive a reboot - exactly like the aquarium name or the
    warning thresholds."""

    def __init__(self):
        self._culture = DEFAULT_CULTURE
        self._utc_offset_minutes = DEFAULT_UTC_OFFSET_MINUTES
        try:
            with open(_PATH) as f:
                data = ujson.load(f)
            culture = data.get('culture')
            if culture in CULTURES:
                self._culture = culture
            offset = data.get('utc_offset_minutes')
            if offset in VALID_OFFSET_MINUTES:
                self._utc_offset_minutes = offset
        except (OSError, ValueError):
            pass  # no override file yet, keep the defaults

    def get_culture(self):
        return self._culture

    def get_utc_offset_minutes(self):
        return self._utc_offset_minutes

    def set(self, culture, utc_offset_minutes):
        if culture not in CULTURES:
            raise ValueError("Unbekannte Culture: {}".format(culture))
        if utc_offset_minutes not in VALID_OFFSET_MINUTES:
            raise ValueError("Unbekannter UTC-Offset: {}".format(utc_offset_minutes))
        self._culture = culture
        self._utc_offset_minutes = utc_offset_minutes
        with open(_PATH, 'w') as f:
            ujson.dump({'culture': self._culture, 'utc_offset_minutes': self._utc_offset_minutes}, f)
