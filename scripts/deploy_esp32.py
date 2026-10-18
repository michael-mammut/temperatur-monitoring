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

Module werden vor dem Übertragen zu Bytecode (.mpy) vorkompiliert. Sonst
übersetzt MicroPython jede .py-Datei beim Import auf dem Board selbst -
das kostete hier gemessen ~67 KB RAM und hinterließ einen so
zersplitterten Heap, dass keine Seite der Web-Oberfläche mehr gerendert
werden konnte. Das .mpy-Format hängt von der Firmware ab (1.16: v5,
1.2x: v6), deshalb fragt das Skript das Board und wählt den passenden
Compiler selbst.

Benutzung:
    python3 scripts/deploy_esp32.py                  # alle Projektdateien
    python3 scripts/deploy_esp32.py WebServer/webserver.py   # nur diese eine Datei
    python3 scripts/deploy_esp32.py --port /dev/ttyUSB0         # anderer Port (Linux)
    python3 scripts/deploy_esp32.py --no-mpy           # reine .py übertragen (Fehlersuche)

Voraussetzung: `pip install pyserial` und der zur Firmware passende Compiler:
`pip install mpy-cross-v5` (MicroPython 1.12-1.18) bzw. `pip install mpy-cross` (1.19+).
"""
import argparse
import base64
import os
import subprocess
import sys
import tempfile
import time

DEFAULT_PORT = "/dev/cu.usbserial-0001"  # macOS; unter Linux z.B. /dev/ttyUSB0
BAUD = 115200
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Nur die Dateien, die tatsächlich auf dem Gerät laufen müssen.
# (tests/, .github/, README.md, .gitignore, *.example.py bleiben auf dem Dev-Rechner.)
FILES = [
    "boot.py",
    "config.py",
    "main.py",
    "aquarium.py",
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
    "WebServer/pages/datetimesettings.py",
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
    "WlanNetwork/accesspoint.py",
    "WlanNetwork/doublereset.py",
    "WlanNetwork/setupmode.py",
    "WlanNetwork/dnsserver.py",
    "WlanNetwork/config.py",
    "Monitoring/config.py",
    "Monitoring/settings.py",
    "Monitoring/sensoralert.py",
]


# .mpy format version reported by the board -> Python module of the
# matching compiler (both installable via pip).
MPY_COMPILERS = {
    5: ("mpy_cross_v5", "mpy-cross-v5"),
    6: ("mpy_cross", "mpy-cross"),
}


def compiles_to_mpy(rel_path):
    """boot.py/main.py must stay .py (MicroPython only auto-runs those),
    config files stay editable by hand, package markers are empty anyway."""
    name = os.path.basename(rel_path)
    return rel_path.endswith(".py") and name not in ("boot.py", "main.py", "config.py", "__init__.py")


def mpy_compiler_for(mpy_version):
    if mpy_version not in MPY_COMPILERS:
        sys.exit("Unbekannte .mpy-Version %r der Firmware - mit --no-mpy übertragen." % mpy_version)
    module, package = MPY_COMPILERS[mpy_version]
    try:
        __import__(module)
    except ImportError:
        sys.exit("Compiler für .mpy v%d fehlt: pip install %s (oder mit --no-mpy übertragen)" % (mpy_version, package))
    return module


def device_mpy_version(ser):
    out = exec_raw(ser, "import sys\n"
                        "print(getattr(sys.implementation, '_mpy', getattr(sys.implementation, 'mpy', 0)) & 0xff)\n")
    return int(out.strip())


def compile_to_mpy(compiler_module, rel_path, out_dir):
    out_path = os.path.join(out_dir, rel_path[:-3] + ".mpy")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    subprocess.run([sys.executable, "-m", compiler_module, "-o", out_path, os.path.join(PROJECT_ROOT, rel_path)],
                   check=True)
    return out_path


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


def write_file(ser, rel_path, local_path=None):
    if local_path is None:
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


def remove_file(ser, rel_path):
    exec_raw(ser, "import os\ntry:\n    os.remove('%s')\nexcept OSError:\n    pass\n" % rel_path)


def upload(ser, rel_path, compiler_module, out_dir):
    if compiler_module is None or not compiles_to_mpy(rel_path):
        write_file(ser, rel_path)
        return
    mpy_rel_path = rel_path[:-3] + ".mpy"
    write_file(ser, mpy_rel_path, compile_to_mpy(compiler_module, rel_path, out_dir))
    # MicroPython prefers x.py over x.mpy - a leftover .py from an earlier
    # deploy would silently keep the old code running.
    remove_file(ser, rel_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Nur diese Datei(en) übertragen, relativ zum Projektordner. Ohne Angabe: alle Dateien aus FILES.")
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serieller Port (Default: %s)" % DEFAULT_PORT)
    parser.add_argument("--no-mpy", action="store_true", help="Module als .py statt vorkompiliert (.mpy) übertragen")
    args = parser.parse_args()

    files_to_upload = args.files if args.files else FILES
    unknown = [f for f in files_to_upload if args.files and not os.path.exists(os.path.join(PROJECT_ROOT, f))]
    if unknown:
        sys.exit("Datei(en) nicht gefunden: %s" % ", ".join(unknown))

    import serial  # only needed here, keeps the helpers importable for tests

    ser = serial.Serial(args.port, BAUD, timeout=1)
    try:
        enter_raw_repl(ser)
        print("Raw REPL betreten")
        compiler_module = None
        if not args.no_mpy:
            mpy_version = device_mpy_version(ser)
            compiler_module = mpy_compiler_for(mpy_version)
            print("Firmware erwartet .mpy v%d, kompiliere mit %s" % (mpy_version, compiler_module))
        with tempfile.TemporaryDirectory() as out_dir:
            for rel_path in files_to_upload:
                upload(ser, rel_path, compiler_module, out_dir)
        print("Alle Dateien übertragen, starte Gerät neu...")
        ser.write(b"\x02")  # Ctrl-B -> zurück in freundliche REPL
        time.sleep(0.2)
        ser.write(b"\x04")  # Soft-Reset in freundlicher REPL führt boot.py + main.py erneut aus
    finally:
        ser.close()


if __name__ == "__main__":
    main()
