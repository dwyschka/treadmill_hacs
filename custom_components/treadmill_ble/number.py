"""Zielgeschwindigkeit."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TreadmillConfigEntry
from .device import TreadmillDevice, TreadmillError
from .entity import TreadmillEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TreadmillConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TreadmillTargetSpeed(entry.runtime_data)])


class TreadmillTargetSpeed(TreadmillEntity, NumberEntity):
    """Zielgeschwindigkeit – der Bereich kommt (bei FitShow) vom Laufband."""

    _attr_device_class = NumberDeviceClass.SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, device: TreadmillDevice) -> None:
        super().__init__(device, "target_speed")

    @property
    def available(self) -> bool:
        return super().available and self._device.controller is not None

    @property
    def native_min_value(self) -> float:
        return self._device.speed_range[0]

    @property
    def native_max_value(self) -> float:
        return self._device.speed_range[1]

    @property
    def native_value(self) -> float | None:
        # Läuft das Band, zeigt das Feld die Ist-Geschwindigkeit, sonst den letzten Zielwert
        if self._device.running and (speed := self._device.data.get("speed")):
            return round(speed, 1)
        return self._device.data.get("target_speed")

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._device.async_set_speed(value)
        except TreadmillError as err:
            raise HomeAssistantError(str(err)) from err
