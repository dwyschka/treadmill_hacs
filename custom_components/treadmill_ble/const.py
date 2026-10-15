"""Konstanten für die Treadmill-BLE-Integration."""

from __future__ import annotations

DOMAIN = "treadmill_ble"

CONF_STRIDE_LENGTH = "stride_length"
CONF_WEIGHT = "weight"
DEFAULT_STRIDE_LENGTH = 0.70  # m
DEFAULT_WEIGHT = 75  # kg – wird bei FitShow als Nutzerprofil übertragen

DEFAULT_SPEED_RANGE = (0.5, 6.0)  # km/h, bis das Laufband den echten Bereich meldet
RECONNECT_INTERVAL = 15  # s zwischen Verbindungsversuchen
FITSHOW_POLL_INTERVAL = 1.0  # s
COMMAND_TIMEOUT = 5.0  # s

# Bluetooth-Namen von Laufbändern mit FitShow-Modul (nach qdomyos-zwift)
FITSHOW_NAME_PREFIXES = ("TF-",)

STEPS_SOURCE_TREADMILL = "treadmill"
STEPS_SOURCE_SENSOR = "cadence"
STEPS_SOURCE_ESTIMATED = "estimated"
