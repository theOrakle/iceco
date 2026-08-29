"""Select platform for Iceco refrigerator — mode, battery protection, unit."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BATTERY_PROTECTION_OPTIONS,
    CONF_DEVICE_ADDRESS,
    DISPLAY_UNIT_OPTIONS,
    ENTITY_BATTERY_PROTECTION,
    ENTITY_DISPLAY_UNIT,
    ENTITY_ECO_MODE,
    MODE_OPTIONS,
)
from .coordinator import IcecoDataUpdateCoordinator
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Iceco select entities from a config entry."""
    coordinator: IcecoDataUpdateCoordinator = entry.runtime_data

    async_add_entities(
        [
            IcecoModeSelect(coordinator, entry),
            IcecoBatteryProtectionSelect(coordinator, entry),
            IcecoDisplayUnitSelect(coordinator, entry),
        ]
    )


class _IcecoSelect(CoordinatorEntity[IcecoDataUpdateCoordinator], SelectEntity):
    """Base for the Iceco selects — all config-category, connected-only."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{suffix}"
        self._attr_device_info = build_device_info(entry.data[CONF_DEVICE_ADDRESS])

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.connection_state == "connected"
        )


class IcecoModeSelect(_IcecoSelect):
    """Compressor mode — ECO or MAX (command S06)."""

    _attr_name = "Mode"
    _attr_icon = "mdi:snowflake-variant"
    _attr_options = list(MODE_OPTIONS)

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, ENTITY_ECO_MODE)

    @property
    def current_option(self) -> str | None:
        eco = self.coordinator.data.eco_mode
        if eco is None:
            return None
        return "ECO" if eco else "MAX"

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_eco_mode(option == "ECO")


class IcecoBatteryProtectionSelect(_IcecoSelect):
    """Battery low-voltage cut-off level — Low / Medium / High (command S04)."""

    _attr_name = "Battery Protection"
    _attr_icon = "mdi:car-battery"
    _attr_options = list(BATTERY_PROTECTION_OPTIONS)

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, ENTITY_BATTERY_PROTECTION)

    @property
    def current_option(self) -> str | None:
        status = self.coordinator.data.status
        if status is None or not 1 <= status.battery_protection_level <= 3:
            return None
        return BATTERY_PROTECTION_OPTIONS[status.battery_protection_level - 1]

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_battery_protection(
            BATTERY_PROTECTION_OPTIONS.index(option) + 1
        )


class IcecoDisplayUnitSelect(_IcecoSelect):
    """The unit shown on the fridge's own display — °C or °F (command S07).

    Independent of how Home Assistant displays the temperatures.
    """

    _attr_name = "Display Unit"
    _attr_icon = "mdi:thermometer"
    _attr_options = list(DISPLAY_UNIT_OPTIONS)

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, ENTITY_DISPLAY_UNIT)

    @property
    def current_option(self) -> str | None:
        return "°C" if self.coordinator.data.unit_mode == "C" else "°F"

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_display_unit(option == "°C")
