"""Constants for the Treadmill BLE integration."""

from __future__ import annotations

DOMAIN = "treadmill_ble"

CONF_STRIDE_LENGTH = "stride_length"
CONF_WEIGHT = "weight"
DEFAULT_STRIDE_LENGTH = 0.70  # m
DEFAULT_WEIGHT = 75  # kg – sent to FitShow devices as user profile

DEFAULT_SPEED_RANGE = (0.5, 6.0)  # km/h, until the treadmill reports its real range
RECONNECT_INTERVAL = 15  # s between connection attempts
FITSHOW_POLL_INTERVAL = 1.0  # s
COMMAND_TIMEOUT = 5.0  # s

# Bluetooth names of treadmills with a FitShow module (see qdomyos-zwift)
FITSHOW_NAME_PREFIXES = ("TF", "SP-TM")

STEPS_SOURCE_TREADMILL = "treadmill"
STEPS_SOURCE_SENSOR = "cadence"
STEPS_SOURCE_ESTIMATED = "estimated"
