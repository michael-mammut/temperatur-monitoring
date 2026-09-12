import gc
import time
import json
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

print("+++++ START ++++++")
pin_K4_5_volt_free = ActorControl(actor_config.ACTOR_GPIO_FREE)
pin_K3_5_volt_air_pump = ActorControl(actor_config.ACTOR_GPIO_AIR_PUMP)
pin_K2_12_volt_fan = ActorControl(actor_config.ACTOR_GPIO_FAN)
pin_K1_12_volt_wlan = ActorControl(actor_config.ACTOR_GPIO_WLAN)

air_pump_state = False
air_cooler_state = False

first_run = True
message_send_counter = 0

wlan = WlanConnection(wlan_config.SSID, wlan_config.PASSWORD, wlan_config.DHCP_HOSTNAME)
print("----- LOOP START ------")
while True:
    if wlan.isConnected() == False:
        print("Main-Script is online")
        pin_K1_12_volt_wlan.on()
        if wlan.connect() == True:
            print("Main-Script is now online")
            pin_K1_12_volt_wlan.off()

    hour = time.gmtime()[3]

    # measure temperature
    ambient = Temperature(temperature_config.ONE_WIRE_GPIO_AMBIENT)
    ambient_temperature = ambient.readCurrentAverage()

    water = Temperature(temperature_config.ONE_WIRE_GPIO_WATER)
    water_temperature = water.readCurrentAverage()

    # air pump
    if hour == air_pump_config.AIR_PUMP_ON and air_pump_state == False:
        pin_K3_5_volt_air_pump.off()
        air_pump_state = True

    if hour == air_pump_config.AIR_PUMP_OFF and air_pump_state == True:
        pin_K3_5_volt_air_pump.on()
        air_pump_state = False

    # set relais by temperature value
    if water_temperature > temperature_config.TEMPERATURE_MAX:
        pin_K2_12_volt_fan.off()
        air_cooler_state = True

    elif water_temperature < temperature_config.TEMPERATURE_MIN:
        pin_K2_12_volt_fan.on()
        air_cooler_state = False
    else:
        pass

    # time of sending temperature notification
    if wlan.isConnected() == True:
        telegram = Telegram(project_config.AQUARIUM_NAME)
        message_send_counter = telegram.send_aquarium_notification(ambient_temperature, water_temperature, first_run, message_send_counter)
        first_run = False

    led_twinkle(22, 75)
    time.sleep_ms(3000)
    gc.collect()
