# Projekt-Dokumentation: Captain Nemo

Allgemeine Übersicht über das Projekt, seine Entstehung und den Einsatz von
KI-Unterstützung. Technische Details (Architektur, Konfiguration, Setup)
stehen in [README.md](README.md), Sicherheitsaspekte in [SECURITY.md](SECURITY.md).

## Projekt-Historie

**Frühjahr 2019** — Ursprung des Projekts: Nach einem Wochenende ohne
Aufsicht starb ein Teil der Fische im Aquarium durch zu hohe Wassertemperatur
(siehe [README.md](README.md)). Daraus entstand die ESP32-basierte
Temperaturüberwachung mit automatischer Lüfter-/Luftpumpensteuerung und
Telegram-Benachrichtigung — reiner, von Hand geschriebener MicroPython-Code,
über Jahre gewachsen, ohne Versionskontrolle.

**12.09.2026** — **Erster Einsatz von KI (Claude) in diesem Projekt.** Das
Projekt wurde zu diesem Zeitpunkt erstmals in Git versioniert
(`77f08b2`). Im Zuge dessen wurde der bestehende Code analysiert, um ein
seit Jahren bekanntes Problem zu klären: Der ESP32 lief 1–2 Wochen stabil,
blieb dann hängen und brauchte einen manuellen Hard-Reset. Gefundene und
behobene Ursachen (`5e8dbc5`):
- nie geschlossene HTTP-Responses in `telegram.py` → Socket-Leak
- ein Crash-Pfad in `temperature.py` bei Sensor-Lesefehlern (`NameError`)
- kein Watchdog, keine Fehlerisolierung pro Loop-Durchlauf
- `Temperature`-Objekte wurden bei jedem Loop neu erzeugt (Heap-Fragmentierung)

Dabei wurde die erste automatisierte Testsuite (`tests/`, reines
`unittest`) sowie die GitHub-Actions-CI (`4745e3a`) eingeführt.

**27.09.2026** — Flaky Test gefixt (ungemockte Systemzeit, `4390d6e`),
erste README-Dokumentation ergänzt (`0cc7fde`).

**17.10.2026** — Auf echter Hardware wurde ein zweiter, seit Projektbeginn
bestehender Bug gefunden: Telegram-Nachrichten scheiterten *immer* (erst
durch fehlendes URL-Encoding, nach dem ersten Fix durch eine
Content-Length-Berechnung nach Zeichen- statt Byte-Länge bei `°`-Zeichen),
aber unsichtbar, weil nichts geloggt wurde (`c67d096`, im Commit als
*"Fehlersuche mittels Claude. Fix mit Claude. Human-Reviewed"* vermerkt).
Zusätzlich: NTP-Zeitsync-Fix, korrekter DHCP-Hostname, eine
Web-Status-Seite und eine Einstellungsseite für den Aquarium-Namen
(`0b415e1`).

**Laufend** — WLAN-Zugangsdaten über die Web-Oberfläche änderbar
(Dropdown + Passwortfeld), abgesichert durch HTTP Basic Auth,
Eingabevalidierung, HTML-Escaping und Request-Size-Limits — siehe
[SECURITY.md](SECURITY.md). Dazu eine `/statistics`-Seite (RAM-/Flash-
Belegung, letzter Login, WLAN-Signalstärke, Benachrichtigungen der
letzten 30 Tage, Fehler-Diagramm + -Tabelle nach Kategorie
System/Hardware/Netzwerk/Externe APIs) sowie die dafür nötige
Fehlerprotokollierung in allen betroffenen Modulen. Dabei auf echter
Hardware einen `MemoryError` gefunden, der das Rendern von `/statistics`
komplett verhinderte, sobald das Fehler-Log seine 200-Einträge-Grenze
erreicht hatte (Tabelle zeigt seither maximal die letzten 20 Zeilen) —
und beim Deployen selbst ebenfalls einen `MemoryError`, weil größere
Dateien bisher als ein einziger Base64-Block statt in kleinen Chunks
übertragen wurden. Außerdem eine Telegram-Warnung, wenn freier RAM oder
Flash unter einen konfigurierbaren Prozentsatz fällt
(`Monitoring/config.py`, zusätzlich über `/settings` änderbar). Dazu:
Fehlerprotokollierung je Kategorie über `/settings` abschaltbar
(`WebServer/loggingsettings.py`), ein Flash-Anteil-Deckel für Fehler- +
Benachrichtigungs-Log zusammen (`enforce_storage_budget()`, Default 15 %,
ebenfalls über `/settings` änderbar) sowie ein Formular auf
`/statistics`, um Log-Einträge älter als X Minuten manuell zu löschen.

## Wie KI in diesem Projekt eingesetzt wird

