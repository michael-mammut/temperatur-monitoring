import time
import ujson

_PATH = 'last_login.json'


class LoginLog:
    """Tracks the timestamp of the last successful admin login, persisted
    across reboots. record_login() returns the *previous* value before
    overwriting it, since the login happening right now would otherwise
    always just show "just now" on the page it is itself about to render."""

    def __init__(self):
        self._last_login = None
        try:
            with open(_PATH) as f:
                self._last_login = ujson.load(f).get('timestamp')
        except (OSError, ValueError):
            pass

    def get_last_login(self):
        return self._last_login

    def record_login(self):
        previous = self._last_login
        self._last_login = time.time()
        with open(_PATH, 'w') as f:
            ujson.dump({'timestamp': self._last_login}, f)
        return previous
