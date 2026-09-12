from machine import Pin


class ActorControl:
    def __init__(self, gpio_pin):
        self._actor = Pin(gpio_pin, Pin.OUT)
        self._actor.on()

    def on(self):
        self._actor.on()

    def off(self):
        self._actor.off()
