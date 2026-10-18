from network import WLAN, STA_IF
from GpioControl.LedControl import led_twinkle, led_error_twinkle
from WebServer.errorlog import CATEGORY_NETWORK, record_exception
import machine, ntptime, time


_SCAN_CACHE_TTL_MS = 30000


class WlanConnection:
    def __init__(self, ssid, key, hostname, error_log=None, logging_settings=None):
        self.__ssid = ssid
        self.__key = key
        self.__hostname = hostname
        self._error_log = error_log
        self._logging_settings = logging_settings
        self._scan_cache = None
        self._scan_cache_time = None

    def isConnected(self):
        wlan = WLAN(STA_IF)
        return wlan.isconnected()

    def disconnect(self):
        try:
            WLAN(STA_IF).disconnect()
        except Exception:
            pass  # not connected/connecting - nothing to stop

    def get_rssi(self):
        try:
            return WLAN(STA_IF).status('rssi')
        except Exception as exc:
            record_exception(self._error_log, CATEGORY_NETWORK, exc, logging_settings=self._logging_settings)
            return None

    def scan_networks(self):
        # Scanning while associated to an AP takes several seconds (it has
        # to briefly leave the connected channel to probe others) - that's
        # uncomfortably close to the watchdog timeout and blocks the whole
        # main loop meanwhile. Caching means repeated page loads only pay
        # that cost once every 30s instead of on every single request.
        now = time.ticks_ms()
        if self._scan_cache is not None and time.ticks_diff(now, self._scan_cache_time) < _SCAN_CACHE_TTL_MS:
            return self._scan_cache

        wlan = WLAN(STA_IF)
        wlan.active(True)
        ssids = []
        for entry in wlan.scan():
            ssid = entry[0]
            if isinstance(ssid, bytes):
                ssid = ssid.decode('utf-8', 'ignore')
            if ssid and ssid not in ssids:
                ssids.append(ssid)

        self._scan_cache = ssids
        self._scan_cache_time = now
        return ssids

    def connect(self):
        if self.isConnected() == True:
            led_twinkle(22, 500)
            led_twinkle(23, 500)
            return True
        print("Start with connection")
        wlan = WLAN(STA_IF)
        print(self.__hostname)
        wlan.active(True)
        # Must be set after active(True) but before connect(), otherwise the
        # DHCP request goes out before the hostname is applied and the
        # router never learns it - which is exactly why this was previously
        # unreachable by name, not just by luck.
        wlan.config(dhcp_hostname=self.__hostname)
        try:
            wlan.connect(self.__ssid, self.__key)
        except Exception as exc:
            print("offline")
            record_exception(self._error_log, CATEGORY_NETWORK, exc, logging_settings=self._logging_settings)
            led_error_twinkle(22, 23, 200, 2)
            return False

        time_to_wait = 10
        time_to_wait_counter = 0
        while not self.isConnected():
            print(str(time_to_wait_counter) + " - waiting...")
            led_twinkle(23, 250)
            machine.idle()
            time_to_wait_counter = time_to_wait_counter + 1
            if time_to_wait_counter == time_to_wait:
                break

        # No NTP sync here: the caller does it right after, in its own
        # watchdog window - waiting for the connection (~5 s) plus NTP with
        # an unanswered DNS lookup (~7 s, measured) came too close to the
        # 15 s watchdog in a single step.
        if self.isConnected() == False:
            led_twinkle(23, 200)
            led_twinkle(23, 200)
            led_twinkle(23, 200)

        return self.isConnected()

    def ensure_time_synced(self):
        # The ESP32's RTC defaults to the year 2000 until NTP sets it. A
        # single failed attempt (e.g. a transient network hiccup right
        # after connecting) used to leave the clock wrong for the rest of
        # the boot session, since this was only ever called once from
        # connect() - and connect() is skipped entirely once isConnected()
        # is already True. Checking the year lets every iteration retry
        # until it actually succeeds.
        if time.gmtime()[0] >= 2020:
            return
        try:
            ntptime.settime()
            print("Local time after synchronization： %s " % str(time.gmtime()))
        except Exception as exc:
            print("NTP sync failed:", exc)
            record_exception(self._error_log, CATEGORY_NETWORK, exc, logging_settings=self._logging_settings)
