"""Switch platform for Iceco refrigerator."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ADDRESS,
    ENTITY_CONNECTION,
    ENTITY_POWER_SWITCH,
)
from .coordinator import IcecoDataUpdateCoordinator
from .entity import IcecoEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Iceco switch entities from a config entry.

    ECO/MAX and the panel lock are read-only on the /S00/0L firmware (the write
    commands are unknown), so they are exposed as a sensor / binary_sensor rather
    than switches that would always fail on toggle.
    """
    coordinator: IcecoDataUpdateCoordinator = entry.runtime_data

    async_add_entities(
        [
            IcecoPowerSwitch(coordinator, entry),
            IcecoConnectionSwitch(coordinator, entry),
        ]
    )


class IcecoPowerSwitch(IcecoEntity, SwitchEntity):
    """Fridge display + compressor power."""

    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)

        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{ENTITY_POWER_SWITCH}"
        self._attr_name = "Power"

    @property
    def is_on(self) -> bool | None:
        """Return True if the fridge is on.

        Set optimistically when we send a power command, corrected to True by any
        status frame (the fridge only streams while on), and back to False by the
        coordinator's health check if frames stop for >2 min while connected.
        """
        return self.coordinator.data.power_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power the fridge on (compressor starts after a short delay)."""
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power the fridge off."""
        await self.coordinator.async_set_power(False)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.connection_state == "connected"
        )


class IcecoConnectionSwitch(IcecoEntity, SwitchEntity):
    """HA's BLE link to the fridge — turn off to let the Iceco app connect."""

    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)

        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{ENTITY_CONNECTION}"
        self._attr_name = "BLE Connection"

    @property
    def is_on(self) -> bool:
        """Return True if connected."""
        return self.coordinator.data.connection_state == "connected"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Connect to refrigerator."""
        if self.coordinator.data.connection_state != "connected":
            await self.coordinator.async_manual_reconnect()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disconnect from refrigerator (allows mobile app access)."""
        if self.coordinator.data.connection_state == "connected":
            await self.coordinator.async_manual_disconnect()

    @property
    def available(self) -> bool:
        """Always available so the connection can be re-established."""
        return True
