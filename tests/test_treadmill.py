"""Tests for custom_components/treadmill_ble using a simulated FitShow treadmill."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.treadmill_ble import protocol as p
from custom_components.treadmill_ble.const import DOMAIN
from custom_components.treadmill_ble.device import TreadmillDevice, TreadmillError

ADDRESS = "AA:BB:CC:DD:EE:FF"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


# --- Fakes -------------------------------------------------------------------


class Char:
    def __init__(self, uuid, props=("notify",)):
        self.uuid = uuid
        self.properties = list(props)


class Service:
    def __init__(self, uuid, chars):
        self.uuid = uuid
        self.chars = {c.uuid: c for c in chars}

    def get_characteristic(self, uuid):
        return self.chars.get(uuid)


class Services:
    def __init__(self, services):
        self.services = {s.uuid: s for s in services}

    def get_service(self, uuid):
        return self.services.get(uuid)

    def get_characteristic(self, uuid):
        for s in self.services.values():
            if c := s.get_characteristic(uuid):
                return c
        return None


def fs_frame(*payload):
    return bytearray(p.fitshow_frame(bytes(payload)))


class FakeFitShowClient:
    """FitShow treadmill that also sends FTMS data but refuses FTMS control."""

    def __init__(self):
        self.fs_write = Char(p.uuid16(0xFFF2), ("write-without-response",))
        self.fs_notify = Char(p.uuid16(0xFFF1))
        self.cp = Char(p.FTMS_CONTROL_POINT, ("write", "indicate"))
        self.services = Services([
            Service(p.FTMS_SERVICE, [Char(p.TREADMILL_DATA), Char(p.FTMS_STATUS), self.cp]),
            Service(p.uuid16(0xFFF0), [self.fs_write, self.fs_notify]),
        ])
        self.handlers = {}
        self.writes = []
        self.is_connected = True

    async def start_notify(self, ch, handler):
        self.handlers[ch.uuid] = (ch, handler)

    def emit(self, uuid, data):
        ch, handler = self.handlers[uuid]
        handler(ch, data)

    async def write_gatt_char(self, ch, data, response):
        data = bytes(data)
        self.writes.append(data)
        if ch is self.fs_write:
            assert response is False
            cmd, par = data[1], data[2]
            loop = asyncio.get_running_loop()
            if cmd == p.FITSHOW_SYS_CONTROL:  # echo as acknowledgement
                loop.call_soon(self.emit, self.fs_notify.uuid, fs_frame(cmd, par))
            elif cmd == p.FITSHOW_SYS_INFO and par == p.FITSHOW_INFO_SPEED:
                loop.call_soon(self.emit, self.fs_notify.uuid, fs_frame(0x50, 0x02, 60, 10, 0))

    async def disconnect(self):
        self.is_connected = False


async def connect_fake(hass, device, client):
    async def fake_establish(*args, **kwargs):
        return client

    device.set_ble_device(SimpleNamespace(address=ADDRESS, name="TF-123456"))
    with patch("custom_components.treadmill_ble.device.establish_connection", fake_establish):
        await device.async_ensure_connected(force=True)
    await asyncio.sleep(0.01)


# --- Protocol ------------------------------------------------------------------


def test_treadmill_data():
    # distance + incline + energy + time, speed 8.10 km/h
    data = bytes([0x8C, 0x04, 0x2A, 0x03, 0xE8, 0x03, 0x00, 0x0F, 0x00, 0x00, 0x00,
                  0x2D, 0x00, 0xFF, 0xFF, 0xFF, 0x3C, 0x00])
    assert p.parse_treadmill_data(data) == {
        "speed": 8.1, "distance": 1000, "incline": 1.5, "energy": 45, "elapsed_time": 60,
    }


def test_fitshow_frame_matches_qz():
    assert p.fitshow_frame(bytes([0x53, 0x03])).hex(" ") == "02 53 03 50 03"
    assert p.fitshow_target_payload(3.5, 2).hex(" ") == "53 02 23 02"
    assert p.fitshow_unframe(bytes([2, 0x51, 3, 0xFF, 3])) is None


def test_fitshow_status():
    b = p.fitshow_unframe(bytes(fs_frame(0x51, 3, 35, 0xFE, 125, 0, 12, 0, 9, 0, 0xD2, 0x04, 99, 0)))
    st = p.parse_fitshow_status(b)
    assert st["status"] == "running" and st["speed"] == 3.5 and st["incline_raw"] == -2
    assert st["steps"] == 1234 and st["heart_rate"] == 99 and st["elapsed_time"] == 125


# --- Device logic --------------------------------------------------------------


async def test_device_fitshow(hass: HomeAssistant):
    device = TreadmillDevice(hass, ADDRESS, "TF-123456", stride_length=0.7, weight=80)
    client = FakeFitShowClient()
    await connect_fake(hass, device, client)

    assert device.connected and device.controller == "fitshow"
    assert device.speed_range == (1.0, 6.0)
    assert p.fitshow_frame(p.fitshow_user_payload(80)) in client.writes

    # speed before start → error
    with pytest.raises(TreadmillError) as exc:
        await device.async_set_speed(3)
    assert exc.value.translation_key == "not_running"

    await device.async_start()
    assert p.fitshow_frame(p.fitshow_start_payload()) in client.writes

    # FTMS data (distance 700 m) → estimated steps
    client.emit(p.TREADMILL_DATA, bytearray([0x04, 0x00, 0x5E, 0x01, 0xBC, 0x02, 0x00]))
    assert device.data["speed"] == 3.5 and device.data["distance"] == 700
    assert device.data["steps"] == 1000 and device.data["steps_source"] == "estimated"

    # FitShow status: running, incline 2, 1234 steps → real steps take precedence
    client.emit(client.fs_notify.uuid, fs_frame(0x51, 3, 35, 2, 125, 0, 12, 0, 9, 0, 0xD2, 0x04, 0, 0))
    assert device.running and device.data["status"] == "running"
    assert device.data["steps"] == 1234 and device.data["steps_source"] == "treadmill"
    client.emit(p.TREADMILL_DATA, bytearray([0x04, 0x00, 0x5E, 0x01, 0xBC, 0x02, 0x00]))
    assert device.data["steps"] == 1234

    # speed is clamped (max 6.0) and the incline is sent along
    await device.async_set_speed(9)
    assert p.fitshow_frame(bytes([0x53, 0x02, 60, 2])) in client.writes
    assert device.data["target_speed"] == 6.0

    await device.async_pause()
    await device.async_stop()
    assert p.fitshow_frame(bytes([0x53, 0x06])) in client.writes
    assert p.fitshow_frame(bytes([0x53, 0x03])) in client.writes
    # no FTMS control point commands, FitShow takes precedence
    assert not any(w[:1] in (b"\x00", b"\x07", b"\x08") and len(w) <= 3 for w in client.writes)

    # status polling is running
    client.writes.clear()
    await asyncio.sleep(1.1)
    assert p.fitshow_frame(bytes([0x51])) in client.writes

    await device.async_disconnect()
    assert not device.connected and not device.enabled


async def test_device_command_timeout(hass: HomeAssistant):
    device = TreadmillDevice(hass, ADDRESS, "TF-1", stride_length=0.7, weight=75)
    client = FakeFitShowClient()
    await connect_fake(hass, device, client)

    async def silent(ch, data, response):
        client.writes.append(bytes(data))

    client.write_gatt_char = silent
    with patch("custom_components.treadmill_ble.device.COMMAND_TIMEOUT", 0.05):
        with pytest.raises(TreadmillError) as exc:
            await device.async_stop()
    assert exc.value.translation_key == "no_acknowledgement"
    await device.async_disconnect()


async def test_not_connected(hass: HomeAssistant):
    device = TreadmillDevice(hass, ADDRESS, "TF-1", stride_length=0.7, weight=75)
    with pytest.raises(TreadmillError) as exc:
        await device.async_start()
    assert exc.value.translation_key == "not_connected"


# --- Config Flow + Setup ------------------------------------------------------


def service_info(name="TF-123456", uuids=(p.FTMS_SERVICE,), service_data=None):
    return SimpleNamespace(
        name=name,
        address=ADDRESS,
        service_uuids=list(uuids),
        service_data=service_data or {},
        device=SimpleNamespace(address=ADDRESS, name=name),
    )


async def test_flow_bluetooth(hass: HomeAssistant):
    with patch("custom_components.treadmill_ble.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TF-123456"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}


async def test_flow_bluetooth_any_ftms(hass: HomeAssistant):
    """Every FTMS device is offered – even with a different machine type."""
    info = service_info(name="WalkPad", service_data={p.FTMS_SERVICE: bytes([1, 0x20, 0])})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bluetooth_confirm"


async def test_flow_bluetooth_rejects_unrelated(hass: HomeAssistant):
    info = service_info(name="Headphones", uuids=())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


async def test_flow_user(hass: HomeAssistant):
    with (
        patch(
            "custom_components.treadmill_ble.config_flow.async_discovered_service_info",
            return_value=[service_info(uuids=())],
        ),
        patch("custom_components.treadmill_ble.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_user_lists_unknown_devices(hass: HomeAssistant):
    """Unrecognized named devices can be picked, unnamed ones cannot."""
    unknown = service_info(name="WalkPad X", uuids=())
    unknown.address = "11:22:33:44:55:66"
    nameless = service_info(name="11-22-33-44-55-77", uuids=())
    nameless.address = "11:22:33:44:55:77"
    with (
        patch(
            "custom_components.treadmill_ble.config_flow.async_discovered_service_info",
            return_value=[unknown, nameless, service_info(name="TF04-ABCD", uuids=())],
        ),
        patch("custom_components.treadmill_ble.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        options = list(result["data_schema"].schema["address"].container)
        assert options == ["__refresh__", ADDRESS, "11:22:33:44:55:66"]  # recognized treadmill first
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: "11:22:33:44:55:66"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WalkPad X"


async def test_flow_user_none_then_refresh(hass: HomeAssistant):
    """Empty list → hint; "search again" reloads and finds the device that appeared meanwhile."""
    found: list = []
    with (
        patch(
            "custom_components.treadmill_ble.config_flow.async_discovered_service_info",
            side_effect=lambda *a, **k: list(found),
        ),
        patch("custom_components.treadmill_ble.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "no_devices_found"}

        found.append(service_info(uuids=()))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: "__refresh__"}
        )
        assert result["errors"] == {}
        assert ADDRESS in result["data_schema"].schema["address"].container
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_user_marks_not_connectable(hass: HomeAssistant):
    """Devices seen only passively are still listed, but marked."""
    with (
        patch(
            "custom_components.treadmill_ble.config_flow.async_discovered_service_info",
            return_value=[service_info(uuids=())],
        ) as discovered,
        patch(
            "custom_components.treadmill_ble.config_flow.async_ble_device_from_address",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert discovered.call_args.kwargs["connectable"] is False
    assert "not connectable" in result["data_schema"].schema["address"].container[ADDRESS]


async def test_options_flow(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)
    with patch("custom_components.treadmill_ble.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"stride_length": 0.8, "weight": 90}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"stride_length": 0.8, "weight": 90}


async def test_setup_entities(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}, title="TF-123456"
    )
    entry.add_to_hass(hass)
    client = FakeFitShowClient()

    async def fake_establish(*args, **kwargs):
        return client

    with (
        patch("custom_components.treadmill_ble.bluetooth.async_register_callback", return_value=lambda: None),
        patch(
            "custom_components.treadmill_ble.bluetooth.async_ble_device_from_address",
            return_value=SimpleNamespace(address=ADDRESS, name="TF-123456"),
        ),
        patch("custom_components.treadmill_ble.device.establish_connection", fake_establish),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=False)
        await asyncio.sleep(0.05)

    client.emit(client.fs_notify.uuid, fs_frame(0x51, 3, 35, 0, 125, 0, 12, 0, 9, 0, 0xD2, 0x04, 0, 0))
    await hass.async_block_till_done(wait_background_tasks=False)

    states = {s.entity_id: s for s in hass.states.async_all()}
    print(sorted(states))
    assert states["sensor.tf_123456_steps"].state == "1234"
    assert states["sensor.tf_123456_steps"].attributes["source"] == "treadmill"
    assert states["sensor.tf_123456_status"].state == "running"
    assert states["button.tf_123456_stop"].state != "unavailable"
    assert states["number.tf_123456_target_speed"].attributes["max"] == 6.0

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.tf_123456_target_speed", "value": 4.2}, blocking=True
    )
    assert p.fitshow_frame(bytes([0x53, 0x02, 42, 0])) in client.writes

    await hass.services.async_call("button", "press", {"entity_id": "button.tf_123456_stop"}, blocking=True)
    assert p.fitshow_frame(bytes([0x53, 0x03])) in client.writes

    # not running anymore → translated error from the number entity
    client.emit(client.fs_notify.uuid, fs_frame(0x51, 4, 0, 0, 125, 0, 12, 0, 9, 0, 0xD2, 0x04, 0, 0))
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": "number.tf_123456_target_speed", "value": 3}, blocking=True
        )
    assert exc.value.translation_key == "not_running"
    assert str(exc.value) == "The treadmill is not running. Start it before changing the speed"
    assert p.fitshow_frame(bytes([0x53, 0x03])) in client.writes

    # release the connection → entities unavailable, switch stays usable
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.tf_123456_bluetooth_connection"}, blocking=True
    )
    assert hass.states.get("sensor.tf_123456_steps").state == "unavailable"
    assert hass.states.get("switch.tf_123456_bluetooth_connection").state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
