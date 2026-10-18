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
(`WebServer/loggingsettings.py`), ein Deckel für Fehler- +
Benachrichtigungs-Log zusammen (`enforce_storage_budget()`, Default
15 % des *verfügbaren* Speichers — bewusst nicht der Gesamtkapazität,
damit der Deckel mitschrumpft, falls der freie Speicher aus anderen
Gründen knapper wird — ebenfalls über `/settings` änderbar) sowie ein
Formular auf
`/statistics`, um Log-Einträge älter als X Minuten manuell zu löschen.
Außerdem ein einheitliches Datums-/Zeit-Anzeigeformat für alle Seiten,
wählbar über `/settings` nach Country/Culture (z. B. `17.10.2026
07:05:09` für Österreich vs. `10/17/2026 07:05:09 AM` für die USA) plus
ein fester, ebenfalls über `/settings` wählbarer UTC-Offset statt einer
echten Zeitzone — eine vollständige IANA-Zeitzonendatenbank mit
Sommerzeit-Regeln je Land wäre für den ESP32-Flash zu groß und könnte
auf dem Gerät ohnehin nicht aktuell gehalten werden. Dazu eine optionale
automatische Sommerzeit-Umstellung nach der EU-Regel (letzter Sonntag im
März/Oktober, 01:00 UTC) über eine Checkbox auf `/settings` — das Projekt
ist damit vorerst bewusst auf Europa beschränkt, andere Regionen (USA,
Südhalbkugel, ...) haben andere Umstellungstermine oder keine Sommerzeit
und müssten ihren UTC-Offset bei Bedarf selbst zweimal im Jahr ändern.
Die Berechnung (Wochentag der letzten Sonntage im März/Oktober) wurde
gegen Pythons `zoneinfo`-Modul (Europe/Vienna) minutengenau über 20 Jahre
verifiziert, ohne eine einzige Abweichung. Dabei den großen
`WebServer/statusserver.py` (704 Zeilen, fünf verschiedene
Zuständigkeiten in einer Klasse) in einen schlanken HTTP-Kern
(`WebServer/webserver.py`, Klasse `WebServer`) plus ein Modul je Seite
unter `WebServer/pages/` aufgeteilt — reines Verschieben, keine
Logikänderung, 176 Tests blieben unverändert grün. Dabei auf echter
Hardware einen dritten `MemoryError` gefunden: `/settings` (die größte
Seite) schlug beim Speichern fehl, weil `main.py`s `gc.collect()` erst
*nach* `handle_requests()` läuft und die Fragmentierung aus dem Rest
des Loop-Durchlaufs (Sensoren, WLAN, Telegram) beim Bearbeiten der
nächsten Anfrage noch da war — behoben durch einen zusätzlichen
`gc.collect()`-Aufruf direkt am Anfang von `handle_requests()`. Als
`/settings` durch die Sommerzeit-Checkbox noch einmal größer wurde, trat
derselbe Fehler erneut auf (Fragmentierung entsteht auch *während* des
Renderns, z. B. beim Aufbau der Dropdown-Optionen) — statt eines
weiteren Einzel-Flickens jetzt eine generelle Selbstheilung:
`_render_with_retry()` fängt einen `MemoryError` beim Rendern
irgendeiner Seite ab, räumt noch einmal auf und versucht es exakt
einmal erneut, bevor der Fehler durchschlägt. Ursächlicher angegangen,
nachdem der Fehler trotzdem noch einmal auftrat: Datum-/Zeit-Format,
Zeitzone und Sommerzeit-Checkbox wurden von `/settings` auf eine eigene
Seite `/datetime-settings` ausgelagert — das Culture-/Zeitzonen-Dropdown
allein hat ~45 Optionen und war mit Abstand der größte Einzel-Block;
die Aufteilung senkt die größte benötigte zusammenhängende Allokation
von ~9,7 KB auf ~5,8 KB.
Aus einem Code-Review: Ein Sensor-Lesefehler (`-999`, jetzt als
Konstante `SENSOR_ERROR` in `Temperature/temperature.py`) lag unter
`TEMPERATURE_MIN` und schaltete den Lüfter bei jedem Loop-Durchlauf ein —
anhand eines toten Sensors statt einer echten Messung. Bei Sensorfehler
bleibt der Lüfter jetzt in seinem aktuellen Zustand. Damit ein toter
Sensor nicht nur still auf der Statusseite als `n/a` auftaucht, meldet
das Gerät ihn jetzt per Telegram (sofort, dann alle 12 h, Entwarnung
sobald er wieder stabil misst; über `/settings` abschaltbar). Dabei auf
echter Hardware gemessen, dass ein fehlender Sensor das Fehler-Log mit
zwei identischen Einträgen pro Loop-Durchlauf bis zur 200er-Grenze
füllte — 24 KB RAM, genug, dass auf einem Board mit MicroPython 1.16
jede Seite inkl. `/` mit `MemoryError` scheiterte. Gleiche Fehler
innerhalb von 12 h werden seither zu einem Eintrag mit Zähler
zusammengefasst. Die Rohdaten des Fehler-Logs lassen sich über
`/error-log.json` ansehen oder herunterladen.
Dazu ein eigenes Einrichtungs-WLAN (`Captain-Nemo-Setup`), über das man
dem Gerät ohne USB-Kabel ein neues Heim-WLAN zuweisen kann — automatisch
ohne gespeicherte Zugangsdaten oder nach 5 min ohne Heim-WLAN, manuell
per doppeltem RESET-Druck (ein einzelner Druck ist für den ESP32 nicht
von einem Stromausfall zu unterscheiden); die LED blinkt währenddessen
im Sekundentakt. Ein kleiner DNS-Server beantwortet im Einrichtungs-WLAN
jede Anfrage mit der eigenen IP, sodass `http://captain-nemo-setup/`
direkt auf die WLAN-Einstellungen führt. Dabei im Deploy-Skript eine
fehlende Datei (`WebServer/pages/datetimesettings.py`) in der
Übertragungsliste gefunden, die einen kompletten Neu-Deploy auf ein
leeres Board beim Start hätte abstürzen lassen. Auf dem ESP32 ohne
PSRAM reichte der Speicher danach mit keiner Firmware mehr: Auf 1.16
zersplitterte das Übersetzen des Quellcodes auf dem Board den Heap so,
dass keine Seite mehr renderte; auf 1.29 nimmt der wachsende Python-Heap
dem WLAN-/TLS-Speicher so viel weg, dass der Telegram-Aufruf hängt (beides
auf echter Hardware gemessen). Lösung: zurück auf 1.16, das Deploy-Skript
kompiliert die Module jetzt vorab zu `.mpy`, und große Seiten werden in
kleinen Stücken gesendet statt am Stück im RAM zusammengebaut.
Zusätzlich ein Zeitlimit für Telegram: Bei Internet-Ausfall (WLAN noch da)
blockierte der Versand die Hauptschleife 18 s und das Board startete per
Watchdog alle ~22 s neu — jetzt bricht ein zeitbegrenzter
Verbindungstest nach 5 s ab, danach pausiert Telegram 5 min, und der
Watchdog wird zwischen WLAN-, NTP- und Telegram-Schritt gefüttert. Ein
eigener HTTPS-Client hätte auch das Lesen begrenzt, kostete auf dem Board
aber genug RAM, dass keine Seite mehr renderte; `urequests` liegt dagegen
in der Firmware (Flash). Dabei die eigentliche Speicher-Ursache gefunden:
Beim Laden der Module blieb der Heap so zersplittert, dass bei ~38 KB
frei kein 2-KB-Block mehr übrig war. Abhilfe: `main.py` ist jetzt ein
Starter, der während der Imports `gc.threshold()` setzt, das Programm
selbst liegt in `aquarium.py` (vorkompiliert), und jede Seite reicht das
CSS als eigenes Stück durch, statt es per `.format()` zu kopieren.

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
| [test_main.py](tests/test_main.py) | 32 | Hauptschleife: Watchdog-Fütterung (auch zwischen WLAN-, NTP- und Telegram-Schritt), Starter `main.py` (`gc.threshold()` beim Laden), Fehlerisolierung pro Durchlauf, Sensor-Wiederverwendung, Lüftersteuerung (inkl. kein Schalten bei Sensorfehler), Verdrahtung der Sensor-Fehler-Meldung und des Einrichtungs-WLANs, Absicherung der Fehler-Protokollierung, DNS-Polling im Sleep, Verdrahtung der Web-Oberfläche und der Logs, RAM-/Flash-Warnschwellen, Log-Speicher-Deckel |
| [test_telegram.py](tests/test_telegram.py) | 21 | Telegram-Versand: Zeitlimit beim Verbindungsaufbau (5 s statt 18 s), 5-Minuten-Pause nach Fehlschlag, HTTP ≠ 200 als Fehler, Response-Schließung, UTF-8-Byte-Kodierung, Erfolgs-Rückmeldung von `notify()`, Benachrichtigungs-Timing, Fehler-/Benachrichtigungs-Protokoll |
| [test_temperature.py](tests/test_temperature.py) | 6 | Sensor-Mittelwertbildung, Absturzsicherheit bei Lesefehlern, Fehlerprotokollierung |
| [test_wlanconnection.py](tests/test_wlanconnection.py) | 12 | WLAN-Verbindung, DHCP-Hostname, NTP-Zeitsync-Retry, Netzwerk-Scan (inkl. 30s-Cache), Signalstärke, Fehlerprotokollierung |
| [test_deploy.py](tests/test_deploy.py) | 13 | Deploy-Skript: welche Dateien zu `.mpy` kompiliert werden (nicht `boot.py`/`main.py`/`config.py`), Löschen alter `.py` auf dem Board, Compiler-Wahl je Firmware, Vollständigkeit der Übertragungsliste, echter v5-Compiler-Lauf (falls installiert) |
| [test_settings.py](tests/test_settings.py) | 3 | Persistenz des Aquarium-Namens über Neustarts |
| [test_setupmode.py](tests/test_setupmode.py) | 15 | Wann das Einrichtungs-WLAN auf-/zugeht (inkl. DNS-Polling nur solange aktiv): ohne Zugangsdaten, nach doppeltem RESET (10-min-Zeitlimit, nicht solange jemand verbunden ist), Fallback nach 5 min offline inkl. Heim-WLAN-Retry höchstens 1×/min und nie bei verbundenem Client |
| [test_doublereset.py](tests/test_doublereset.py) | 5 | Erkennung des doppelten RESET-Drucks, einmaliges Abholen der Anforderung, keine Marker-Reste bei unterbrochenem Boot |
| [test_accesspoint.py](tests/test_accesspoint.py) | 8 | Einrichtungs-WLAN (WPA2, Passwort ≥ 8 Zeichen, Config nach active()), DNS-Server nur solange aktiv, LED-Blinken im Sekundentakt, Abschalten von WLAN + LED |
| [test_dnsserver.py](tests/test_dnsserver.py) | 10 | Catch-all-DNS im Einrichtungs-WLAN: A-Antwort mit eigener IP für jeden Namen, leere AAAA-Antwort, kaputte/kurze/Antwort-Pakete ignoriert, echte UDP-Anfrage (zusätzlich mit `dig` gegengeprüft) |
| [test_wifisettings.py](tests/test_wifisettings.py) | 11 | Persistenz + Validierung der WLAN-Zugangsdaten (SSID-/Passwort-Längen nach 802.11/WPA2-Spezifikation) |
| [test_webserver.py](tests/test_webserver.py) | 76 | HTTP-Server: Routing, CSS als eigenes Stück statt Kopie in jeder Seite, stückweises Senden großer Seiten (`/datetime-settings` als Teilstücke), Weiterleitung `captain-nemo-setup` im Einrichtungs-WLAN, Rohdaten-Download `/error-log.json` (Auth auch mit Query-String, nosniff, Download-Header), Sensor-Fehler-Checkbox auf `/settings` (inkl. atomar), Zähler zusammengefasster Fehler auf `/statistics`, HTTP-Basic-Auth, HTML-Escaping (XSS), Request-Size-Limit, Statistik-Seite (inkl. Zeilenbegrenzung gegen MemoryError), Warnschwellen-Formular, Protokollierungs-Checkboxen, Logs-löschen-Formular, `/datetime-settings` (Datum-/Zeit-Format- + Zeitzonen- + EU-Sommerzeit-Auswahl, inkl. Tagesgrenzen-Übertrag, getrennt von `/settings`), `gc.collect()` + Retry-nach-`MemoryError` vor jeder Anfrage, echte Socket-Kommunikation über Loopback |
| [test_eventlog.py](tests/test_eventlog.py) | 23 | Persistierter Event-Log: 30-Tage-Fenster, Begrenzung auf 200 Einträge, stückweises Senden der Rohdatei, Zusammenfassen gleicher Einträge mit Zähler (Fenstergrenze, Persistenz, nicht beim Benachrichtigungs-Log), Dateigröße, Alters-basiertes Löschen, Speicher-Budget-Durchsetzung |
| [test_errorlog.py](tests/test_errorlog.py) | 7 | Exception → Fehlerkategorie/-code/-meldung, Ein-/Ausschalten je Kategorie, Zusammenfassen innerhalb von 12 h |
| [test_sensoralert.py](tests/test_sensoralert.py) | 17 | Sensor-Fehler-Meldung: Bestätigung nach 3 Fehl-Messungen, 12-h-Erinnerung, Nachholen wenn offline, Retry-Pause nach Sendefehler, Entwarnung erst nach stabilen Werten (kein Flattern), Sensoren unabhängig, Persistenz + Fallbacks der Einstellung |
| [test_loggingsettings.py](tests/test_loggingsettings.py) | 4 | Persistenz der Protokollierungs-Ein/Aus-Schalter je Kategorie |
| [test_loginlog.py](tests/test_loginlog.py) | 3 | Login-Zeitpunkt-Persistenz, Rückgabe des *vorherigen* Logins |
| [test_systemstats.py](tests/test_systemstats.py) | 2 | RAM-/Flash-Belegung (`used + free == total`) |
| [test_monitoringsettings.py](tests/test_monitoringsettings.py) | 7 | Persistenz + Validierung der RAM-/Flash-/Log-Speicher-Warnschwellen (5–50 %) |
| [test_datetimeformat.py](tests/test_datetimeformat.py) | 34 | Datums-/Zeit-Formatierung je Country/Culture (Tag/Monat-Reihenfolge, 12h-/24h-Anzeige inkl. Mitternacht/Mittag), Fallback auf ISO 8601 bei unbekannter Culture, UTC-Offset-Verschiebung inkl. Tages-/Monats-/Jahres-/Schaltjahr-Übertrag, Halb-/Viertelstunden-Offsets, EU-Sommerzeit-Umstellung (Übergangs-Instant auf die Sekunde, inkl. Schaltjahr) |
| [test_datetimesettings.py](tests/test_datetimesettings.py) | 8 | Persistenz + Validierung der gewählten Culture, des UTC-Offsets und der EU-Sommerzeit-Checkbox, Fallback bei veralteter/ungültiger/fehlender gespeicherter Culture bzw. Offset bzw. Sommerzeit-Flag |

**Gesamt: 317 Tests**, Stand des letzten vollständigen Durchlaufs in diesem
Dokument. Viele Tests sind als Regressionstests für konkret auf der
Hardware beobachtete Bugs angelegt (siehe Docstrings in den jeweiligen
Testdateien) — sie beschreiben bewusst, *welches reale Problem* sie
verhindern, nicht nur was sie prüfen.
