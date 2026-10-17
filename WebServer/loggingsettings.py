import ujson

from WebServer.errorlog import ALL_CATEGORIES

_PATH = 'logging_settings.json'


class LoggingSettings:
    """Persists which error categories are allowed to be recorded, so a
    chatty-but-harmless category (e.g. a known-disconnected sensor during
    bench testing) can be switched off via /settings without touching
    code. All categories are enabled by default."""

    def __init__(self):
        self._enabled = {category: True for category in ALL_CATEGORIES}
        try:
            with open(_PATH) as f:
                data = ujson.load(f)
            for category in ALL_CATEGORIES:
                if category in data:
                    self._enabled[category] = bool(data[category])
        except (OSError, ValueError):
            pass  # no override file yet, keep everything enabled

    def is_enabled(self, category):
        return self._enabled.get(category, True)

    def set_enabled(self, enabled_by_category):
        for category in ALL_CATEGORIES:
            if category in enabled_by_category:
                self._enabled[category] = bool(enabled_by_category[category])
        with open(_PATH, 'w') as f:
            ujson.dump(self._enabled, f)
