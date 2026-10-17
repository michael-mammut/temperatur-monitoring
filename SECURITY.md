# Sicherheit: WLAN-Zugangsdaten & Web-Oberfläche

Dieses Dokument beschreibt, wie WLAN-Zugangsdaten gespeichert werden, wie die
Web-Oberfläche (`/settings`, `/wifi-settings`, `/statistics`) abgesichert ist,
und welche Grenzen diese Absicherung bewusst hat.

## Wo WLAN-Zugangsdaten gespeichert werden

Zwei Orte, **beide im Klartext**:

| Ort | Wann aktiv |
|---|---|
| [WlanNetwork/config.py](WlanNetwork/config.py) | Werte vom ersten Flash-Vorgang. Nicht in Git (`.gitignore`). |
| `wifi_settings.json` auf dem Flash des ESP32 | Sobald einmal über `/wifi-settings` ein Netzwerk gespeichert wurde — überschreibt die Werte aus `config.py` dauerhaft. |

[WlanNetwork/wifisettings.py](WlanNetwork/wifisettings.py) liest beim Boot
zuerst die JSON-Datei; existiert sie noch nicht, gelten die Werte aus
`config.py` als Fallback:

```python
with open('wifi_settings.json', 'w') as f:
    ujson.dump({'ssid': ssid, 'password': password}, f)
```

### Warum Klartext unvermeidbar ist

Ein WLAN-Client muss die echte WPA2-Passphrase aktiv über Funk senden, um
sich zu authentifizieren — anders als ein Login-Passwort, das man nur
*hashen und vergleichen* muss. `network.WLAN.connect()` in MicroPython
akzeptiert ausschließlich die Klartext-Passphrase, keinen vorab
abgeleiteten Schlüssel (geprüft: offizielle MicroPython-Doku + ESP32-Quelltext,
kein dokumentierter Weg für einen rohen PSK). Deshalb speichert **jedes**
WLAN-IoT-Gerät (Router, Smart-Plugs, Shelly, Tasmota, …) das Passwort aus
demselben Grund im Klartext — es muss sich nach einem Stromausfall selbst
neu verbinden können, ohne dass jemand es erneut eingibt.

**Konsequenz:** Wer physischen oder seriellen (USB/REPL) Zugriff auf den
ESP32 bekommt, kann das WLAN-Passwort auslesen. Der einzige wirksame Schutz
dagegen ist physische Zugangskontrolle zum Gerät selbst, keine Software.

## Zugriffsschutz für die Web-Oberfläche

`/settings` (Aquarium-Name ändern), `/wifi-settings` (WLAN-Zugangsdaten
ändern) und `/statistics` (System-/Fehlerstatistik) sind per **HTTP Basic
Auth** geschützt. `/` (Status-Seite) bleibt bewusst öffentlich — sie zeigt
nur Messwerte, keine sensiblen Daten.

Jeder erfolgreiche Login auf einer der drei geschützten Seiten wird
persistiert ([WebServer/loginlog.py](WebServer/loginlog.py)) und auf
`/statistics` als "Letzter Login" angezeigt — dabei immer der *vorherige*
Zeitpunkt, nicht der gerade stattfindende (sonst stünde dort trivial immer
"gerade jetzt").

- Admin-Passwort liegt in [WebServer/config.py](WebServer/config.py)
  (`ADMIN_PASSWORD`) — nicht in Git, analog zu den WLAN-/Telegram-Secrets.
- Ändern: Wert in der Datei anpassen und neu auf den ESP32 übertragen.
- Der Passwort-Vergleich läuft **konstant-zeitig** (`_constant_time_equals`
  in [WebServer/statusserver.py](WebServer/statusserver.py)), um
  Timing-Angriffe zu erschweren.
- Ohne oder mit falschem Passwort antwortet das Gerät mit `401 Unauthorized`
  — unabhängig davon, ob der Pfad überhaupt existiert.

## Weitere Schutzmaßnahmen (alle Eingaben)

