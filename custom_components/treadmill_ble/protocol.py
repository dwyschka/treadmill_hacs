"""Protokoll-Helfer für FTMS und FitShow – ohne Home-Assistant-Abhängigkeiten.

FTMS: Bluetooth SIG "Fitness Machine Service 1.0".
FitShow: proprietäres Protokoll nach qdomyos-zwift (src/devices/fitshowtreadmill).
"""

from __future__ import annotations

import struct
from typing import Any


def uuid16(short: int) -> str:
    """16-bit-UUID in die volle Bluetooth-Base-UUID umwandeln."""
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


# --- FTMS --------------------------------------------------------------------

FTMS_SERVICE = uuid16(0x1826)
TREADMILL_DATA = uuid16(0x2ACD)
FTMS_CONTROL_POINT = uuid16(0x2AD9)
FTMS_STATUS = uuid16(0x2ADA)

HR_SERVICE = uuid16(0x180D)
HR_MEASUREMENT = uuid16(0x2A37)
RSC_SERVICE = uuid16(0x1814)
RSC_MEASUREMENT = uuid16(0x2A53)

FTMS_OP_REQUEST_CONTROL = 0x00
FTMS_OP_SET_TARGET_SPEED = 0x02
FTMS_OP_START_RESUME = 0x07
FTMS_OP_STOP_PAUSE = 0x08
FTMS_OP_RESPONSE = 0x80

FTMS_RESULT_SUCCESS = 0x01
FTMS_RESULT_CONTROL_NOT_PERMITTED = 0x05
FTMS_RESULT_TEXT = {
    0x01: "Erfolgreich",
    0x02: "Nicht unterstützt",
    0x03: "Ungültiger Parameter",
    0x04: "Fehlgeschlagen",
    0x05: "Steuerung nicht erlaubt",
}

def parse_treadmill_data(data: bytes) -> dict[str, Any]:
    """Treadmill Data (0x2ACD) parsen. Nur gesendete Felder sind enthalten."""
    flags = struct.unpack_from("<H", data, 0)[0]
    o = 2
    d: dict[str, Any] = {}

    def has(bit: int) -> bool:
        return bool(flags & (1 << bit))

    def read(fmt: str) -> int:
        nonlocal o
        value = struct.unpack_from(fmt, data, o)[0]
        o += struct.calcsize(fmt)
        return value

    if not has(0):  # "More Data" = 0 → Instantaneous Speed vorhanden
        d["speed"] = read("<H") / 100  # km/h
    if has(1):
        d["avg_speed"] = read("<H") / 100
    if has(2):
        d["distance"] = data[o] | data[o + 1] << 8 | data[o + 2] << 16  # m
        o += 3
    if has(3):
        d["incline"] = read("<h") / 10  # %
        read("<h")  # Ramp Angle
    if has(4):
        read("<H")  # Positive Elevation Gain
        read("<H")  # Negative Elevation Gain
    if has(5):
        read("<B")  # Instantaneous Pace
    if has(6):
        read("<B")  # Average Pace
    if has(7):
        d["energy"] = read("<H")  # kcal
        read("<H")  # kcal/h
        read("<B")  # kcal/min
    if has(8):
        d["heart_rate"] = read("<B")
    if has(9):
        read("<B")  # MET
    if has(10):
        d["elapsed_time"] = read("<H")  # s
    if has(11):
        read("<H")  # Remaining Time
    return d


def parse_ftms_status(data: bytes) -> tuple[str | None, bool | None]:
    """Fitness Machine Status (0x2ADA) → (Status, läuft?)."""
    code = data[0]
    if code == 0x02 and len(data) > 1:
        return ("paused", False) if data[1] == 0x02 else ("stopped", False)
    return {
        0x01: ("idle", False),
        0x03: ("stopped", False),
        0x04: ("running", True),
    }.get(code, (None, None))


def parse_heart_rate(data: bytes) -> int:
    """Heart Rate Measurement (0x2A37)."""
    return struct.unpack_from("<H", data, 1)[0] if data[0] & 0x01 else data[1]


def parse_rsc_cadence(data: bytes) -> int:
    """Running Speed and Cadence Measurement (0x2A53) → Schritte/min."""
    return data[3]


# --- FitShow -----------------------------------------------------------------

