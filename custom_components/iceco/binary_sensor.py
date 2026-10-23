"""Binary sensor platform for Iceco refrigerator."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_DEVIATION,
    ATTR_LAST_UPDATE,
    ATTR_SET_TEMPERATURE,
    ATTR_THRESHOLD,
    ATTR_TIMEOUT_MINUTES,
    CONF_DEVICE_ADDRESS,
    CONF_POWER_LOSS_TIMEOUT,
    CONF_TEMP_DEVIATION_THRESHOLD,
    DEFAULT_POWER_LOSS_TIMEOUT,
    DEFAULT_TEMP_DEVIATION_THRESHOLD,
    ENTITY_LOW_BATTERY,
    ENTITY_POWER_LOSS_ALARM,
    ENTITY_TEMP_ALARM_LEFT,
    ENTITY_TEMP_ALARM_RIGHT,
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
    """Set up Iceco binary sensor entities from a config entry."""
    coordinator: IcecoDataUpdateCoordinator = entry.runtime_data

    async_add_entities(
        [
            IcecoPowerLossAlarm(coordinator, entry),
            IcecoTempAlarm(coordinator, entry, "left"),
            IcecoTempAlarm(coordinator, entry, "right"),
            IcecoLowBattery(coordinator, entry),
        ]
    )


class IcecoPowerLossAlarm(
    IcecoEntity, BinarySensorEntity
):
    """Binary sensor for power loss / offline alarm."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)

        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{ENTITY_POWER_LOSS_ALARM}"
        self._attr_name = "Power Loss Alarm"
        self._entry = entry

    @property
    def is_on(self) -> bool:
        """Return True if power loss detected."""
        return self.coordinator.data.power_loss_alarm

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {
            ATTR_TIMEOUT_MINUTES: self._entry.options.get(
                CONF_POWER_LOSS_TIMEOUT, DEFAULT_POWER_LOSS_TIMEOUT
            )
        }

        if self.coordinator.data.last_update:
            attrs[ATTR_LAST_UPDATE] = self.coordinator.data.last_update.isoformat()

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Power loss alarm is always available to report connection issues
        return True


class IcecoLowBattery(
    IcecoEntity, BinarySensorEntity
):
    """On when the supply voltage is at/below the compressor cut-out for the
    active battery-protection level (fridge has or is about to shut the
    compressor off to protect the battery)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{ENTITY_LOW_BATTERY}"
        self._attr_name = "Low Battery"

    @property
    def is_on(self) -> bool | None:
        """Return True if voltage is at/below the compressor cut-out."""
        status = self.coordinator.data.status
        if not status or status.battery_voltage is None:
            return None
        _system, cut_out, _cut_in = battery_thresholds(
            status.battery_protection_level, status.battery_voltage
        )
        if cut_out is None:
            return None
        return status.battery_voltage <= cut_out

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the thresholds in play."""
        status = self.coordinator.data.status
        if not status:
            return {}
        system, cut_out, cut_in = battery_thresholds(
            status.battery_protection_level, status.battery_voltage
        )
        if cut_out is None:
            return {}
        return {
            "voltage": status.battery_voltage,
            "system_voltage": system,
            "compressor_cut_out_v": cut_out,
            "compressor_cut_in_v": cut_in,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.connection_state == "connected"
        )


class IcecoTempAlarm(IcecoEntity, BinarySensorEntity):
    """Binary sensor for temperature deviation alarm."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)

        self._zone = zone
        self._entry = entry

        entity_id = ENTITY_TEMP_ALARM_LEFT if zone == "left" else ENTITY_TEMP_ALARM_RIGHT
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_{entity_id}"
        self._attr_name = f"{zone.capitalize()} Zone Temperature Alarm"

    @property
    def is_on(self) -> bool:
        """Return True if temperature deviation alarm triggered."""
        if self._zone == "left":
            return self.coordinator.data.left_temp_alarm
        return self.coordinator.data.right_temp_alarm

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        # Get current temp (from SECONDARY) and setpoint (from PRIMARY)
        if self._zone == "left":
            actual = self.coordinator.data.left_current_temp
            setpoint = self.coordinator.data.left_setpoint
        else:
            actual = self.coordinator.data.right_current_temp
            setpoint = self.coordinator.data.right_setpoint

        # Return empty if no data available
        if actual is None:
            return {}

        attrs = {
            ATTR_CURRENT_TEMPERATURE: actual,
            ATTR_THRESHOLD: self._entry.options.get(
                CONF_TEMP_DEVIATION_THRESHOLD, DEFAULT_TEMP_DEVIATION_THRESHOLD
            ),
        }

        if setpoint is not None:
            attrs[ATTR_SET_TEMPERATURE] = setpoint
            attrs[ATTR_DEVIATION] = actual - setpoint

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.connection_state == "connected"
        )
