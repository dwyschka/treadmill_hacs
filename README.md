# Treadmill (FTMS / FitShow) for Home Assistant

Custom integration that reads and controls treadmills and walking pads over Bluetooth.

- **FTMS** (Bluetooth Fitness Machine Service): speed, distance, time, incline, calories, heart rate
- **FitShow** (treadmills with Bluetooth names like `TF…`): start / pause / stop, target speed and the
  **real step count** – these devices usually refuse control via FTMS (`Control Not Permitted`)
- Uses Home Assistant's Bluetooth stack: a local adapter or an ESPHome Bluetooth proxy with
  **active connections** enabled

## Installation

### HACS (one click)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dwyschka&repository=treadmill_hacs&category=integration)

1. Click the button → confirm your Home Assistant instance → **Download** in HACS
2. Restart Home Assistant
3. Set up the integration:

   [![Set up integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=treadmill_ble)

<details>
<summary>Without the button</summary>

HACS → ⋮ → *Custom repositories* → `https://github.com/dwyschka/treadmill_hacs`, type *Integration*,
then download "Treadmill (FTMS / FitShow)" and restart Home Assistant.
</details>

### Manual

Copy `custom_components/treadmill_ble` to `<config>/custom_components/` and restart Home Assistant.

## Setup

Switch the treadmill on – it shows up under *Settings → Devices & services* as a discovered device.
Alternatively use *Add integration → Treadmill (FTMS / FitShow)* and pick the device from the list.

Discovered automatically are all devices advertising **FTMS** as well as FitShow devices (`TF-…`,
`TF0…`–`TF9…`, `SP-TM…`). If yours is not recognized, *Add integration* also lists every other named
Bluetooth device in range, so you can pick it manually. Use **↻ Search again** to reload the list.

### Nothing found?

- The treadmill must not be connected to another app (vendor app, web app in a browser) – while
  connected it stops advertising.
- Check *Settings → Devices & services → Bluetooth → Advertisement monitor* to see whether Home
  Assistant receives the device and through which source.
- Entries marked **"not connectable"** are only heard by a passive scanner. Home Assistant needs a
  scanner that supports **active connections** within range of the treadmill:
  - ESPHome Bluetooth proxy with
    ```yaml
    esp32_ble_tracker:
      scan_parameters:
        active: true
    bluetooth_proxy:
      active: true
    ```
  - or a local Bluetooth adapter on the Home Assistant host.
  - Passive-only scanners (e.g. Shelly devices, TECHO5 Echo firmware) can't be used for connecting.

## Entities

| Type   | Entity | Notes |
|--------|--------|-------|
| Sensor | Speed, distance, elapsed time, incline, calories, heart rate, cadence | Average speed is disabled by default |
| Sensor | Steps | Attribute `source`: `treadmill` (reported by the treadmill), `cadence` (from cadence sensor), `estimated` (distance ÷ stride length) |
| Sensor | Status | `idle`, `starting`, `running`, `paused`, `stopped`, `safety_key`, `error`, `calibrating` |
| Button | Start, pause, stop | |
| Number | Target speed | Range is reported by the treadmill; changes only while the belt is running |
| Switch | Bluetooth connection | Off = release the treadmill for other apps |

**Options:** stride length (for the step estimate, default 0.70 m) and body weight (sent to FitShow devices).

The UI is available in English and German.

## Behavior

- Home Assistant connects automatically as soon as the treadmill is visible over Bluetooth.
- **When the treadmill is switched off**, the integration stays loaded normally – there is **no setup
  error**. Its entities simply become *unavailable* until the treadmill is switched on again, then it
  reconnects on its own. Only the *Bluetooth connection* switch stays available.
- A BLE treadmill usually accepts only **one** connection. While Home Assistant is connected, the
  vendor app can't connect – turn off the *Bluetooth connection* switch to release it.
- FitShow devices are polled for their status every second; commands are sent one at a time and
  acknowledged by the treadmill.

### Example automation

```yaml
automation:
  - alias: Stop treadmill after 30 minutes
    triggers:
      - trigger: numeric_state
        entity_id: sensor.tf_123456_elapsed_time
        above: 1800
    actions:
      - action: button.press
        target:
          entity_id: button.tf_123456_stop
```

Entity IDs depend on the device name and your language – check *Devices & services*.

## Development

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

The tests simulate a FitShow treadmill (FTMS data + FitShow control) and cover the protocol, device
logic, config flow and entities.

## Credits

The FitShow protocol is based on [qdomyos-zwift](https://github.com/cagnulein/qdomyos-zwift)
(`src/devices/fitshowtreadmill`).