# Bekannte Varianten: (Service, Write-Characteristic, Notify-Characteristic)
FITSHOW_VARIANTS = [
    (uuid16(0xFFF0), uuid16(0xFFF2), uuid16(0xFFF1)),
    (uuid16(0xFFE0), uuid16(0xFFE1), uuid16(0xFFE4)),
    (uuid16(0xAE00), uuid16(0xAE01), uuid16(0xAE02)),
]
FITSHOW_SERVICES = [v[0] for v in FITSHOW_VARIANTS]

FITSHOW_HEADER = 0x02
FITSHOW_FOOTER = 0x03

FITSHOW_SYS_INFO = 0x50
FITSHOW_SYS_STATUS = 0x51
FITSHOW_SYS_DATA = 0x52
FITSHOW_SYS_CONTROL = 0x53

FITSHOW_CONTROL_USER = 0x00
FITSHOW_CONTROL_START = 0x01
FITSHOW_CONTROL_TARGET = 0x02
FITSHOW_CONTROL_STOP = 0x03
FITSHOW_CONTROL_PAUSE = 0x06

FITSHOW_INFO_SPEED = 0x02
FITSHOW_DATA_SPORT = 0x00

FITSHOW_STATUS_RUNNING = 3
FITSHOW_STATUS = {
    0: "idle",
    1: "stopped",  # Einheit beendet
    2: "starting",  # Countdown
    3: "running",
    4: "stopped",
    5: "error",
    6: "safety_key",
    7: "calibrating",
    10: "paused",
}

STATUS_OPTIONS = sorted({*FITSHOW_STATUS.values(), "unknown"})


def fitshow_frame(payload: bytes) -> bytes:
    """Payload in ein FitShow-Paket verpacken: 0x02 | Payload | XOR | 0x03."""
    xor = 0
    for b in payload:
        xor ^= b
    return bytes([FITSHOW_HEADER, *payload, xor, FITSHOW_FOOTER])


def fitshow_unframe(data: bytes) -> bytes | None:
    """Paket prüfen und das komplette Paket zurückgeben, sonst None."""
    if len(data) < 4 or data[0] != FITSHOW_HEADER or data[-1] != FITSHOW_FOOTER:
        return None
    xor = 0
    for b in data[1:-2]:
        xor ^= b
    return bytes(data) if xor == data[-2] else None


def fitshow_start_payload() -> bytes:
    """Start im normalen Modus (Sport-ID 0, keine Zielvorgabe)."""
    return bytes([FITSHOW_SYS_CONTROL, FITSHOW_CONTROL_START, 0, 0, 0, 0, 0, 0, 0, 0])


def fitshow_user_payload(weight_kg: float) -> bytes:
    """Nutzerdaten wie qdomyos-zwift (User-ID 0, 110, Alter 30, Gewicht)."""
    return bytes([FITSHOW_SYS_CONTROL, FITSHOW_CONTROL_USER, 0, 0, 110, 30, round(weight_kg) & 0xFF])


def fitshow_target_payload(speed_kmh: float, incline_raw: int) -> bytes:
    """Zielgeschwindigkeit (0,1 km/h) + Steigung (Rohwert, int8)."""
    return bytes(
        [FITSHOW_SYS_CONTROL, FITSHOW_CONTROL_TARGET, round(speed_kmh * 10) & 0xFF, incline_raw & 0xFF]
    )


def parse_fitshow_status(b: bytes) -> dict[str, Any]:
    """FitShow-Statuspaket (komplettes Paket inkl. Header) parsen."""
    par = b[2]
    result: dict[str, Any] = {"code": par, "status": FITSHOW_STATUS.get(par, "unknown")}
    # Laufdaten nur bei End/Running/Stop/Pause und vollständigem Paket
    if par in (1, 3, 4, 10) and len(b) >= 16:
        result.update(
            speed=b[3] / 10,
            incline_raw=struct.unpack_from("<b", b, 4)[0],
            elapsed_time=b[5] | b[6] << 8,
            steps=b[11] | b[12] << 8,
            heart_rate=b[13],
        )
    return result


def parse_fitshow_speed_range(b: bytes) -> tuple[float, float] | None:
    """Antwort auf Info/Speed → (min, max) in km/h."""
    if len(b) > 6 and b[3] > 0:
        return b[4] / 10, b[3] / 10
    return None


def parse_fitshow_sport_steps(b: bytes) -> int | None:
    """Antwort auf Data/Sport → Schrittzahl."""
    if len(b) > 12:
        return b[9] | b[10] << 8
    return None
