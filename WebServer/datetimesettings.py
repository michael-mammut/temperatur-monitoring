import ujson

from WebServer.jsonfile import load_dict

from WebServer.datetimeformat import (
    CULTURES, DEFAULT_CULTURE, DEFAULT_UTC_OFFSET_MINUTES, VALID_OFFSET_MINUTES,
)

_PATH = 'datetime_settings.json'

DEFAULT_EU_SUMMER_TIME = False


class DateTimeSettings:
    """Persists the Country/Culture date & time display format, the
    fixed UTC offset, and whether the EU summer-time rule is applied on
    top of it - all used throughout the web interface (/settings), so
    they survive a reboot - exactly like the aquarium name or the
    warning thresholds."""

    def __init__(self):
        self._culture = DEFAULT_CULTURE
        self._utc_offset_minutes = DEFAULT_UTC_OFFSET_MINUTES
        self._eu_summer_time = DEFAULT_EU_SUMMER_TIME
        data = load_dict(_PATH)  # None: no override file yet, or unreadable
        if data is None:
            return
        culture = data.get('culture')
        if culture in CULTURES:
            self._culture = culture
        offset = data.get('utc_offset_minutes')
        if offset in VALID_OFFSET_MINUTES:
            self._utc_offset_minutes = offset
        if isinstance(data.get('eu_summer_time'), bool):  # bool("false") would be True
            self._eu_summer_time = data['eu_summer_time']

    def get_culture(self):
        return self._culture

    def get_utc_offset_minutes(self):
        return self._utc_offset_minutes

    def get_eu_summer_time(self):
        return self._eu_summer_time

    def set(self, culture, utc_offset_minutes, eu_summer_time):
        if culture not in CULTURES:
            raise ValueError("Unbekannte Culture: {}".format(culture))
        if utc_offset_minutes not in VALID_OFFSET_MINUTES:
            raise ValueError("Unbekannter UTC-Offset: {}".format(utc_offset_minutes))
        self._culture = culture
        self._utc_offset_minutes = utc_offset_minutes
        self._eu_summer_time = bool(eu_summer_time)
        with open(_PATH, 'w') as f:
            ujson.dump({
                'culture': self._culture,
                'utc_offset_minutes': self._utc_offset_minutes,
                'eu_summer_time': self._eu_summer_time,
            }, f)
