---
name: nemo-workflow
description: Standard-Workflow für Code-Änderungen an diesem Projekt (Captain Nemo, ESP32/MicroPython-Aquarium-Monitor) - Tests, Hardware-Deploy, Verifikation, Doku, Git-Regeln. Immer anwenden, wenn main.py, WebServer/, WlanNetwork/, Notification/, Temperature/, Monitoring/, GpioControl/ oder Airpump/ geändert werden.
---

# Captain Nemo – Entwicklungs-Workflow

Dieses Projekt ist ein MicroPython-Programm auf einem ESP32, das ein
Aquarium überwacht (Temperatur, Lüfter/Luftpumpe, Telegram-Alarme) und
eine kleine Web-Oberfläche anbietet (`/`, `/settings`,
`/datetime-settings`, `/wifi-settings`, `/statistics`). Hintergrund und
Architektur stehen in [README.md](../../../README.md), Sicherheitsmodell
in [SECURITY.md](../../../SECURITY.md), Projekt-Historie in
[PROJECT.md](../../../PROJECT.md).

`WebServer/webserver.py` (Klasse `WebServer`) ist nur noch der schlanke
HTTP-Kern - Routing, Auth, Request-Parsing. Jede der fünf Seiten hat ihr
eigenes Modul unter `WebServer/pages/` (`status.py`, `settings.py`,
`datetimesettings.py`, `wifisettings.py`, `statistics.py`) mit
`render(server, ...)` und ggf. `handle_post(server, ...)` als freie
Funktionen, die den `server` als ersten Parameter bekommen (Zugriff auf
z. B. `server._escape_html(...)`, `server._error_log`). Neue
Seiten/Formulare gehören in ein neues Modul unter `pages/`, nicht in
`webserver.py` selbst - und wenn ein Formularteil deutlich größer ist
als der Rest einer Seite (viele Optionen, lange Liste), eher eine
eigene kleine Seite dafür als es anzuhängen (siehe
`datetimesettings.py`, aus genau diesem Grund von `settings.py`
abgespalten - Details unten unter "Speicher-Fallstricke").

**Hinweis zur Benennung:** `WebServer/pages/datetimesettings.py`
(Seiten-Rendering) und `WebServer/datetimesettings.py`
(Persistenz-Klasse `DateTimeSettings`) haben bewusst denselben Basis­namen
in unterschiedlichen Verzeichnissen - exakt dasselbe Muster wie
`WebServer/settings.py` (Klasse `Settings`) vs.
`WebServer/pages/settings.py` (Seiten-Rendering). Kein Konflikt, beide
über ihren vollen Modulpfad eindeutig importiert.

Die Datums-/Zeit-Anzeige ist **bewusst auf Europa beschränkt** - die
automatische Sommerzeit-Umstellung kennt nur die EU-Regel (letzter
Sonntag März/Oktober). Das ist eine getroffene Scope-Entscheidung, kein
Versehen: andere Regionen (USA/Kanada, Südhalbkugel) haben andere
Umstellungstermine oder keine Sommerzeit und bräuchten eigene Regelsätze.
Bei einer Erweiterung in diese Richtung vorher abklären, nicht einfach
mit-implementieren.

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

## Speicher-Fallstricke auf dem ESP32

Jede Seite wird als ein einziger großer String gebaut (`.format()` über
das komplette HTML) und dann in einem Stück gesendet. Das braucht eine
**zusammenhängende** Allokation von mehreren KB - das ist auf dem ESP32
mehrfach an der Heap-Fragmentierung gescheitert, nicht am insgesamt
freien Speicher (schon bei >60 KB frei gesehen). Zwei Lehren daraus:

- **`gc.collect()` läuft in `WebServer/webserver.py: handle_requests()`
  (genauer: `_render_with_retry()`) direkt nach dem Parsen der Anfrage,
  bevor irgendeine Seite gerendert wird** - bewusst dort und nicht nur in
  `main.py`s Loop, weil `main.py`s `gc.collect()` erst *nach*
  `handle_requests()` läuft und die Fragmentierung vom Rest des
  vorherigen Loop-Durchlaufs (Sensoren, WLAN, Telegram) sonst noch da
  wäre, wenn die nächste Anfrage reinkommt. Nicht entfernen, auch wenn es
  im Code wie ein überflüssiger Zusatzaufruf aussieht.
- **Dieser eine `gc.collect()` reichte auf Dauer nicht** - als `/settings`
  durch die Sommerzeit-Checkbox noch größer wurde, trat derselbe
  `MemoryError` erneut auf, weil der Heap auch *während* des Renderns
  fragmentiert (z. B. beim Aufbau der ~45 Culture-/Zeitzonen-Optionen).
  Statt noch einen manuell platzierten `gc.collect()`-Aufruf nachzuziehen
  (der beim nächsten größeren Feld wieder reißen würde), fängt
  `_render_with_retry()` jetzt generell einen `MemoryError` beim Rendern
  ab, sammelt noch einmal und versucht es exakt einmal erneut - für jede
  Seite, auch zukünftige. Bei neuer Seiten-/Formular-Logik nicht wieder
  einzelne `gc.collect()`-Flicken einbauen, sondern auf diesen
  bestehenden Retry-Mechanismus vertrauen.
