from network import WLAN, STA_IF
from GpioControl.LedControl import led_twinkle, led_error_twinkle
import machine, ntptime, time


class WlanConnection:
    def __init__(self, ssid, key, hostname):
        self.__ssid = ssid
        self.__key = key
        self.__hostname = hostname

    def isConnected(self):
        wlan = WLAN(STA_IF)
        return wlan.isconnected()

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
        except:
            print("offline")
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

        if self.isConnected() == True:
            self.ensure_time_synced()
        else:
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

        