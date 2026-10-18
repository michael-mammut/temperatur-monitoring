import time

# Home WLAN unreachable this long (e.g. router slower than the ESP32 after a
# power cut, or it was replaced) -> open the setup network.
FALLBACK_AFTER_MS = 5 * 60 * 1000
# Setup started by a double RESET press keeps the old credentials and goes
# back to them after this long, unless someone saved new ones meanwhile.
BUTTON_SETUP_TIMEOUT_MS = 10 * 60 * 1000
# While the setup network is up after a fallback, retry the home WLAN this
# often - but only while nobody is connected to the setup network, since a
# connection attempt makes the radio hop channels and drops its clients.
HOME_RETRY_INTERVAL_MS = 60 * 1000

REASON_NO_CREDENTIALS = 'no_credentials'
REASON_BUTTON = 'button'
REASON_FALLBACK = 'fallback'


class NetworkSetup:
    """Decides when the device opens its own setup WiFi network
    (WlanNetwork/accesspoint.py) and when it goes back to the home WLAN."""

    def __init__(self, wlan, access_point, has_credentials, setup_requested):
        self._wlan = wlan
        self._access_point = access_point
        self._reason = None
        self._started_at = None
        self._offline_since = None
        self._last_home_attempt = None
        if not has_credentials:
            self._start(REASON_NO_CREDENTIALS)
        elif setup_requested:
            self._start(REASON_BUTTON)

    def is_active(self):
        return self._reason is not None

    def poll(self):
        """Cheap, call often (e.g. while the main loop sleeps): answers
        pending DNS queries of setup-network clients."""
        if self._reason is not None:
            self._access_point.poll_dns()

    def mark_online(self):
        self._offline_since = None

    def mark_offline(self):
        now = time.ticks_ms()
        if self._offline_since is None:
            self._offline_since = now
        elif time.ticks_diff(now, self._offline_since) >= FALLBACK_AFTER_MS:
            self._start(REASON_FALLBACK)

    def update(self):
        if self._reason == REASON_NO_CREDENTIALS:
            return  # nothing to go back to; new credentials reboot the device
        if self._access_point.has_clients():
            return  # someone is configuring right now, don't disturb them
        now = time.ticks_ms()
        if self._reason == REASON_BUTTON:
            if time.ticks_diff(now, self._started_at) >= BUTTON_SETUP_TIMEOUT_MS:
                self._stop()
            return
        if (self._last_home_attempt is not None
                and time.ticks_diff(now, self._last_home_attempt) < HOME_RETRY_INTERVAL_MS):
            return
        self._last_home_attempt = now
        if self._wlan.connect():
            self._stop()
        else:
            self._wlan.disconnect()

    def _start(self, reason):
        self._reason = reason
        self._started_at = time.ticks_ms()
        self._last_home_attempt = None
        # Stop the station's own background reconnect attempts - they make
        # the radio hop channels and keep dropping setup-network clients.
        self._wlan.disconnect()
        self._access_point.start()

    def _stop(self):
        self._access_point.stop()
        self._reason = None
        self._offline_since = None
