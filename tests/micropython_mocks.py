"""Stubs for MicroPython-only modules (machine, network, onewire, ds18x20,
ntptime, urequests) so the ESP32 firmware code can be imported and unit
tested under regular CPython.

Call install() once before importing any project module that (transitively)
imports one of these MicroPython modules.
"""
import base64
import gc
import json
import sys
import time
import types


class FakePin:
    IN = "IN"
    OUT = "OUT"

    def __init__(self, gpio, mode=None):
        self.gpio = gpio
        self.mode = mode
        self._value = 0

    def on(self):
        self._value = 1

    def off(self):
        self._value = 0

    def value(self, *args):
        if args:
            self._value = args[0]
        return self._value


class FakeWDT:
    """Records every feed() call so tests can assert the watchdog is fed."""

    def __init__(self, id=0, timeout=None):
        self.id = id
        self.timeout = timeout
        self.feed_count = 0

    def feed(self):
        self.feed_count += 1


class FakeWLAN:
    def __init__(self, interface):
        self.interface = interface
        self._connected = False

    def active(self, *args):
        pass

    def isconnected(self):
        return self._connected

    def connect(self, ssid, key):
        pass

    def config(self, *args, **kwargs):
        return ""

    def scan(self):
        return []

    def status(self, *args):
        return -60  # a plausible default RSSI in dBm


def _install_module(name, **attrs):
    if name in sys.modules:
        module = sys.modules[name]
    else:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def install():
    """Idempotent: safe to call from every test module."""
    _install_module("machine", Pin=FakePin, WDT=FakeWDT, idle=lambda: None, reset=lambda: None)
    _install_module("ubinascii", a2b_base64=base64.b64decode, b2a_base64=base64.b64encode)
    _install_module("network", WLAN=FakeWLAN, STA_IF="STA_IF")
    _install_module("onewire", OneWire=object)
    _install_module("ds18x20", DS18X20=object)
    _install_module("ntptime", settime=lambda: None)
    _install_module("urequests", get=lambda **kwargs: None, post=lambda *args, **kwargs: None)
    # MicroPython's ujson.dumps does not escape non-ASCII characters to
    # \uXXXX (unlike CPython's json.dumps default ensure_ascii=True) - it
    # passes them through raw. Match that so UTF-8 byte-length bugs show up
    # under test the same way they did on real hardware.
    _install_module(
        "ujson",
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False),
        loads=json.loads,
        dump=lambda obj, f: json.dump(obj, f, ensure_ascii=False),
        load=json.load,
    )

    # MicroPython's time module has extra functions CPython's doesn't.
    if not hasattr(time, "sleep_ms"):
        time.sleep_ms = lambda ms: None
    if not hasattr(time, "ticks_ms"):
        time.ticks_ms = lambda: int(time.monotonic() * 1000)
    if not hasattr(time, "ticks_diff"):
        time.ticks_diff = lambda a, b: a - b
    if not hasattr(time, "ticks_add"):
        time.ticks_add = lambda a, b: a + b

    # MicroPython's gc module exposes mem_free()/mem_alloc(); CPython's
    # doesn't track that, so stub plausible fixed values for tests.
    if not hasattr(gc, "mem_free"):
        gc.mem_free = lambda: 100000
    if not hasattr(gc, "mem_alloc"):
        gc.mem_alloc = lambda: 50000
