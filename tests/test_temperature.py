import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from Temperature.temperature import Temperature


class FakeDS18X20:
    def __init__(self, onewire_bus, roms, readings):
        self._roms = roms
        self._readings = readings

    def scan(self):
        return self._roms

    def convert_temp(self):
        pass

    def read_temp(self, rom):
        return self._readings[rom]


class AverageTemperatureTests(unittest.TestCase):
    def test_average_of_multiple_readings(self):
        sensor = Temperature(gpio=16)
        self.assertAlmostEqual(sensor._averageTemperature([20.0, 22.0]), 21.0)

    def test_average_with_no_readings_returns_sentinel(self):
        sensor = Temperature(gpio=16)
        self.assertEqual(sensor._averageTemperature([]), -999)


class ReadCurrentAverageTests(unittest.TestCase):
    def test_returns_average_when_sensors_found(self):
        sensor = Temperature(gpio=16)
        fake_ds = FakeDS18X20(None, roms=[b"rom1", b"rom2"], readings={b"rom1": 20.0, b"rom2": 22.0})

        with patch("Temperature.temperature.ds18x20.DS18X20", return_value=fake_ds), \
             patch("Temperature.temperature.onewire.OneWire", return_value=None):
            result = sensor.readCurrentAverage()

        self.assertAlmostEqual(result, 21.0)

    def test_scan_failure_does_not_crash_and_returns_sentinel(self):
        """Regression test: ds.scan()/convert_temp() raising used to leave
        `roms` undefined, crashing the whole main loop with a NameError."""
        sensor = Temperature(gpio=16)

        def raise_error():
            raise OSError("no devices on 1-wire bus")

        fake_ds = FakeDS18X20(None, roms=[], readings={})
        fake_ds.scan = raise_error

        with patch("Temperature.temperature.ds18x20.DS18X20", return_value=fake_ds), \
             patch("Temperature.temperature.onewire.OneWire", return_value=None):
            result = sensor.readCurrentAverage()  # must not raise

        self.assertEqual(result, -999)

    def test_read_temp_failure_for_one_sensor_does_not_crash(self):
        sensor = Temperature(gpio=16)
        fake_ds = FakeDS18X20(None, roms=[b"rom1"], readings={})

        def raise_read_error(rom):
            raise OSError("CRC error")

        fake_ds.read_temp = raise_read_error

        with patch("Temperature.temperature.ds18x20.DS18X20", return_value=fake_ds), \
             patch("Temperature.temperature.onewire.OneWire", return_value=None):
            result = sensor.readCurrentAverage()  # must not raise

        self.assertEqual(result, -999)


if __name__ == "__main__":
    unittest.main()
