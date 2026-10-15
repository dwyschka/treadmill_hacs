"""Buttons: start, pause, stop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TreadmillConfigEntry
from .const import DOMAIN
from .device import TreadmillDevice, TreadmillError
from .entity import TreadmillEntity


@dataclass(frozen=True, kw_only=True)
class TreadmillButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[TreadmillDevice], Awaitable[None]]


BUTTONS = (
    TreadmillButtonDescription(key="start", press_fn=lambda d: d.async_start()),
    TreadmillButtonDescription(key="pause", press_fn=lambda d: d.async_pause()),
    TreadmillButtonDescription(key="stop", press_fn=lambda d: d.async_stop()),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TreadmillConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(TreadmillButton(entry.runtime_data, d) for d in BUTTONS)


class TreadmillButton(TreadmillEntity, ButtonEntity):
    entity_description: TreadmillButtonDescription

    def __init__(self, device: TreadmillDevice, description: TreadmillButtonDescription) -> None:
        super().__init__(device, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self._device.controller is not None

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self._device)
        except TreadmillError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.placeholders,
            ) from err
