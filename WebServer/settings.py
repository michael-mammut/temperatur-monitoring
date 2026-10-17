import ujson

_PATH = 'aquarium_settings.json'


class Settings:
    """Persists user-editable settings (currently just the aquarium name)
    to a JSON file on flash, so changes made via the /settings web page
    survive a reboot without needing to re-flash config.py."""

    def __init__(self, default_name):
        self._name = default_name
        try:
            with open(_PATH) as f:
                data = ujson.load(f)
            self._name = data.get('name', default_name)
        except OSError:
            pass  # no settings file yet, keep the default

    def get_name(self):
        return self._name

    def set_name(self, name):
        self._name = name
        with open(_PATH, 'w') as f:
            ujson.dump({'name': name}, f)
