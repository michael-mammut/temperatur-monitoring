import time
import ujson

from Temperature.temperature import SENSOR_ERROR

_PATH = 'sensor_alert_settings.json'

# While a sensor stays failed, remind via Telegram this often.
REMINDER_INTERVAL_MS = 12 * 60 * 60 * 1000
# Failed reads in a row before a sensor counts as failed - a single bad
# read (e.g. one CRC error) is not worth a message.
FAILURE_CONFIRM_READINGS = 3
# A failed sensor only counts as recovered after delivering values this
# long without interruption. Counting good reads instead would let a
# flaky connector (alternating good/bad reads) send warning + all-clear
# on every few loop iterations.
RECOVERY_STABLE_MS = 10 * 60 * 1000
# After a failed send (e.g. internet down while WLAN is up) wait this long
# before trying again, instead of retrying on every loop iteration.
RETRY_AFTER_FAILURE_MS = 5 * 60 * 1000


class SensorAlertSettings:
    """Persists whether sensor failures are reported via Telegram (on by
    default, switchable via /settings)."""

    def __init__(self):
        self._enabled = True
        try:
            with open(_PATH) as f:
                data = ujson.load(f)
            value = data.get('enabled', True)
            if isinstance(value, bool):
                self._enabled = value
        except (OSError, ValueError, AttributeError):
            pass  # no/corrupt file, keep the default

    def is_enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be True or False")
        self._enabled = enabled
        with open(_PATH, 'w') as f:
            ujson.dump({'enabled': enabled}, f)


class _SensorState:
    def __init__(self):
        self.failed = False
        self.error_streak = 0
        self.ok_since = None
        self.last_warning = None
        self.recovery_pending = False


class SensorAlert:
    """Telegram message when a temperature sensor fails, a reminder every
    12 h while it stays failed, and an all-clear once it works again."""

    def __init__(self, telegram, settings=None):
        self._telegram = telegram
        self._settings = settings
        self._states = {}
        self._retry_at = None

    def update(self, label, value, online, hint=''):
        state = self._states.get(label)
        if state is None:
            state = self._states[label] = _SensorState()
        now = time.ticks_ms()
        self._track(state, value, now)

        if self._settings is not None and not self._settings.is_enabled():
            state.recovery_pending = False
            return
        if not online:
            return  # sent later, once the device is online again
        if self._retry_at is not None and time.ticks_diff(now, self._retry_at) < 0:
            return

        if state.failed:
            if state.last_warning is None or time.ticks_diff(now, state.last_warning) >= REMINDER_INTERVAL_MS:
                if self._send("Warnung: {} liefert keine Messwerte (Sensorfehler).{} "
                              "Erinnerung alle 12 h, solange der Fehler anhält.".format(label, hint), now):
                    state.last_warning = now
        elif state.recovery_pending:
            if self._send("Entwarnung: {} liefert wieder Messwerte ({}°C).".format(label, value), now):
                state.recovery_pending = False

    def _track(self, state, value, now):
        if value == SENSOR_ERROR:
            state.ok_since = None
            state.error_streak += 1
            if not state.failed and state.error_streak >= FAILURE_CONFIRM_READINGS:
                state.failed = True
                state.last_warning = None
                state.recovery_pending = False
            return
        state.error_streak = 0
        if not state.failed:
            return
        if state.ok_since is None:
            state.ok_since = now
        elif time.ticks_diff(now, state.ok_since) >= RECOVERY_STABLE_MS:
            state.failed = False
            state.ok_since = None
            state.recovery_pending = state.last_warning is not None

    def _send(self, text, now):
        if self._telegram.notify(self._telegram._project_name + " - " + text):
            self._retry_at = None
            return True
        self._retry_at = time.ticks_add(now, RETRY_AFTER_FAILURE_MS)
        return False