Seit dem 12.09.2026 wird die Weiterentwicklung mit Claude (Anthropic)
unterstützt: Fehleranalyse (inkl. Live-Debugging direkt auf dem
angeschlossenen ESP32 über die serielle Schnittstelle), Code-Fixes,
neue Features und die komplette Testsuite. Vor dem Fix auf echte Hardware
übertragen und end-to-end verifiziert, nicht nur über die Unit-Tests.
Commits, bei denen das explizit vermerkt ist, nennen das im Commit-Text
(z. B. `c67d096`). Die eigentliche Freigabe/Review der Änderungen liegt
weiterhin beim Projektinhaber — nichts wird automatisch committed oder
gepusht, ohne dass das vorher bestätigt wurde.

## Tests

Alle Tests liegen in [tests/](tests/), laufen mit reinem `python3`
(Standard-`unittest`, keine zusätzliche Installation nötig) und werden bei
jedem `git push`/Pull Request automatisch über
[.github/workflows/tests.yml](.github/workflows/tests.yml) ausgeführt.

```bash
python3 -m unittest discover -s tests -v
```

MicroPython-only-Module (`machine`, `network`, `ds18x20`, `onewire`,
`ntptime`, `urequests`, `ujson`, `ubinascii`) werden über
[tests/micropython_mocks.py](tests/micropython_mocks.py) gestubbt, damit
die komplette Logik unter normalem CPython (und in der CI) läuft, ohne
echte Hardware zu benötigen.

| Testdatei | Anzahl Tests | Prüft |
|---|---|---|
| [test_main.py](tests/test_main.py) | 17 | Hauptschleife: Watchdog-Fütterung, Fehlerisolierung pro Durchlauf, Sensor-Wiederverwendung, Verdrahtung der Web-Oberfläche und der Logs, RAM-/Flash-Warnschwellen, Log-Speicher-Deckel |
| [test_telegram.py](tests/test_telegram.py) | 11 | Telegram-Versand: Response-Schließung, UTF-8-Byte-Kodierung, Benachrichtigungs-Timing, Fehler-/Benachrichtigungs-Protokoll |
| [test_temperature.py](tests/test_temperature.py) | 6 | Sensor-Mittelwertbildung, Absturzsicherheit bei Lesefehlern, Fehlerprotokollierung |
| [test_wlanconnection.py](tests/test_wlanconnection.py) | 12 | WLAN-Verbindung, DHCP-Hostname, NTP-Zeitsync-Retry, Netzwerk-Scan (inkl. 30s-Cache), Signalstärke, Fehlerprotokollierung |
| [test_settings.py](tests/test_settings.py) | 3 | Persistenz des Aquarium-Namens über Neustarts |
| [test_wifisettings.py](tests/test_wifisettings.py) | 11 | Persistenz + Validierung der WLAN-Zugangsdaten (SSID-/Passwort-Längen nach 802.11/WPA2-Spezifikation) |
| [test_statusserver.py](tests/test_statusserver.py) | 39 | HTTP-Server: Routing, HTTP-Basic-Auth, HTML-Escaping (XSS), Request-Size-Limit, Statistik-Seite (inkl. Zeilenbegrenzung gegen MemoryError), Warnschwellen-Formular, Protokollierungs-Checkboxen, Logs-löschen-Formular, echte Socket-Kommunikation über Loopback |
| [test_eventlog.py](tests/test_eventlog.py) | 14 | Persistierter Event-Log: 30-Tage-Fenster, Begrenzung auf 200 Einträge, Dateigröße, Alters-basiertes Löschen, Speicher-Budget-Durchsetzung |
| [test_errorlog.py](tests/test_errorlog.py) | 6 | Exception → Fehlerkategorie/-code/-meldung, Ein-/Ausschalten je Kategorie |
| [test_loggingsettings.py](tests/test_loggingsettings.py) | 4 | Persistenz der Protokollierungs-Ein/Aus-Schalter je Kategorie |
| [test_loginlog.py](tests/test_loginlog.py) | 3 | Login-Zeitpunkt-Persistenz, Rückgabe des *vorherigen* Logins |
| [test_systemstats.py](tests/test_systemstats.py) | 2 | RAM-/Flash-Belegung (`used + free == total`) |
| [test_monitoringsettings.py](tests/test_monitoringsettings.py) | 7 | Persistenz + Validierung der RAM-/Flash-/Log-Speicher-Warnschwellen (5–50 %) |

**Gesamt: 135 Tests**, Stand des letzten vollständigen Durchlaufs in diesem
Dokument. Viele Tests sind als Regressionstests für konkret auf der
Hardware beobachtete Bugs angelegt (siehe Docstrings in den jeweiligen
Testdateien) — sie beschreiben bewusst, *welches reale Problem* sie
verhindern, nicht nur was sie prüfen.
