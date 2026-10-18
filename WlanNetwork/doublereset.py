import os
import time

# Pressing the board's RESET (EN) button cannot be told apart from a power
# cut by software - both look like a fresh power-on to the ESP32. So a
# single press must stay a plain reboot (otherwise every power outage would
# drop the home WiFi). Two presses in quick succession are the signal
# instead: the first boot leaves a marker file on flash for a short window,
# and a second boot that still finds it knows RESET was pressed again.
#
# This runs from boot.py, before main.py imports the whole project -
# otherwise those imports (several seconds on the ESP32) would push the
# window so far back that a natural double press would be missed.

_MARKER_PATH = 'reset_marker'
_REQUEST_PATH = 'setup_request'
WINDOW_MS = 3000


def check_double_reset(window_ms=WINDOW_MS, sleep_ms=None):
    if sleep_ms is None:
        sleep_ms = time.sleep_ms
    if _exists(_MARKER_PATH):
        _remove(_MARKER_PATH)
        _touch(_REQUEST_PATH)
        return True
    _touch(_MARKER_PATH)
    try:
        sleep_ms(window_ms)
    finally:
        # Also on KeyboardInterrupt (deploy script interrupting the boot),
        # otherwise the next boot would mistake it for a second press.
        _remove(_MARKER_PATH)
    return False


def consume_setup_request():
    """True exactly once after a detected double reset."""
    if _exists(_REQUEST_PATH):
        _remove(_REQUEST_PATH)
        return True
    return False


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _touch(path):
    with open(path, 'w') as f:
        f.write('1')


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
