"""Verbindung und Protokoll-Logik für ein Laufband (FTMS + FitShow)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.core import HomeAssistant

from .const import (
    COMMAND_TIMEOUT,
    DEFAULT_SPEED_RANGE,
    FITSHOW_POLL_INTERVAL,
    RECONNECT_INTERVAL,
    STEPS_SOURCE_ESTIMATED,
    STEPS_SOURCE_SENSOR,
    STEPS_SOURCE_TREADMILL,
)
from .protocol import (
    FITSHOW_DATA_SPORT,
    FITSHOW_INFO_SPEED,
    FITSHOW_STATUS_RUNNING,
    FITSHOW_SYS_CONTROL,
    FITSHOW_SYS_DATA,
    FITSHOW_SYS_INFO,
    FITSHOW_SYS_STATUS,
    FITSHOW_CONTROL_PAUSE,
    FITSHOW_CONTROL_STOP,
    FITSHOW_VARIANTS,
    FTMS_CONTROL_POINT,
    FTMS_OP_REQUEST_CONTROL,
    FTMS_OP_RESPONSE,
    FTMS_OP_SET_TARGET_SPEED,
    FTMS_OP_START_RESUME,
    FTMS_OP_STOP_PAUSE,
    FTMS_RESULT_CONTROL_NOT_PERMITTED,
    FTMS_RESULT_SUCCESS,
    FTMS_RESULT_TEXT,
    FTMS_SERVICE,
    FTMS_STATUS,
    HR_MEASUREMENT,
    RSC_MEASUREMENT,
    TREADMILL_DATA,
    fitshow_frame,
    fitshow_start_payload,
    fitshow_target_payload,
    fitshow_unframe,
    fitshow_user_payload,
    parse_fitshow_speed_range,
    parse_fitshow_sport_steps,
    parse_fitshow_status,
    parse_ftms_status,
    parse_heart_rate,
    parse_rsc_cadence,
    parse_treadmill_data,
)

_LOGGER = logging.getLogger(__name__)

CONTROLLER_FITSHOW = "fitshow"
CONTROLLER_FTMS = "ftms"


class TreadmillError(Exception):
    """Befehl konnte nicht ausgeführt werden."""


class TreadmillDevice:
    """Hält die BLE-Verbindung zum Laufband und den aktuellen Zustand."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        stride_length: float,
        weight: float,
    ) -> None:
        self._hass = hass
        self.address = address
        self.name = name
        self.stride_length = stride_length
        self.weight = weight

        self._ble_device: BLEDevice | None = None
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()  # keine parallelen GATT-Operationen
        self._command_lock = asyncio.Lock()  # Befehle nacheinander, jeweils bis zur Antwort
        self._last_attempt = 0.0
        self._listeners: set[Callable[[], None]] = set()
        self._poll_task: asyncio.Task | None = None

        self.enabled = True
        self.controller: str | None = None
        self.speed_range: tuple[float, float] = DEFAULT_SPEED_RANGE
        self.running = False
        self.data: dict[str, Any] = {}

        # FitShow
        self._fs_write: BleakGATTCharacteristic | None = None
        self._fs_write_response = False
        self._fs_pending: dict[tuple[int, int], asyncio.Future[bytes]] = {}
        self._fs_incline_raw = 0

        # FTMS
        self._has_ftms_data = False
        self._ftms_has_control = False
        self._ftms_cp: BleakGATTCharacteristic | None = None
        self._cp_pending: tuple[int, asyncio.Future[int]] | None = None

        # Schritte aus Schrittfrequenz (RSC)
        self._rsc_steps = 0.0
        self._rsc_last: float | None = None

    # --- Zustand / Listener ------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self._ble_device = ble_device

    # --- Verbindung --------------------------------------------------------------

    async def async_ensure_connected(self, force: bool = False) -> None:
        """Verbindet, falls nötig. Wird bei jedem Advertising aufgerufen – daher gedrosselt."""
        if not self.enabled or self.connected or self._ble_device is None:
            return
        if self._connect_lock.locked():
            return
        if not force and time.monotonic() - self._last_attempt < RECONNECT_INTERVAL:
            return

        async with self._connect_lock:
            self._last_attempt = time.monotonic()
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._ble_device,
                    self.name,
                    disconnected_callback=self._on_disconnected,
                    ble_device_callback=lambda: self._ble_device,
                )
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("%s: Verbindung fehlgeschlagen: %s", self.name, err)
                return

            self._client = client
            try:
                await self._async_setup(client)
            except (BleakError, TimeoutError) as err:
                _LOGGER.warning("%s: Einrichtung fehlgeschlagen: %s", self.name, err)
                await self._async_drop_client()
                return

            _LOGGER.info("%s: verbunden (Steuerung: %s)", self.name, self.controller or "keine")
            self._notify()

    async def _async_setup(self, client: BleakClient) -> None:
        services = client.services
        self._has_ftms_data = False
        self._ftms_has_control = False
        self.controller = None

        if (ftms := services.get_service(FTMS_SERVICE)) is not None:
            await self._async_try_notify(client, ftms.get_characteristic(TREADMILL_DATA), self._on_treadmill_data)
            await self._async_try_notify(client, ftms.get_characteristic(FTMS_STATUS), self._on_ftms_status)
            cp = ftms.get_characteristic(FTMS_CONTROL_POINT)
            if await self._async_try_notify(client, cp, self._on_control_point):  # Indications
                self._ftms_cp = cp
                self.controller = CONTROLLER_FTMS

        await self._async_try_notify(client, services.get_characteristic(HR_MEASUREMENT), self._on_heart_rate)
        await self._async_try_notify(client, services.get_characteristic(RSC_MEASUREMENT), self._on_rsc)

        # FitShow hat Vorrang: diese Geräte verweigern die Steuerung per FTMS meist
        for svc_uuid, write_uuid, notify_uuid in FITSHOW_VARIANTS:
            svc = services.get_service(svc_uuid)
            if svc is None:
                continue
            write_ch = svc.get_characteristic(write_uuid)
            notify_ch = svc.get_characteristic(notify_uuid)
            if write_ch is None or notify_ch is None:
                continue
            self._fs_write = write_ch
            self._fs_write_response = "write-without-response" not in write_ch.properties
            await client.start_notify(notify_ch, self._on_fitshow)
            self.controller = CONTROLLER_FITSHOW
            # Init-Sequenz wie qdomyos-zwift: Nutzerdaten + Geschwindigkeitsbereich abfragen
            await self._async_fs_write(fitshow_user_payload(self.weight))
            await self._async_fs_write(bytes([FITSHOW_SYS_INFO, FITSHOW_INFO_SPEED]))
            self._poll_task = self._hass.async_create_background_task(
                self._async_fitshow_poll(), f"treadmill_ble poll {self.address}"
            )
            break

    async def _async_try_notify(
        self,
        client: BleakClient,
        ch: BleakGATTCharacteristic | None,
        handler: Callable[[BleakGATTCharacteristic, bytearray], None],
    ) -> bool:
        """Optionale Characteristic abonnieren – Fehler nur loggen."""
        if ch is None:
            return False
        try:
            await client.start_notify(ch, handler)
        except BleakError as err:
            _LOGGER.debug("%s: %s nicht abonnierbar: %s", self.name, ch.uuid, err)
            return False
        return True

    async def _async_fitshow_poll(self) -> None:
        """FitShow schickt den Status nur auf Anfrage."""
        status = bytes([FITSHOW_SYS_STATUS])
        while self.connected:
            if not self._command_lock.locked():
                try:
                    await self._async_fs_write(status)
                except (BleakError, TimeoutError) as err:
                    _LOGGER.debug("%s: Status-Abfrage fehlgeschlagen: %s", self.name, err)
            await asyncio.sleep(FITSHOW_POLL_INTERVAL)

    def _on_disconnected(self, _client: BleakClient) -> None:
        _LOGGER.debug("%s: Verbindung getrennt", self.name)
        self._reset_connection_state()
        self._notify()

    def _reset_connection_state(self) -> None:
        self._client = None
        self.controller = None
        self.running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        for fut in self._fs_pending.values():
            if not fut.done():
                fut.set_exception(TreadmillError("Verbindung getrennt"))
        self._fs_pending.clear()
        if self._cp_pending and not self._cp_pending[1].done():
            self._cp_pending[1].set_exception(TreadmillError("Verbindung getrennt"))
        self._cp_pending = None
        self._rsc_last = None

    async def _async_drop_client(self) -> None:
        client = self._client
        self._reset_connection_state()
        if client is not None:
            try:
                await client.disconnect()
            except BleakError:
                pass

    async def async_disconnect(self) -> None:
        """Verbindung trennen und nicht automatisch neu verbinden."""
        self.enabled = False
        await self._async_drop_client()
        self._notify()

    async def async_enable(self) -> None:
        self.enabled = True
        self._notify()
        await self.async_ensure_connected(force=True)

    # --- Befehle -----------------------------------------------------------------

    async def async_start(self) -> None:
        if self.controller == CONTROLLER_FITSHOW:
            await self._async_fs_command(fitshow_start_payload())
        else:
            await self._async_ftms_command(bytes([FTMS_OP_START_RESUME]))

    async def async_stop(self) -> None:
        if self.controller == CONTROLLER_FITSHOW:
            await self._async_fs_command(bytes([FITSHOW_SYS_CONTROL, FITSHOW_CONTROL_STOP]))
        else:
            await self._async_ftms_command(bytes([FTMS_OP_STOP_PAUSE, 0x01]))

    async def async_pause(self) -> None:
        if self.controller == CONTROLLER_FITSHOW:
            await self._async_fs_command(bytes([FITSHOW_SYS_CONTROL, FITSHOW_CONTROL_PAUSE]))
        else:
            await self._async_ftms_command(bytes([FTMS_OP_STOP_PAUSE, 0x02]))

    async def async_set_speed(self, kmh: float) -> None:
        self._require_connection()
        low, high = self.speed_range
        kmh = round(min(high, max(low, kmh)), 1)
        if self.controller == CONTROLLER_FITSHOW:
            # FitShow ignoriert Zielwerte, solange das Band nicht läuft (z. B. im Countdown)
            if not self.running:
                raise TreadmillError("Laufband läuft nicht")
            await self._async_fs_command(fitshow_target_payload(kmh, self._fs_incline_raw))
        else:
            value = round(kmh * 100)
            await self._async_ftms_command(bytes([FTMS_OP_SET_TARGET_SPEED, value & 0xFF, value >> 8]))
        self.data["target_speed"] = kmh
        self._notify()

    def _require_connection(self) -> None:
        if not self.connected or self.controller is None:
            raise TreadmillError("Laufband nicht verbunden oder nicht steuerbar")

    # FitShow

    async def _async_fs_write(self, payload: bytes) -> None:
        assert self._client is not None and self._fs_write is not None
        async with self._write_lock:
            await self._client.write_gatt_char(
                self._fs_write, fitshow_frame(payload), response=self._fs_write_response
            )

    async def _async_fs_command(self, payload: bytes) -> None:
        """Befehl senden und auf das Echo (cmd/par) als Bestätigung warten."""
        self._require_connection()
        async with self._command_lock:
            key = (payload[0], payload[1])
            fut: asyncio.Future[bytes] = self._hass.loop.create_future()
            self._fs_pending[key] = fut
            try:
                await self._async_fs_write(payload)
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    await fut
            except TimeoutError as err:
                raise TreadmillError("Keine Bestätigung vom Laufband") from err
            except BleakError as err:
                raise TreadmillError(f"Bluetooth-Fehler: {err}") from err
            finally:
                self._fs_pending.pop(key, None)

    # FTMS

    async def _async_ftms_send(self, payload: bytes) -> int:
        assert self._client is not None and self._ftms_cp is not None
        fut: asyncio.Future[int] = self._hass.loop.create_future()
        self._cp_pending = (payload[0], fut)
        try:
            async with self._write_lock:
                await self._client.write_gatt_char(self._ftms_cp, payload, response=True)
            async with asyncio.timeout(COMMAND_TIMEOUT):
                return await fut
        except TimeoutError as err:
            raise TreadmillError("Keine Antwort vom Laufband") from err
        except BleakError as err:
            raise TreadmillError(f"Bluetooth-Fehler: {err}") from err
        finally:
            self._cp_pending = None

    async def _async_ftms_command(self, payload: bytes) -> None:
        self._require_connection()
        async with self._command_lock:
            if not self._ftms_has_control:
                await self._async_ftms_request_control()
            result = await self._async_ftms_send(payload)
            if result == FTMS_RESULT_CONTROL_NOT_PERMITTED and self._ftms_has_control:
                self._ftms_has_control = False
                await self._async_ftms_request_control()
                result = await self._async_ftms_send(payload)
            if result != FTMS_RESULT_SUCCESS:
                raise TreadmillError(f"FTMS: {FTMS_RESULT_TEXT.get(result, hex(result))}")

    async def _async_ftms_request_control(self) -> None:
        # Manche Geräte lehnen Request Control ab, führen Befehle aber trotzdem aus
        result = await self._async_ftms_send(bytes([FTMS_OP_REQUEST_CONTROL]))
        self._ftms_has_control = result == FTMS_RESULT_SUCCESS
        if not self._ftms_has_control:
            _LOGGER.debug("%s: Request Control abgelehnt (%s)", self.name, result)

    # --- Notifications -----------------------------------------------------------

    def _on_treadmill_data(self, _ch: BleakGATTCharacteristic, data: bytearray) -> None:
        try:
            parsed = parse_treadmill_data(bytes(data))
        except (IndexError, ValueError):
            _LOGGER.debug("%s: ungültiges Treadmill-Data-Paket: %s", self.name, data.hex())
            return
        self._has_ftms_data = True
        self.data.update(parsed)
        self._update_estimated_steps()
        self._notify()

    def _on_ftms_status(self, _ch: BleakGATTCharacteristic, data: bytearray) -> None:
        if not data or self.controller == CONTROLLER_FITSHOW:
            return  # FitShow liefert einen genaueren Status
        status, running = parse_ftms_status(bytes(data))
        if status is not None:
            self.data["status"] = status
            self.running = bool(running)
            self._notify()

    def _on_control_point(self, _ch: BleakGATTCharacteristic, data: bytearray) -> None:
        if len(data) < 3 or data[0] != FTMS_OP_RESPONSE or self._cp_pending is None:
            return
        op, fut = self._cp_pending
        if data[1] == op and not fut.done():
            fut.set_result(data[2])

    def _on_heart_rate(self, _ch: BleakGATTCharacteristic, data: bytearray) -> None:
        if len(data) >= 2:
            self.data["heart_rate"] = parse_heart_rate(bytes(data))
            self._notify()

    def _on_rsc(self, _ch: BleakGATTCharacteristic, data: bytearray) -> None:
        if len(data) < 4:
            return
        cadence = parse_rsc_cadence(bytes(data))
        now = time.monotonic()
        self.data["cadence"] = cadence
        if self.data.get("steps_source") != STEPS_SOURCE_TREADMILL:
            if self._rsc_last is not None:
                # Lücken begrenzen, damit Verbindungsabbrüche nicht als Schritte zählen
                self._rsc_steps += cadence * min(now - self._rsc_last, 5.0) / 60
            self.data["steps"] = round(self._rsc_steps)
            self.data["steps_source"] = STEPS_SOURCE_SENSOR
        self._rsc_last = now
        self._notify()

    def _on_fitshow(self, _ch: BleakGATTCharacteristic, data: bytearray) -> None:
        b = fitshow_unframe(bytes(data))
        if b is None:
            return
        cmd, par = b[1], b[2]

        if (fut := self._fs_pending.get((cmd, par))) is not None and not fut.done():
            fut.set_result(b)

        if cmd == FITSHOW_SYS_INFO and par == FITSHOW_INFO_SPEED:
            if speed_range := parse_fitshow_speed_range(b):
                self.speed_range = speed_range
                _LOGGER.debug("%s: Geschwindigkeitsbereich %s–%s km/h", self.name, *speed_range)

        elif cmd == FITSHOW_SYS_STATUS:
            st = parse_fitshow_status(b)
            self.running = par == FITSHOW_STATUS_RUNNING
            self.data["status"] = st["status"]
            if "steps" in st:
                self._fs_incline_raw = st["incline_raw"]
                if st["steps"] > 0:
                    self.data["steps"] = st["steps"]
                    self.data["steps_source"] = STEPS_SOURCE_TREADMILL
                if not self._has_ftms_data:
                    # Ohne FTMS die FitShow-Werte verwenden
                    self.data["speed"] = st["speed"] if self.running else 0.0
                    self.data["incline"] = float(st["incline_raw"])
                    self.data["elapsed_time"] = st["elapsed_time"]
                    if st["heart_rate"]:
                        self.data["heart_rate"] = st["heart_rate"]
            elif not self._has_ftms_data:
                self.data["speed"] = 0.0

        elif cmd == FITSHOW_SYS_DATA and par == FITSHOW_DATA_SPORT:
            if (steps := parse_fitshow_sport_steps(b)) is not None and steps > 0:
                self.data["steps"] = steps
                self.data["steps_source"] = STEPS_SOURCE_TREADMILL

        self._notify()

    def _update_estimated_steps(self) -> None:
        """Schritte aus Distanz ÷ Schrittlänge, wenn keine echte Quelle vorhanden ist."""
        if self.data.get("steps_source") in (STEPS_SOURCE_TREADMILL, STEPS_SOURCE_SENSOR):
            return
        distance = self.data.get("distance")
        if distance is None or self.stride_length <= 0:
            return
        self.data["steps"] = round(distance / self.stride_length)
        self.data["steps_source"] = STEPS_SOURCE_ESTIMATED
