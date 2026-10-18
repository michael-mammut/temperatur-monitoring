"""Erzeugt Screenshots der Web-Oberfläche für die Doku (docs/screenshots/).

Rendert jede Seite mit dem echten Seiten-Code und den echten
Einstellungs-Klassen unter CPython (MicroPython-Module über
tests/micropython_mocks.py gestubbt), mit erfundenen Beispieldaten - kein
Board, keine echten Zugangsdaten nötig. Die Bilder macht ein headless
Google Chrome.

Benutzung:
    python3 scripts/render_ui_screenshots.py
    CHROME=/pfad/zu/chrome python3 scripts/render_ui_screenshots.py   # anderer Browser

Nach Änderungen an der Oberfläche einfach erneut ausführen.
"""
import os
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "docs", "screenshots")
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
# Roughly phone-sized (the UI is mostly used from a phone). Not narrower:
# headless Chrome lays pages out at least ~500 px wide and would cut off
# the right edge of a narrower screenshot.
WIDTH = 500

# file name -> window height (CSS px), tuned so each page fits without a
# large empty margin below
PAGES = {
    "status.png": 360,
    "settings.png": 880,
    "datetime-settings.png": 440,
    "wifi-settings.png": 430,
    "statistics.png": 1450,
}

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tests"))
import micropython_mocks  # noqa: E402

micropython_mocks.install()


class _ExampleWlan:
    def scan_networks(self):
        return ["Heimnetz", "Heimnetz-Gast", "Nachbar-WLAN"]

    def get_rssi(self):
        return -58


def _render_pages(work_dir):
    from Monitoring.sensoralert import SensorAlertSettings
    from Monitoring.settings import MonitoringSettings
    from WebServer.datetimesettings import DateTimeSettings
    from WebServer.eventlog import EventLog
    from WebServer.loggingsettings import LoggingSettings
    from WebServer.settings import Settings
    from WebServer.webserver import WebServer
    from WlanNetwork.wifisettings import WifiSettings

    now = time.time()
    datetime_settings = DateTimeSettings()
    datetime_settings.set('de_AT', 60, True)

    error_log = EventLog('error_log.json')
    error_log._entries = [
        {'timestamp': now - 5 * 86400, 'category': 'network', 'code': 'OSError', 'message': 'Wifi Internal Error'},
        {'timestamp': now - 2 * 86400, 'category': 'external_api', 'code': 'OSError',
         'message': 'Telegram: keine Verbindung innerhalb von 5 s'},
        {'timestamp': now - 9 * 3600, 'category': 'hardware', 'code': 'OneWireError', 'message': '',
         'count': 37, 'last': now - 3600},
    ]
    error_log._save()
    notification_log = EventLog('notification_log.json')
    notification_log._entries = [{'timestamp': now - i * 43200} for i in range(14)]
    notification_log._save()

    server = WebServer(
        0, Settings('Vorzimmer'), WifiSettings('Heimnetz', 'x'), 'x', reset_callback=lambda: None,
        error_log=error_log, notification_log=notification_log,
        monitoring_settings=MonitoringSettings(20, 20, 15), logging_settings=LoggingSettings(),
        datetime_settings=datetime_settings, sensor_alert_settings=SensorAlertSettings())
    monitor = SimpleNamespace(
        telegram=SimpleNamespace(_project_name='Vorzimmer'), wlan=_ExampleWlan(),
        last_water_temperature=24.3, last_ambient_temperature=22.1, last_measurement_time=time.gmtime(now))

    # ESP32-like numbers instead of the host's RAM and disk.
    esp32_memory = {'used': 70 * 1024, 'free': 38 * 1024, 'total': 108 * 1024}
    esp32_storage = {'used': 290 * 1024, 'free': 1758 * 1024, 'total': 2048 * 1024}
    try:
        with patch("WebServer.pages.statistics.get_memory_stats", return_value=esp32_memory), \
             patch("WebServer.pages.statistics.get_storage_stats", return_value=esp32_storage):
            return {
                "status.png": server.render(monitor),
                "settings.png": server.render_settings(),
                "datetime-settings.png": server.render_datetime_settings(),
                "wifi-settings.png": server.render_wifi_settings(monitor),
                "statistics.png": server.render_statistics(monitor, now - 3600),
            }
    finally:
        server._socket.close()


def main():
    if not os.path.exists(CHROME):
        sys.exit("Chrome nicht gefunden: %s (Pfad per CHROME=... setzen)" % CHROME)
    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as work_dir:
        cwd = os.getcwd()
        os.chdir(work_dir)  # the settings classes read/write their JSON files here
        try:
            pages = _render_pages(work_dir)
        finally:
            os.chdir(cwd)
        for name, html in pages.items():
            html_path = os.path.join(work_dir, name + ".html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            out_path = os.path.join(OUT_DIR, name)
            subprocess.run([
                CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                "--user-data-dir=" + os.path.join(work_dir, "chrome-profile"),
                "--force-device-scale-factor=2", "--window-size=%d,%d" % (WIDTH, PAGES[name]),
                "--screenshot=" + out_path, "file://" + html_path,
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("geschrieben:", os.path.relpath(out_path, PROJECT_ROOT))


if __name__ == "__main__":
    main()
