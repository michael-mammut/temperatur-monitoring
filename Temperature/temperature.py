from machine import Pin
from WebServer.errorlog import CATEGORY_HARDWARE, record_exception
import array, ds18x20, onewire, time

# Returned by readCurrentAverage() when no sensor value could be read.
SENSOR_ERROR = -999

class Temperature:
    def __init__(self, gpio, error_log=None, logging_settings=None):
        self.__gpio = gpio
        self._error_log = error_log
        self._logging_settings = logging_settings

    def readCurrentAverage(self):
        temperature_list = array.array('f', [])
        dat = Pin(self.__gpio, Pin.IN)
        try:
            ds = ds18x20.DS18X20(onewire.OneWire(dat))
            roms = ds.scan()
            ds.convert_temp()
            time.sleep_ms(750)
            for rom in roms:
                temperature_list.append(ds.read_temp(rom))
        except Exception as ow_exc:
            print(ow_exc)
            record_exception(self._error_log, CATEGORY_HARDWARE, ow_exc, logging_settings=self._logging_settings)

        return self._averageTemperature(temperature_list)

    def _averageTemperature(self, temperature_list):
        average = SENSOR_ERROR
        temperature_list_count = len(temperature_list)
        if temperature_list_count > 0:
            temperature_sum = 0
            for temperature in temperature_list:
                temperature_sum = temperature_sum + temperature
                average = temperature_sum / temperature_list_count
        return average
