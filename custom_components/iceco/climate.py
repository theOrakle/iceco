"""Climate platform for Iceco refrigerator."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_SET_TEMPERATURE,
    CONF_DEVICE_ADDRESS,
    ENTITY_CLIMATE_LEFT,
    ENTITY_CLIMATE_RIGHT,
    MAX_TEMP,
    MIN_TEMP,
    TEMP_STEP,
)
from .coordinator import IcecoDataUpdateCoordinator
from .entity import IcecoEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Iceco climate entities from a config entry."""
    coordinator: IcecoDataUpdateCoordinator = entry.runtime_data

    async_add_entities(
        [
            IcecoClimate(coordinator, entry, "left"),
            IcecoClimate(coordinator, entry, "right"),
        ]
    )


class IcecoClimate(IcecoEntity, ClimateEntity):
    """Climate entity for Iceco temperature zone."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_preset_modes = ["Refrigeration", "Freezing"]
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, entry)

        self._zone = zone
        self._attr_unique_id = (
            f"{entry.data[CONF_DEVICE_ADDRESS]}_{ENTITY_CLIMATE_LEFT if zone == 'left' else ENTITY_CLIMATE_RIGHT}"
        )
        self._attr_name = f"{zone.capitalize()} Zone"

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature from SECONDARY notification."""
        if self._zone == "left":
            current = self.coordinator.data.left_current_temp
        else:
            current = self.coordinator.data.right_current_temp

        return float(current) if current is not None else None

    @property
    def target_temperature(self) -> float | None:
        """Return the target (set) temperature from PRIMARY notification."""
        if self._zone == "left":
            setpoint = self.coordinator.data.left_setpoint
        else:
            setpoint = self.coordinator.data.right_setpoint

        return float(setpoint) if setpoint is not None else None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return COOL when powered on, OFF when in standby."""
        if not self.coordinator.data.power_on:
            return HVACMode.OFF
        return HVACMode.COOL

    @property
    def hvac_action(self) -> HVACAction | None:
        """Best-effort per-zone activity.

        The fridge has one compressor and no field telling us which zone it is
        feeding, so this is derived: COOLING when the zone is above its setpoint,
        IDLE when at or below it, OFF in standby.
        """
        if not self.coordinator.data.power_on:
            return HVACAction.OFF
        current = self.current_temperature
        target = self.target_temperature
        if current is None or target is None:
            return None
        return HVACAction.COOLING if current > target else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {}
        setpoint = (
            self.coordinator.data.left_setpoint
            if self._zone == "left"
            else self.coordinator.data.right_setpoint
        )
        if setpoint is not None:
            attrs[ATTR_SET_TEMPERATURE] = setpoint
        return attrs

    @property
    def preset_mode(self) -> str | None:
        """Return preset label only when temperature matches a preset's canonical value."""
        temp = self.target_temperature
        if temp == -18:
            return "Freezing"
        if temp == 4:
            return "Refrigeration"
        return None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset — jumps to the standard temp for that mode."""
        if preset_mode == "Freezing":
            await self.async_set_temperature(temperature=-18)
        elif preset_mode == "Refrigeration":
            await self.async_set_temperature(temperature=4)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        temp_int = round(temperature)
        _LOGGER.info("Setting %s zone to %d°C", self._zone, temp_int)

        # Let HomeAssistantError propagate so the UI surfaces the failure.
        if self._zone == "left":
            await self.coordinator.async_set_left_temperature(temp_int)
        else:
            await self.coordinator.async_set_right_temperature(temp_int)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Power the fridge on/off to match the requested HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_power(False)
        elif hvac_mode == HVACMode.COOL:
            await self.coordinator.async_set_power(True)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.connection_state == "connected"
        )
