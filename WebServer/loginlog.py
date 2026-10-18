import time
import ujson

from WebServer.jsonfile import load_dict

_PATH = 'last_login.json'


class LoginLog:
    """Tracks the timestamp of the last successful admin login, persisted
    across reboots. record_login() returns the *previous* value before
    overwriting it, since the login happening right now would otherwise
    always just show "just now" on the page it is itself about to render."""

    def __init__(self):
        self._last_login = None
        data = load_dict(_PATH)
        if data is not None and isinstance(data.get('timestamp'), (int, float)):
            self._last_login = data['timestamp']

    def get_last_login(self):
        return self._last_login

    def record_login(self):
        previous = self._last_login
        self._last_login = time.time()
        with open(_PATH, 'w') as f:
            ujson.dump({'timestamp': self._last_login}, f)
        return previous
