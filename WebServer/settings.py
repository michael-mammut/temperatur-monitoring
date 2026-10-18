import ujson

from WebServer.jsonfile import load_dict

_PATH = 'aquarium_settings.json'


class Settings:
    """Persists user-editable settings (currently just the aquarium name)
    to a JSON file on flash, so changes made via the /settings web page
    survive a reboot without needing to re-flash config.py."""

    def __init__(self, default_name):
        self._name = default_name
        data = load_dict(_PATH)  # None: no settings file yet, or unreadable
        if data is not None and isinstance(data.get('name'), str) and data['name'].strip():
            self._name = data['name']

    def get_name(self):
        return self._name

    def set_name(self, name):
        self._name = name
        with open(_PATH, 'w') as f:
            ujson.dump({'name': name}, f)