- Trotzdem gilt: Wird eine Seite durch neue Felder größer, ist man im
  Mittel näher an einem erneuten `MemoryError` (auch wenn der Retry ihn
  jetzt meist abfängt) - der Retry behandelt das Symptom, nicht die
  Ursache. Listen mit vielen Einträgen (Fehler-Tabelle,
  Netzwerk-Scan-Ergebnisse, Culture-/Zeitzonen-Optionen) im Zweifel
  begrenzen (siehe `_MAX_DISPLAYED_ERRORS` in
  `WebServer/pages/statistics.py` als Muster) statt alles ungekappt in
  einen String zu rendern.
- **Ursächlicher: eine wachsende Seite aufteilen, nicht nur abfedern.**
  Genau das ist mit `/settings` passiert - das Culture-/Zeitzonen-
  Dropdown allein hatte ~45 Optionen und war mit Abstand der größte
  Einzel-Block der Seite. Statt immer robusterer Gegenmaßnahmen wurde
  dieser Block auf eine eigene Seite (`/datetime-settings`,
  `WebServer/pages/datetimesettings.py`) ausgelagert - senkt die größte
  je gebrauchte zusammenhängende Allokation von ~9,7 KB auf ~5,8 KB
  (gemessen, nicht geschätzt). Bei einer neuen, großen Formular-Sektion
  zuerst prüfen, ob sie eine eigene Seite verdient, bevor man sie einer
  bestehenden Seite hinzufügt.
- **Ein Retry führt den ganzen Handler noch einmal aus**, inklusive
  jedes Speichern/Löschen, das ein POST schon vor dem `MemoryError`
  gemacht hat (z. B. im finalen `render()`-Aufruf). Akzeptiert, weil
  jede solche Aktion idempotent ist (dieselben Settings noch einmal
  speichern, bereits gelöschte Einträge noch einmal löschen) - mit einer
  bekannten kosmetischen Ausnahme: die "N Log-Einträge gelöscht"-Zahl auf
  `/statistics` könnte bei einem Retry zu niedrig ausfallen. Bei neuer
  POST-Logik mit Seiteneffekten diese Idempotenz-Anforderung im Hinterkopf
  behalten.

## Kalender-/Datumsrechnung

MicroPython hat **kein `datetime`- und kein `calendar`-Modul** - jede
Kalenderrechnung (Tage addieren, Wochentag bestimmen, Schaltjahre,
Monatsgrenzen) muss von Hand in reiner Integer-Arithmetik passieren,
siehe `_days_from_civil()`/`_civil_from_days()`/`_weekday()`/
`_last_sunday()` in `WebServer/datetimeformat.py` (Howard-Hinnant-
Algorithmus für die zivile Kalenderrechnung). `time.mktime()` ist
bewusst *nicht* die Lösung - auf CPython behandelt es das Tupel als
lokale Zeit (abhängig von der Host-Zeitzone), auf MicroPython gibt es
dieses Konzept gar nicht, beide Plattformen würden sich also
unterscheiden.

Bei neuer Kalenderlogik (z. B. weitere Feiertage/Regeln) die eigene
Implementierung **gegen eine unabhängige Referenz cross-validieren**,
nicht nur gegen handgerechnete Beispiele - bei der EU-Sommerzeit wurde
so gegen Pythons `zoneinfo`-Modul (`Europe/Vienna`) über 20 Jahre
minutengenau verglichen (600.000+ Stichproben, 0 Abweichungen), bevor
es als verifiziert galt:
```python
from zoneinfo import ZoneInfo
import datetime
vienna = ZoneInfo("Europe/Vienna")
# für jeden zu prüfenden UTC-Zeitpunkt t:
expected = t.astimezone(vienna).dst() == datetime.timedelta(hours=1)
```
Das ist kein Ersatz für die normalen Unit-Tests, sondern eine zusätzliche
Absicherung *vor* dem Schreiben der Tests, um die eigene Handrechnung
nicht gegen sich selbst zu prüfen.

## Hardware-Bugs reproduzieren und debuggen

CPython-Unit-Tests mit den Mocks reichen für Logikfehler, aber **mehrere
reale Bugs in diesem Projekt (MemoryError, UTF-8-Byte-Bug, DHCP-Hostname,
der `gc.collect()`-Bug oben) traten ausschließlich auf echter Hardware
auf** und liefen in den Mocks unauffällig durch. Bei einem Bugreport erst
versuchen, ihn 1:1 über `curl` gegen das laufende Gerät nachzustellen
(nicht nur über die Unit-Tests). Lässt sich ein Fehler so nachstellen,
aber die genaue Exception ist unklar (z. B. "leere Antwort" bei einem
serverseitigen Crash), den fraglichen Code-Pfad direkt per Raw-REPL mit
vollem Traceback ausführen:

```python
import serial
ser = serial.Serial(PORT, 115200, timeout=1)
# enter_raw_repl()-Handshake aus scripts/deploy_esp32.py verwenden, dann:
code = '''
import sys
...  # betroffenen Code-Pfad direkt mit denselben Eingaben aufrufen
try:
    ...
except Exception as e:
    sys.print_exception(e)  # voller Traceback, nicht nur str(e)
'''
```

**Wichtig:** Jedes Öffnen des seriellen Ports resettet das Board (Auto-Reset
über DTR/RTS) und unterbricht dadurch `main.py` (WLAN fällt weg, Webserver
ist nicht mehr erreichbar). Nach so einer Diagnose-Session **immer** per
Ctrl-B + Ctrl-D wieder zurück in die freundliche REPL und soft-resetten
(siehe `enter_raw_repl()`/`main()` in `scripts/deploy_esp32.py`), sonst
bleibt das Gerät offline - genau das ist in dieser Session einmal passiert
und musste nachträglich gefixt werden.

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
