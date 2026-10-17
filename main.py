import gc
import time

import machine
from machine import WDT

from Temperature import config as temperature_config
from GpioControl.ActorControl import ActorControl
from GpioControl import config as actor_config
from GpioControl.LedControl import led_error_twinkle, led_twinkle
from Notification.telegram import Telegram
from Temperature.temperature import Temperature
from WlanNetwork.wlanconnection import WlanConnection
from WlanNetwork.wifisettings import WifiSettings
from WlanNetwork import config as wlan_config
from Airpump import config as air_pump_config
from Monitoring.settings import MonitoringSettings
from Monitoring import config as monitoring_config
from WebServer.statusserver import StatusServer
from WebServer.settings import Settings
from WebServer.eventlog import EventLog, enforce_storage_budget
from WebServer.loginlog import LoginLog
from WebServer.errorlog import CATEGORY_SYSTEM, record_exception
from WebServer.loggingsettings import LoggingSettings
from WebServer.systemstats import format_bytes, free_percent, get_memory_stats, get_storage_stats
from WebServer import config as webserver_config
import config as project_config

WATCHDOG_TIMEOUT_MS = 15000


class AquariumMonitor:
    def __init__(self):
        self.pin_K4_5_volt_free = ActorControl(actor_config.ACTOR_GPIO_FREE)
        self.pin_K3_5_volt_air_pump = ActorControl(actor_config.ACTOR_GPIO_AIR_PUMP)
        self.pin_K2_12_volt_fan = ActorControl(actor_config.ACTOR_GPIO_FAN)
        self.pin_K1_12_volt_wlan = ActorControl(actor_config.ACTOR_GPIO_WLAN)

        self.error_log = EventLog('error_log.json')
        self.notification_log = EventLog('notification_log.json')
        self.login_log = LoginLog()
        self.logging_settings = LoggingSettings()
        self.monitoring_settings = MonitoringSettings(
            monitoring_config.RAM_FREE_WARNING_PERCENT, monitoring_config.STORAGE_FREE_WARNING_PERCENT,
            monitoring_config.MAX_LOG_STORAGE_PERCENT)

        self.wifi_settings = WifiSettings(wlan_config.SSID, wlan_config.PASSWORD)
        self.wlan = WlanConnection(
            self.wifi_settings.get_ssid(), self.wifi_settings.get_password(), wlan_config.DHCP_HOSTNAME,
            error_log=self.error_log, logging_settings=self.logging_settings)
        self.settings = Settings(project_config.AQUARIUM_NAME)
        self.telegram = Telegram(
            self.settings.get_name(), error_log=self.error_log, notification_log=self.notification_log,
            logging_settings=self.logging_settings)
        self.ambient_sensor = Temperature(
            temperature_config.ONE_WIRE_GPIO_AMBIENT, error_log=self.error_log, logging_settings=self.logging_settings)
        self.water_sensor = Temperature(
            temperature_config.ONE_WIRE_GPIO_WATER, error_log=self.error_log, logging_settings=self.logging_settings)

        self.air_pump_state = False
        self.first_run = True
        self.message_send_counter = 0
        self.last_water_temperature = None
        self.last_ambient_temperature = None
        self.last_measurement_time = None
        self._ram_low_notified = False
        self._storage_low_notified = False

    def run_iteration(self):
        if self.wlan.isConnected() == False:
            print("Main-Script is online")
            self.pin_K1_12_volt_wlan.on()
            if self.wlan.connect() == True:
                print("Main-Script is now online")
                self.pin_K1_12_volt_wlan.off()
        else:
            self.wlan.ensure_time_synced()

        hour = time.gmtime()[3]

        ambient_temperature = self.ambient_sensor.readCurrentAverage()
        water_temperature = self.water_sensor.readCurrentAverage()
        self.last_ambient_temperature = ambient_temperature
        self.last_water_temperature = water_temperature
        self.last_measurement_time = time.gmtime()

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

        self._enforce_log_storage_budget()

        if self.wlan.isConnected() == True:
            self.message_send_counter = self.telegram.send_aquarium_notification(
                ambient_temperature, water_temperature, self.first_run, self.message_send_counter)
            self.first_run = False
            self._check_resource_usage()

        led_twinkle(22, 75)

    def _enforce_log_storage_budget(self):
        try:
            free_bytes = get_storage_stats()['free']
        except Exception:
            return
        enforce_storage_budget(
            [self.error_log, self.notification_log], self.monitoring_settings.get_log_storage_percent(), free_bytes)

    def _check_resource_usage(self):
        self._check_threshold(
            get_memory_stats(), 'RAM', self.monitoring_settings.get_ram_percent(), '_ram_low_notified')
        try:
            storage = get_storage_stats()
        except Exception:
            return
        self._check_threshold(
            storage, 'Flash', self.monitoring_settings.get_storage_percent(), '_storage_low_notified')

    def _check_threshold(self, stats, label, threshold_percent, flag_name):
        percent_free = free_percent(stats)
        if percent_free < threshold_percent:
            if not getattr(self, flag_name):
                self.telegram.notify(
                    "Warnung: {} nur noch {:.0f}% frei ({} von {} belegt)".format(
                        label, percent_free, format_bytes(stats['used']), format_bytes(stats['total'])))
                setattr(self, flag_name, True)
        else:
            setattr(self, flag_name, False)


def main():
    print("+++++ START ++++++")
    monitor = AquariumMonitor()
    wdt = WDT(timeout=WATCHDOG_TIMEOUT_MS)
    web_server = StatusServer(
        webserver_config.PORT,
        monitor.settings,
        monitor.wifi_settings,
        webserver_config.ADMIN_PASSWORD,
        reset_callback=machine.reset,
        error_log=monitor.error_log,
        notification_log=monitor.notification_log,
        login_log=monitor.login_log,
        monitoring_settings=monitor.monitoring_settings,
        logging_settings=monitor.logging_settings,
    )
    print("----- LOOP START ------")
    while True:
        try:
            monitor.run_iteration()
        except Exception as exc:
            print("Loop iteration failed:", exc)
            record_exception(monitor.error_log, CATEGORY_SYSTEM, exc, logging_settings=monitor.logging_settings)
            led_error_twinkle(22, 23, 150, 3)
        try:
            web_server.handle_requests(monitor)
        except Exception as exc:
            print("Web server failed:", exc)
            record_exception(monitor.error_log, CATEGORY_SYSTEM, exc, logging_settings=monitor.logging_settings)
        wdt.feed()
        time.sleep_ms(3000)
        gc.collect()


if __name__ == "__main__":
    main()
