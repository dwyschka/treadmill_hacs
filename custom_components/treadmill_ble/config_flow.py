"""Config Flow: Laufband per Bluetooth-Discovery oder manuell aus der Liste wählen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_STRIDE_LENGTH,
    CONF_WEIGHT,
    DEFAULT_STRIDE_LENGTH,
    DEFAULT_WEIGHT,
    DOMAIN,
    FITSHOW_NAME_PREFIXES,
)
from .protocol import FITSHOW_SERVICES, FTMS_SERVICE


def is_supported(info: BluetoothServiceInfoBleak) -> bool:
    """Jedes Gerät mit FTMS oder FitShow (Service oder typischer Name)."""
    if FTMS_SERVICE in info.service_uuids or FTMS_SERVICE in info.service_data:
        return True
    if any(uuid in info.service_uuids for uuid in FITSHOW_SERVICES):
        return True
    return (info.name or "").upper().startswith(FITSHOW_NAME_PREFIXES)


REFRESH = "__refresh__"


def _title(info: BluetoothServiceInfoBleak) -> str:
    return info.name or info.address


class TreadmillConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow für Laufbänder."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not is_supported(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self.async_create_entry(
                title=_title(self._discovery), data={CONF_ADDRESS: self._discovery.address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": _title(self._discovery)},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None and user_input[CONF_ADDRESS] != REFRESH:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(self._discovered[address]), data={CONF_ADDRESS: address}
            )

        # Liste bei jedem Aufruf (auch über "Neu suchen") frisch aufbauen.
        # Erkannte Laufbänder zuerst, danach alle übrigen Geräte mit Namen – manche Walking Pads
        # zeigen FTMS/FitShow erst nach dem Verbinden. Auch nicht verbindbare Geräte werden
        # angezeigt (z. B. nur über einen passiven Proxy gesehen), damit man sie überhaupt findet.
        configured = self._async_current_ids(include_ignore=False)
        self._discovered.clear()
        supported: dict[str, str] = {}
        others: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, connectable=False):
            if info.address in configured:
                continue
            label = f"{_title(info)} ({info.address})"
            if async_ble_device_from_address(self.hass, info.address, connectable=True) is None:
                label += " – nicht verbindbar"
            if is_supported(info):
                supported[info.address] = label
            elif info.name and info.name != info.address.replace(":", "-"):
                others[info.address] = f"{label} – nicht erkannt"
            else:
                continue
            self._discovered[info.address] = info

        others = dict(sorted(others.items(), key=lambda item: item[1].lower()))
        options = {REFRESH: "↻ Neu suchen"} | supported | others
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS, default=next(iter(supported), REFRESH)): vol.In(options)}
            ),
            errors={} if self._discovered else {"base": "no_devices_found"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return TreadmillOptionsFlow()


class TreadmillOptionsFlow(OptionsFlow):
    """Schrittlänge (für die Schätzung) und Gewicht (FitShow-Nutzerprofil)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_STRIDE_LENGTH,
                        default=options.get(CONF_STRIDE_LENGTH, DEFAULT_STRIDE_LENGTH),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.3, max=1.5, step=0.01, unit_of_measurement="m",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_WEIGHT, default=options.get(CONF_WEIGHT, DEFAULT_WEIGHT)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=30, max=200, step=1, unit_of_measurement="kg",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
