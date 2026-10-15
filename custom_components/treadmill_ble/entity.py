"""Basis-Entität für das Laufband."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .device import TreadmillDevice


class TreadmillEntity(Entity):
    """Entität, die bei jeder Zustandsänderung des Laufbands aktualisiert wird."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: TreadmillDevice, key: str) -> None:
        self._device = device
        self._attr_translation_key = key
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, device.address)},
            name=device.name,
        )

    @property
    def available(self) -> bool:
        return self._device.connected

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._device.add_listener(self.async_write_ha_state))
