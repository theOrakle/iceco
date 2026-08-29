"""Iceco Refrigerator integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import CONF_DEVICE_ADDRESS, DOMAIN
from .coordinator import IcecoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_COMMAND = "send_command"
SEND_COMMAND_SCHEMA = vol.Schema(
    {vol.Required("command"): cv.string, vol.Optional("newline", default=True): cv.boolean}
)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Iceco from a config entry."""
    _LOGGER.debug("Setting up Iceco integration")

    # Get device address from config
    address = entry.data[CONF_DEVICE_ADDRESS]

    # Get BLE device from Home Assistant's bluetooth integration
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )

    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find Iceco refrigerator with address {address}"
        )

    # Create coordinator
    coordinator = IcecoDataUpdateCoordinator(hass, ble_device, entry)

    # Register cleanup before first refresh so it always runs on unload
    entry.async_on_unload(coordinator.async_shutdown)

    # Perform initial connection and data fetch; raises ConfigEntryNotReady on failure
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator on the entry (modern pattern — avoids hass.data globals)
    entry.runtime_data = coordinator

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _register_debug_service(hass)

    _LOGGER.info("Iceco integration setup complete")
    return True


def _register_debug_service(hass: HomeAssistant) -> None:
    """Register iceco.send_command — a debug tool for reverse-engineering the
    ECO / lock / battery-protection commands, which are unknown on the /S00/0L
    firmware. Sends a raw ASCII string to the fridge's write characteristic.

    Example: {"command": "/S01/1/002"}  (watch the status frames in the log)
    """
    if hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        return

    async def _handle_send_command(call: ServiceCall) -> None:
        text = call.data["command"]
        if call.data["newline"] and not text.endswith("\n"):
            text += "\n"
        payload = text.encode("ascii")
        sent = False
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                await coordinator.async_send_raw_command(payload)
                sent = True
        if not sent:
            raise ServiceValidationError("No connected Iceco fridge to send to")

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, _handle_send_command, schema=SEND_COMMAND_SCHEMA
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Iceco integration")
    # Coordinator shutdown is handled by the async_on_unload callback registered at setup
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Reloading Iceco integration due to options change")
    await hass.config_entries.async_reload(entry.entry_id)
