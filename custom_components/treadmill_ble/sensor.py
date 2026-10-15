"""Sensors: speed, distance, time, steps, status …"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfSpeed, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TreadmillConfigEntry
from .entity import TreadmillEntity
from .protocol import STATUS_OPTIONS


@dataclass(frozen=True, kw_only=True)
class TreadmillSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _key(name: str) -> Callable[[dict[str, Any]], Any]:
    return lambda data: data.get(name)


SENSORS: tuple[TreadmillSensorDescription, ...] = (
    TreadmillSensorDescription(
        key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_key("speed"),
    ),
    TreadmillSensorDescription(
        key="avg_speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=_key("avg_speed"),
    ),
    TreadmillSensorDescription(
        key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_key("distance"),
    ),
    TreadmillSensorDescription(
        key="elapsed_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_key("elapsed_time"),
    ),
    TreadmillSensorDescription(
        key="incline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_key("incline"),
    ),
    TreadmillSensorDescription(
        key="energy",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_key("energy"),
    ),
    TreadmillSensorDescription(
        key="heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("heart_rate") or None,
    ),
    TreadmillSensorDescription(
        key="steps",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_key("steps"),
        attrs_fn=lambda d: {"source": d.get("steps_source")},
    ),
    TreadmillSensorDescription(
        key="cadence",
        native_unit_of_measurement="steps/min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_key("cadence"),
    ),
    TreadmillSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=_key("status"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TreadmillConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(TreadmillSensor(entry.runtime_data, d) for d in SENSORS)


class TreadmillSensor(TreadmillEntity, SensorEntity):
    entity_description: TreadmillSensorDescription

    def __init__(self, device, description: TreadmillSensorDescription) -> None:
        super().__init__(device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._device.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self._device.data)
