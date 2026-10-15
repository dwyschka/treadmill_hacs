# Treadmill (FTMS / FitShow) für Home Assistant

Custom Integration, die Laufbänder und Walking Pads per Bluetooth ausliest und steuert.

- **FTMS** (Bluetooth Fitness Machine Service): Geschwindigkeit, Distanz, Zeit, Steigung, Kalorien, Puls
- **FitShow** (Laufbänder mit Bluetooth-Namen `TF-…`): Start / Pause / Stopp, Zielgeschwindigkeit und
  **echte Schrittzahl** – diese Geräte verweigern die Steuerung per FTMS meist (`Control Not Permitted`)
- Läuft über den Bluetooth-Stack von Home Assistant: eingebauter Adapter oder ESPHome Bluetooth Proxy
  (mit `active: true`)

## Installation

### HACS (One-Click)

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dwyschka&repository=treadmill_hacs&category=integration)

1. Button klicken → Home-Assistant-Instanz bestätigen → in HACS **Herunterladen**
2. Home Assistant neu starten
3. Integration einrichten:

   [![Integration einrichten](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=treadmill_ble)

<details>
<summary>Ohne Button</summary>

HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/dwyschka/treadmill_hacs`, Typ *Integration*,
dann „Treadmill (FTMS / FitShow)“ herunterladen und Home Assistant neu starten.
</details>

### Manuell

Ordner `custom_components/treadmill_ble` nach `<config>/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

Laufband einschalten – es erscheint unter *Einstellungen → Geräte & Dienste* als gefundenes Gerät.
Alternativ: *Integration hinzufügen → Treadmill (FTMS / FitShow)* und das Gerät aus der Liste wählen.

Fahrrad-Ergometer und Rudergeräte mit FTMS werden anhand des Maschinentyps im Advertising ausgefiltert.

## Entitäten

| Typ    | Entität | Hinweis |
|--------|---------|---------|
| Sensor | Geschwindigkeit, Distanz, Trainingszeit, Steigung, Kalorien, Herzfrequenz, Schrittfrequenz | Ø-Geschwindigkeit standardmäßig deaktiviert |
| Sensor | Schritte | Attribut `source`: `treadmill` (vom Laufband), `cadence` (aus Schrittfrequenz), `estimated` (Distanz ÷ Schrittlänge) |
| Sensor | Status | `idle`, `starting`, `running`, `paused`, `stopped`, `safety_key`, `error`, `calibrating` |
| Button | Start, Pause, Stopp | |
| Number | Zielgeschwindigkeit | Bereich meldet das Laufband; Änderungen nur während das Band läuft |
| Switch | Bluetooth-Verbindung | Aus = Laufband für andere Apps freigeben |

**Optionen:** Schrittlänge (für die Schätzung, Standard 0,70 m) und Körpergewicht (wird an FitShow-Geräte übertragen).

## Verhalten

- Home Assistant verbindet automatisch, sobald das Laufband per Bluetooth sichtbar ist. Ist es aus, sind die
  Entitäten „nicht verfügbar“.
- Ein BLE-Laufband erlaubt meist nur **eine** Verbindung. Solange Home Assistant verbunden ist, kann sich die
  Hersteller-App nicht verbinden – dafür den Schalter *Bluetooth-Verbindung* ausschalten.
- Bei FitShow wird der Status jede Sekunde abgefragt; Befehle werden nacheinander gesendet und bestätigt.

### Beispiel-Automation

```yaml
automation:
  - alias: Laufband nach 30 Minuten stoppen
    triggers:
      - trigger: numeric_state
        entity_id: sensor.tf_123456_trainingszeit
        above: 1800
    actions:
      - action: button.press
        target:
          entity_id: button.tf_123456_stopp
```

Die Entity-IDs hängen vom Gerätenamen und der Sprache ab – unter *Geräte & Dienste* nachsehen.

## Entwicklung

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Die Tests simulieren ein FitShow-Laufband (FTMS-Daten + FitShow-Steuerung) und decken Protokoll,
Gerätelogik, Config Flow und Entitäten ab.

## Danke

Das FitShow-Protokoll stammt aus [qdomyos-zwift](https://github.com/cagnulein/qdomyos-zwift)
(`src/devices/fitshowtreadmill`).
