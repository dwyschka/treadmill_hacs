"""Treadmill (FTMS / FitShow) – Laufband per Bluetooth auslesen und steuern."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback

from .const import CONF_STRIDE_LENGTH, CONF_WEIGHT, DEFAULT_STRIDE_LENGTH, DEFAULT_WEIGHT
from .device import TreadmillDevice

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type TreadmillConfigEntry = ConfigEntry[TreadmillDevice]


async def async_setup_entry(hass: HomeAssistant, entry: TreadmillConfigEntry) -> bool:
    """Integration einrichten.

    Das Laufband ist meist ausgeschaltet – deshalb wird nicht beim Setup verbunden,
    sondern sobald es per Bluetooth sichtbar wird.
    """
    address: str = entry.data[CONF_ADDRESS]
    device = TreadmillDevice(
        hass,
        address,
        entry.title,
        stride_length=entry.options.get(CONF_STRIDE_LENGTH, DEFAULT_STRIDE_LENGTH),
        weight=entry.options.get(CONF_WEIGHT, DEFAULT_WEIGHT),
    )
    entry.runtime_data = device

    @callback
    def _async_seen(
        service_info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange
    ) -> None:
        device.set_ble_device(service_info.device)
        entry.async_create_background_task(
            hass, device.async_ensure_connected(), f"treadmill_ble connect {address}"
        )

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_seen,
            bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    # Schon sichtbar? Dann sofort verbinden.
    if ble_device := bluetooth.async_ble_device_from_address(hass, address, connectable=True):
        device.set_ble_device(ble_device)
        entry.async_create_background_task(
            hass, device.async_ensure_connected(force=True), f"treadmill_ble connect {address}"
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_options(hass: HomeAssistant, entry: TreadmillConfigEntry) -> None:
    device = entry.runtime_data
    device.stride_length = entry.options.get(CONF_STRIDE_LENGTH, DEFAULT_STRIDE_LENGTH)
    device.weight = entry.options.get(CONF_WEIGHT, DEFAULT_WEIGHT)


async def async_unload_entry(hass: HomeAssistant, entry: TreadmillConfigEntry) -> bool:
    """Integration entladen und Verbindung trennen."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_disconnect()
    return unloaded
