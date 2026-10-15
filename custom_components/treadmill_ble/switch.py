"""Switch to release the Bluetooth connection (e.g. for the vendor app)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TreadmillConfigEntry
from .device import TreadmillDevice
from .entity import TreadmillEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TreadmillConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TreadmillConnectionSwitch(entry.runtime_data)])


class TreadmillConnectionSwitch(TreadmillEntity, SwitchEntity):
    """On = Home Assistant connects automatically, off = connection free for other apps."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device: TreadmillDevice) -> None:
        super().__init__(device, "connection")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._device.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"connected": self._device.connected, "controller": self._device.controller}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.async_enable()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.async_disconnect()
