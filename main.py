import gc
import time

from machine import WDT

from Temperature import config as temperature_config
from GpioControl.ActorControl import ActorControl
from GpioControl import config as actor_config
from GpioControl.LedControl import led_error_twinkle, led_twinkle
from Notification.telegram import Telegram
from Temperature.temperature import Temperature
from WlanNetwork.wlanconnection import WlanConnection
from WlanNetwork import config as wlan_config
from Airpump import config as air_pump_config
import config as project_config

WATCHDOG_TIMEOUT_MS = 15000


class AquariumMonitor:
    def __init__(self):
        self.pin_K4_5_volt_free = ActorControl(actor_config.ACTOR_GPIO_FREE)
        self.pin_K3_5_volt_air_pump = ActorControl(actor_config.ACTOR_GPIO_AIR_PUMP)
        self.pin_K2_12_volt_fan = ActorControl(actor_config.ACTOR_GPIO_FAN)
        self.pin_K1_12_volt_wlan = ActorControl(actor_config.ACTOR_GPIO_WLAN)

        self.wlan = WlanConnection(wlan_config.SSID, wlan_config.PASSWORD, wlan_config.DHCP_HOSTNAME)
        self.telegram = Telegram(project_config.AQUARIUM_NAME)
        self.ambient_sensor = Temperature(temperature_config.ONE_WIRE_GPIO_AMBIENT)
        self.water_sensor = Temperature(temperature_config.ONE_WIRE_GPIO_WATER)

        self.air_pump_state = False
        self.first_run = True
        self.message_send_counter = 0

    def run_iteration(self):
        if self.wlan.isConnected() == False:
            print("Main-Script is online")
            self.pin_K1_12_volt_wlan.on()
            if self.wlan.connect() == True:
                print("Main-Script is now online")
                self.pin_K1_12_volt_wlan.off()

        hour = time.gmtime()[3]

        ambient_temperature = self.ambient_sensor.readCurrentAverage()
        water_temperature = self.water_sensor.readCurrentAverage()

        if hour == air_pump_config.AIR_PUMP_ON and self.air_pump_state == False:
            self.pin_K3_5_volt_air_pump.off()
            self.air_pump_state = True

        if hour == air_pump_config.AIR_PUMP_OFF and self.air_pump_state == True:
            self.pin_K3_5_volt_air_pump.on()
            self.air_pump_state = False

        if water_temperature > temperature_config.TEMPERATURE_MAX:
            self.pin_K2_12_volt_fan.off()
        elif water_temperature < temperature_config.TEMPERATURE_MIN:
            self.pin_K2_12_volt_fan.on()

        if self.wlan.isConnected() == True:
            self.message_send_counter = self.telegram.send_aquarium_notification(
                ambient_temperature, water_temperature, self.first_run, self.message_send_counter)
            self.first_run = False

        led_twinkle(22, 75)


def main():
    print("+++++ START ++++++")
    monitor = AquariumMonitor()
    wdt = WDT(timeout=WATCHDOG_TIMEOUT_MS)
    print("----- LOOP START ------")
    while True:
        try:
            monitor.run_iteration()
        except Exception as exc:
            print("Loop iteration failed:", exc)
            led_error_twinkle(22, 23, 150, 3)
        wdt.feed()
        time.sleep_ms(3000)
        gc.collect()


if __name__ == "__main__":
    main()
