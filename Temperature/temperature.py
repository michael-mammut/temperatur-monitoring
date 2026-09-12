from machine import Pin
import array, ds18x20, onewire, time

class Temperature:
    def __init__(self, gpio):
        self.__gpio = gpio

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

        return self._averageTemperature(temperature_list)

    def _averageTemperature(self, temperature_list):
        average = -999
        temperature_list_count = len(temperature_list)
        if temperature_list_count > 0:
            temperature_sum = 0
            for temperature in temperature_list:
                temperature_sum = temperature_sum + temperature
                average = temperature_sum / temperature_list_count
        return average
