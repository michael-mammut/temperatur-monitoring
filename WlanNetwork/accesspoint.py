import network
from machine import Pin, Timer

from WlanNetwork.dnsserver import CatchAllDnsServer

AP_SSID = 'Captain-Nemo-Setup'
# WPA2 requires at least 8 characters - a shorter password would either be
# rejected or silently leave the network open.
AP_PASSWORD = '12345678'
AP_IP = '192.168.4.1'
# Name the setup page is reachable under (resolved by WlanNetwork/dnsserver.py).
AP_HOSTNAME = 'captain-nemo-setup'

# On-board LED of most ESP32 DevKit boards; not used by anything else here.
STATUS_LED_GPIO = 2
# Toggled every 500 ms = one blink per second. A hardware timer, because
# one main loop iteration takes several seconds (sensors + sleep).
_BLINK_TOGGLE_MS = 500


class SetupAccessPoint:
    """The device's own WiFi network for (re)configuring the home WLAN,
    with the status LED blinking while it is up."""

    def __init__(self, led_gpio=STATUS_LED_GPIO, timer_id=0):
        self._led_gpio = led_gpio
        self._timer_id = timer_id
        self._timer = None
        self._led = None
        self._active = False
        self._dns = CatchAllDnsServer(AP_IP)

    def is_active(self):
        return self._active

    def start(self):
        if self._active:
            return
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        # Must come after active(True), otherwise the ESP32 ignores it.
        ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=network.AUTH_WPA2_PSK)
        self._active = True
        self._dns.start()
        self._start_blinking()
        print("Setup-WLAN aktiv:", AP_SSID, "http://%s/" % AP_HOSTNAME)

    def stop(self):
        if not self._active:
            return
        self._dns.stop()
        network.WLAN(network.AP_IF).active(False)
        self._active = False
        self._stop_blinking()
        print("Setup-WLAN beendet")

    def poll_dns(self):
        self._dns.poll()

    def has_clients(self):
        try:
            return len(network.WLAN(network.AP_IF).status('stations')) > 0
        except Exception:
            return False

    def _start_blinking(self):
        self._led = Pin(self._led_gpio, Pin.OUT)
        self._timer = Timer(self._timer_id)
        self._timer.init(period=_BLINK_TOGGLE_MS, mode=Timer.PERIODIC, callback=self._toggle_led)

    def _stop_blinking(self):
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None
        if self._led is not None:
            self._led.off()

    def _toggle_led(self, _timer):
        self._led.value(not self._led.value())
