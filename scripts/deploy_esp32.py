"""Überträgt das Projekt per USB/seriell auf den ESP32.

Wird anstelle von `mpremote` verwendet, weil zwei auf dieser Hardware
reproduzierbare Probleme damit nicht auftreten:

1. Steckt das Board gerade in einer Endlosschleife (z. B. WLAN-Reconnect),
   scheitert `mpremote` oft mit "could not enter raw repl", weil die
   Interrupt-Bytes nicht rechtzeitig verarbeitet werden. Dieses Skript
   schickt Ctrl-C mehrfach und wartet den Boot-Vorgang nach dem
   automatischen Reset (DTR/RTS beim Öffnen des Ports) explizit ab.
2. Größere Dateien (ab ein paar KB) als ein einziger Block übertragen,
   braucht auf dem ESP32 eine einzige große zusammenhängende Allokation
   (Rohbytes + Base64 + Decode-Puffer gleichzeitig) - das schlägt mit
   `MemoryError` fehl, selbst direkt nach einem Neustart. Dieses Skript
   überträgt deshalb in kleinen 512-Byte-Chunks über denselben offenen
   Dateihandle (Raw-REPL-Globals bleiben über mehrere exec()-Aufrufe
   hinweg erhalten).

Benutzung:
    python3 scripts/deploy_esp32.py                  # alle Projektdateien
    python3 scripts/deploy_esp32.py WebServer/webserver.py   # nur diese eine Datei
    python3 scripts/deploy_esp32.py --port /dev/ttyUSB0         # anderer Port (Linux)

Voraussetzung: `pip install pyserial`
"""
import argparse
import base64
import os
import sys
import time

import serial

DEFAULT_PORT = "/dev/cu.usbserial-0001"  # macOS; unter Linux z.B. /dev/ttyUSB0
BAUD = 115200
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Nur die Dateien, die tatsächlich auf dem Gerät laufen müssen.
# (tests/, .github/, README.md, .gitignore, *.example.py bleiben auf dem Dev-Rechner.)
FILES = [
    "boot.py",
    "config.py",
    "main.py",
    "Airpump/config.py",
    "GpioControl/ActorControl.py",
    "GpioControl/LedControl.py",
    "GpioControl/config.py",
    "Notification/telegram.py",
    "Notification/config.py",
    "Temperature/temperature.py",
    "Temperature/config.py",
    "WebServer/webserver.py",
    "WebServer/webstyle.py",
    "WebServer/pages/__init__.py",
    "WebServer/pages/status.py",
    "WebServer/pages/settings.py",
    "WebServer/pages/wifisettings.py",
    "WebServer/pages/statistics.py",
    "WebServer/settings.py",
    "WebServer/eventlog.py",
    "WebServer/errorlog.py",
    "WebServer/loggingsettings.py",
    "WebServer/loginlog.py",
    "WebServer/systemstats.py",
    "WebServer/datetimeformat.py",
    "WebServer/datetimesettings.py",
    "WebServer/config.py",
    "WlanNetwork/wlanconnection.py",
    "WlanNetwork/wifisettings.py",
    "WlanNetwork/config.py",
    "Monitoring/config.py",
    "Monitoring/settings.py",
]


def read_until(ser, expected, timeout=10):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        chunk = ser.read(1)
        if chunk:
            buf += chunk
            if buf.endswith(expected):
                return buf
        else:
            time.sleep(0.02)
    raise TimeoutError("Timed out waiting for %r, got %r" % (expected, buf))


def enter_raw_repl(ser):
    # Das Öffnen des Ports resettet die meisten ESP32-Boards (Auto-Reset via
    # DTR/RTS), was main.py neu startet. Erst den Boot-Vorgang abwarten,
    # sonst gehen die Interrupt-Bytes verloren, während der ROM-Bootloader
    # noch startet.
    time.sleep(1.5)
    ser.reset_input_buffer()

    for _ in range(20):
        ser.write(b"\r\x03")
        time.sleep(0.1)
    ser.reset_input_buffer()
    ser.write(b"\r\x01")  # Ctrl-A -> raw REPL
    read_until(ser, b"raw REPL; CTRL-B to exit\r\n>", timeout=15)


def exec_raw(ser, code, timeout=15):
    # Raw-REPL-Antwortformat: "OK" <stdout> "\x04" <stderr> "\x04" ">"
    ser.write(code.encode("utf-8"))
    ser.write(b"\x04")  # Ctrl-D -> ausführen
    read_until(ser, b"OK", timeout=timeout)
    stdout = read_until(ser, b"\x04", timeout=timeout)[:-1]
    stderr = read_until(ser, b"\x04", timeout=timeout)[:-1]
    read_until(ser, b">", timeout=timeout)
    if stderr:
        raise RuntimeError("Device error: %s" % stderr.decode("utf-8", "replace"))
    return stdout


def write_file(ser, rel_path):
    local_path = os.path.join(PROJECT_ROOT, rel_path)
    with open(local_path, "rb") as f:
        data = f.read()

    remote_dir = os.path.dirname(rel_path)
    if remote_dir:
        exec_raw(
            ser,
            "import os\n"
            "try:\n"
            "    os.mkdir('%s')\n"
            "except OSError:\n"
            "    pass\n" % remote_dir,
        )

    CHUNK_SIZE = 512
    exec_raw(ser, "import ubinascii\n_f = open('%s', 'wb')\n" % rel_path)
    for i in range(0, len(data), CHUNK_SIZE):
        chunk_b64 = base64.b64encode(data[i:i + CHUNK_SIZE]).decode("ascii")
        exec_raw(ser, "_f.write(ubinascii.a2b_base64('%s'))\n" % chunk_b64)
    exec_raw(ser, "_f.close()\ndel _f\n")
    print("uploaded %s (%d bytes)" % (rel_path, len(data)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Nur diese Datei(en) übertragen, relativ zum Projektordner. Ohne Angabe: alle Dateien aus FILES.")
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serieller Port (Default: %s)" % DEFAULT_PORT)
    args = parser.parse_args()

    files_to_upload = args.files if args.files else FILES
    unknown = [f for f in files_to_upload if args.files and not os.path.exists(os.path.join(PROJECT_ROOT, f))]
    if unknown:
        sys.exit("Datei(en) nicht gefunden: %s" % ", ".join(unknown))

    ser = serial.Serial(args.port, BAUD, timeout=1)
    try:
        enter_raw_repl(ser)
        print("Raw REPL betreten")
        for rel_path in files_to_upload:
            write_file(ser, rel_path)
        print("Alle Dateien übertragen, starte Gerät neu...")
        ser.write(b"\x02")  # Ctrl-B -> zurück in freundliche REPL
        time.sleep(0.2)
        ser.write(b"\x04")  # Soft-Reset in freundlicher REPL führt boot.py + main.py erneut aus
    finally:
        ser.close()


if __name__ == "__main__":
    main()