| Angriffsvektor | Maßnahme |
|---|---|
| XSS über Aquarium-Namen, WLAN-SSID (auch von fremden, bösartig benannten Netzwerken in der Scan-Liste!) | HTML-Escaping aller Ausgaben (`_escape_html`) |
| Speicher-Erschöpfung durch riesige/lügende `Content-Length` | Jede Anfrage wird hart auf 2048 Bytes begrenzt (`_MAX_REQUEST_BYTES`), unabhängig vom angegebenen Header |
| Ungültige/zu lange SSID oder Passwort | Validierung nach 802.11-/WPA2-Spezifikation (SSID ≤ 32 Byte, Passwort 8–63 Zeichen oder leer für offene Netze) vor jedem Speichern |
| Falsches WLAN-Passwort führt zum Aussperren | Speichern + Neustart passiert nur nach erfolgreicher Validierung; bei einem Fehler bleibt das Gerät mit den alten, funktionierenden Zugangsdaten online |
| Passwort-Leck über die Oberfläche selbst | Passwortfeld ist write-only — der gespeicherte Wert wird nie wieder angezeigt, auch nicht im HTML-Quelltext |
| XSS über Fehlermeldungen auf `/statistics` | Fehlermeldungen stammen aus internem Exception-Text, nicht direkt aus Nutzereingaben — werden aber trotzdem HTML-escaped ausgegeben, falls eine Meldung einmal externe Daten enthält (z. B. eine Server-Antwort) |
| Unbegrenztes Wachstum von Fehler-/Benachrichtigungs-Log | [WebServer/eventlog.py](WebServer/eventlog.py) begrenzt jedes Log hart auf 200 Einträge, unabhängig vom Alter — ein Crash-Loop kann die Datei (und die JSON-Parse-Kosten beim Laden) nicht unbegrenzt wachsen lassen |
| `MemoryError` beim Rendern von `/statistics` durch zu viele Fehler-Zeilen in einem Stück | Tabelle zeigt maximal die letzten 20 von bis zu 200 Einträgen — auf echter Hardware reproduziert und verifiziert (ein `join()` über 200 Zeilen schlug an der Heap-Fragmentierung fehl, auch bei insgesamt ausreichend freiem Speicher) |
| Ungültige RAM-/Flash-/Log-Warnschwelle auf `/settings` | Werte müssen zwischen 5 % und 50 % liegen ([Monitoring/settings.py](Monitoring/settings.py)); eine fehlgeschlagene Validierung speichert **nichts** — auch nicht den gleichzeitig eingereichten Aquarium-Namen oder die Protokollierungs-Checkboxen (atomar) |
| Manipulierte Country/Culture- oder UTC-Offset-Werte auf `/settings` (z. B. ein nie angebotener Offset wie 37 Minuten) | Beide Werte werden serverseitig gegen die feste Liste der angebotenen Optionen geprüft ([WebServer/datetimesettings.py](WebServer/datetimesettings.py)); eine fehlgeschlagene Validierung speichert **nichts** — atomar mit Name, Warnschwellen und Protokollierungs-Checkboxen |
| Unkontrolliertes Wachstum der Logs relativ zum Flash-Speicher | `enforce_storage_budget()` ([WebServer/eventlog.py](WebServer/eventlog.py)) hält Fehler- + Benachrichtigungs-Log zusammen unter einem konfigurierbaren Anteil (Default 15 %) des *verfügbaren* Speichers (frei + aktuelle Log-Größe) — nicht der Gesamtkapazität, damit der Deckel automatisch mitschrumpft, falls der freie Speicher aus anderen Gründen knapper wird. Geprüft bei jedem Loop-Durchlauf, unabhängig vom 200-Einträge-Limit pro Log. |
| Ungültige Minutenangabe beim manuellen Logs-Löschen auf `/statistics` | Nicht-numerische oder nicht-positive Werte werden abgelehnt, ohne irgendetwas zu löschen |

## Bekannte Grenzen (bewusst in Kauf genommen)

- **Kein TLS/HTTPS.** Ein vollwertiger TLS-Stack ist auf dem ESP32 mit
  MicroPython unrealistisch (Speicher- und Rechenaufwand). Basic-Auth-Daten
  sind damit für jeden, der den WLAN-Traffic im selben Netz mitlesen kann,
  sichtbar (Base64 ist keine Verschlüsselung).
- **Kein CSRF-Schutz.** Basic Auth hat kein eingebautes CSRF-Token-System;
  ein geöffneter bösartiger Tab im selben Browser könnte theoretisch einen
  authentifizierten Request auslösen, falls die Zugangsdaten vom Browser
  zwischengespeichert sind.
- **Scan-Zeit blockiert die Hauptschleife.** `/wifi-settings` scannt
  Netzwerke (mehrere Sekunden), während der Hauptloop (Sensor-Messung,
  Telegram, Watchdog-Feed) steht. Ergebnis wird 30 s gecacht
  (`WlanConnection.scan_networks`), um das zu entschärfen — ganz vermeiden
  lässt es sich mit diesem Single-Thread-Design nicht.
- **Wer das Admin-Passwort hat, kann die Protokollierung abschalten oder
  Logs löschen.** Die Kategorie-Checkboxen auf `/settings` und der
  "Logs löschen"-Button auf `/statistics` sind bewusst mächtig — jemand
  mit (legitimem oder erschlichenem) Zugriff könnte damit eigene Spuren
  verwischen. Da es keine zweite, unabhängige Protokoll-Ebene gibt, ist
  das Admin-Passwort der einzige Schutz dagegen.

## Empfehlung

Dieses Gerät ist für den Betrieb im **vertrauenswürdigen Heimnetz** gedacht.
Die Web-Oberfläche **niemals per Port-Forwarding ins Internet freigeben** —
ohne TLS wäre das WLAN-Passwort und das Admin-Passwort dann im Klartext über
das offene Internet einsehbar.
