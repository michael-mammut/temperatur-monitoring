---
name: nemo-workflow
description: Standard-Workflow für Code-Änderungen an diesem Projekt (Captain Nemo, ESP32/MicroPython-Aquarium-Monitor) - Tests, Hardware-Deploy, Verifikation, Doku, Git-Regeln. Immer anwenden, wenn main.py, WebServer/, WlanNetwork/, Notification/, Temperature/, Monitoring/, GpioControl/ oder Airpump/ geändert werden.
---

# Captain Nemo – Entwicklungs-Workflow

Dieses Projekt ist ein MicroPython-Programm auf einem ESP32, das ein
Aquarium überwacht (Temperatur, Lüfter/Luftpumpe, Telegram-Alarme) und
eine kleine Web-Oberfläche anbietet (`/`, `/settings`, `/wifi-settings`,
`/statistics`). Hintergrund und Architektur stehen in
[README.md](../../../README.md), Sicherheitsmodell in
[SECURITY.md](../../../SECURITY.md), Projekt-Historie in
[PROJECT.md](../../../PROJECT.md).

`WebServer/webserver.py` (Klasse `WebServer`) ist nur noch der schlanke
HTTP-Kern - Routing, Auth, Request-Parsing. Jede der vier Seiten hat ihr
eigenes Modul unter `WebServer/pages/` (`status.py`, `settings.py`,
`wifisettings.py`, `statistics.py`) mit `render(server, ...)` und ggf.
`handle_post(server, ...)` als freie Funktionen, die den `server` als
ersten Parameter bekommen (Zugriff auf z. B. `server._escape_html(...)`,
`server._error_log`). Neue Seiten/Formulare gehören in ein neues Modul
unter `pages/`, nicht in `webserver.py` selbst.

## Bei jeder Code-Änderung

1. **Tests schreiben/anpassen.** Reines `unittest`, keine zusätzlichen
   Abhängigkeiten. MicroPython-only-Module (`machine`, `network`,
   `ds18x20`, `onewire`, `ntptime`, `urequests`, `ujson`, `ubinascii`)
   sind in [tests/micropython_mocks.py](../../../tests/micropython_mocks.py)
   gemockt - `micropython_mocks.install()` muss vor jedem Import aus dem
   Projekt aufgerufen werden (siehe Kopf jeder bestehenden Testdatei).
2. **Komplette Suite laufen lassen**, nicht nur die neue Testdatei:
   ```bash
   python3 -m unittest discover -s tests -v
   ```
3. **Auf echte Hardware deployen und end-to-end verifizieren** - Unit-Tests
   allein reichen hier nicht, mehrere reale Bugs (MemoryError bei großen
   Allokationen, UTF-8-Byte-vs-Zeichen-Bug bei Telegram, DHCP-Hostname)
   wurden erst auf dem echten Gerät sichtbar:
   ```bash
   python3 scripts/deploy_esp32.py                       # alles
   python3 scripts/deploy_esp32.py Pfad/zur/datei.py      # nur geänderte Datei(en)
   ```
   Danach mit `curl` gegen die laufende Web-Oberfläche prüfen (Admin-Passwort
   liegt in `WebServer/config.py`, nicht in Git). Device braucht nach dem
   Deploy ein paar Sekunden zum Neustarten/WLAN-Verbinden, bevor es erreichbar
   ist.
4. **Doku nachziehen**, wenn sich Nutzer-sichtbares Verhalten, Config-Parameter
   oder die Web-Oberfläche ändern: README.md (Modul-Tabelle, Config-Tabellen,
   Web-Oberfläche-Tabelle, Setup-Schritte), SECURITY.md (neue Eingaben IMMER
   mit aufnehmen - siehe unten), PROJECT.md (Historie-Abschnitt "Laufend" +
   Test-Tabelle mit aktueller Zahl pro Testdatei und Gesamtzahl).

## Sicherheitsanforderungen für alles, was über die Web-Oberfläche reinkommt

Dieses Projekt nimmt Eingaben sehr ernst - jeder neue Formular-Wert braucht:

- **Server-seitige Validierung** gegen eine feste Werteliste oder einen
  definierten Bereich, nie nur Client-seitig (HTML `<select>`/`min`/`max`
  schützt nicht vor einem direkten, manipulierten POST-Request).
- **Atomare Speicherung**: Schlägt die Validierung eines Felds fehl, darf
  **kein** anderes Feld aus demselben Formular gespeichert werden (siehe
  `handle_post()` in `WebServer/pages/settings.py` als Referenz-Muster:
  erst alle Felder validieren, danach erst irgendetwas schreiben).
- **HTML-Escaping** jeder Ausgabe, die aus Nutzereingaben oder von außen
  kommt (`_escape_html`), auch bei scheinbar harmlosen Werten (z. B.
  WLAN-SSIDs aus der Scan-Liste - die stammen von fremden Netzwerken).
- Siehe [SECURITY.md](../../../SECURITY.md) für das vollständige
  Bedrohungsmodell und ergänze dort die neue Zeile in der Tabelle.

## Settings-Pattern

Jede Einstellung, die über `/settings` änderbar ist, folgt demselben Muster
(siehe `WebServer/loggingsettings.py`, `WebServer/datetimesettings.py`,
`Monitoring/settings.py` als Beispiele):

- Eigene Klasse mit `get_*()`/`set_*()`, JSON-Datei auf dem Flash.
- Konstruktor liest die JSON-Datei, fällt bei fehlender/korrupter Datei
  oder ungültigem Wert auf einen sinnvollen Default zurück (nie einen Fehler
  werfen, nur weil die Datei noch nicht existiert).
- `set_*()` validiert und wirft `ValueError` bei ungültigem Wert, schreibt
  erst danach.
- Als optionaler Konstruktor-Parameter (`=None`) in `WebServer` und
  `main.py` verdrahten - alles muss ohne diese Einstellung funktionieren
  (Rückwärtskompatibilität für einfachere Tests/ältere Deployments).

## Deploy-Tool

[scripts/deploy_esp32.py](../../../scripts/deploy_esp32.py) - nicht
`mpremote` für die Übertragung verwenden (siehe Docstring dort: scheitert
zuverlässig bei Endlosschleifen auf dem Board, und größere Dateien als ein
Block führen zu `MemoryError` auf dem ESP32). `mpremote` ist nur für die
REPL-Konsole weiterhin brauchbar.

## Git

- **Nie committen, ohne dass explizit danach gefragt wurde** - auch nicht
  nach erfolgreichem Test-Lauf oder Hardware-Verifikation.
- Commit-Messages auf Deutsch, kurz und ohne Floskeln (siehe `git log`
  für Stil-Beispiele aus diesem Projekt). Nur auf explizite Bitte liefern.
- `WlanNetwork/config.py`, `Notification/config.py`, `WebServer/config.py`
  enthalten echte Zugangsdaten/Secrets und sind in `.gitignore` - niemals
  versehentlich mit `git add -A` einchecken. Je eine `*.example.py`-Vorlage
  pflegen, wenn neue Felder dazukommen.
