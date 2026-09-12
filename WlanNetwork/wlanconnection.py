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
        #wlan.config(dhcp_hostname=self.__hostname)
        #print('Connected with DHCP-Hostname: ' + wlan.config('dhcp_hostname') + ' - connection state:' + str(wlan.isconnected()))
        return wlan.isconnected()

    def connect(self):
        if self.isConnected() == True:
            led_twinkle(22, 500)
            led_twinkle(23, 500)
            return True
        print("Start with connection")
        wlan = WLAN(STA_IF)
        print(self.__hostname)
        #wlan.config(dhcp_hostname="asdf")
        wlan.active(True)
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
            ntptime.settime()
            print("Local time after synchronization： %s " % str(time.gmtime()))
        else:
            led_twinkle(23, 200)
            led_twinkle(23, 200)
            led_twinkle(23, 200)

        return self.isConnected()

        