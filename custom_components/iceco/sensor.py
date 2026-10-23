"""Sensor platform for Iceco refrigerator."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_BATTERY_PROTECTION_LEVEL,
    CONF_DEVICE_ADDRESS,
    ENTITY_BATTERY_VOLTAGE,
    battery_thresholds,
)
from .coordinator import IcecoDataUpdateCoordinator
from .entity import IcecoEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Iceco sensor entities from a config entry."""
    coordinator: IcecoDataUpdateCoordinator = entry.runtime_data

    async_add_entities([IcecoBatterySensor(coordinator, entry)])


class IcecoBatterySensor(IcecoEntity, SensorEntity):
    """Supply / battery voltage."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)

        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{ENTITY_BATTERY_VOLTAGE}"
        self._attr_name = "Battery Voltage"

    @property
    def native_value(self) -> float | None:
        """Return the battery voltage."""
        if not self.coordinator.data.status:
            return None

        return self.coordinator.data.status.battery_voltage

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Battery-protection level and the cut-out / cut-in voltages in play."""
        status = self.coordinator.data.status
        if not status:
            return {}
        attrs: dict[str, Any] = {
            ATTR_BATTERY_PROTECTION_LEVEL: status.battery_protection_level
        }
        system, cut_out, cut_in = battery_thresholds(
            status.battery_protection_level, status.battery_voltage
        )
        if cut_out is not None:
            attrs["system_voltage"] = system
            attrs["compressor_cut_out_v"] = cut_out
            attrs["compressor_cut_in_v"] = cut_in
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.connection_state == "connected"
        )
