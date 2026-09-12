import time
from machine import Pin


def turnOn(gpioPin):
    led_pin = Pin(gpioPin, Pin.OUT)
    led_pin.on()


def turn_off(gpioPin):
    led_pin = Pin(gpioPin, Pin.OUT)
    led_pin.off()

def led_twinkle(gpioPin, twinkleTime):
    led_pin = Pin(gpioPin, Pin.OUT)
    led_pin.on()
    time.sleep_ms(twinkleTime)
    led_pin.off()
    time.sleep_ms(twinkleTime)

def led_error_twinkle(gpioPin_A, gpioPin_B, twinkleTime, maxCount):
    count = 0
    pin_led_a = Pin(gpioPin_A, Pin.OUT)
    pin_led_b = Pin(gpioPin_B, Pin.OUT)

    pin_led_a.off()
    pin_led_b.off()

    while count < maxCount:
        pin_led_a.on()
        pin_led_b.off()
        time.sleep_ms(twinkleTime)
        pin_led_a.off()
        pin_led_b.on()
        time.sleep_ms(twinkleTime)
        count += 1

    pin_led_a.off()
    pin_led_b.off()

