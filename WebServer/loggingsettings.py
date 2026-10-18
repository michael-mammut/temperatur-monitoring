import ujson

from WebServer.errorlog import ALL_CATEGORIES
from WebServer.jsonfile import load_dict

_PATH = 'logging_settings.json'


class LoggingSettings:
    """Persists which error categories are allowed to be recorded, so a
    chatty-but-harmless category (e.g. a known-disconnected sensor during
    bench testing) can be switched off via /settings without touching
    code. All categories are enabled by default."""

    def __init__(self):
        self._enabled = {category: True for category in ALL_CATEGORIES}
        data = load_dict(_PATH)  # None: no override file yet, or unreadable
        if data is None:
            return
        for category in ALL_CATEGORIES:
            if isinstance(data.get(category), bool):
                self._enabled[category] = data[category]

    def is_enabled(self, category):
        return self._enabled.get(category, True)

    def set_enabled(self, enabled_by_category):
        for category in ALL_CATEGORIES:
            if category in enabled_by_category:
                self._enabled[category] = bool(enabled_by_category[category])
        with open(_PATH, 'w') as f:
            ujson.dump(self._enabled, f)
