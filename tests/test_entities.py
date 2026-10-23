"""Entity registration details that must not change between refactors."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from custom_components.iceco import binary_sensor, climate, select, sensor, switch
from custom_components.iceco.const import CONF_DEVICE_ADDRESS, DOMAIN

ADDRESS = "AA:BB:CC:DD:EE:FF"


async def _entities(module) -> list:
    entry = MagicMock(spec=ConfigEntry)
    entry.data = {CONF_DEVICE_ADDRESS: ADDRESS}
    entry.runtime_data = MagicMock()
    added: list = []
    await module.async_setup_entry(MagicMock(), entry, added.extend)
    return added


@pytest.mark.parametrize(
    "module", [binary_sensor, climate, select, sensor, switch], ids=lambda m: m.__name__
)
async def test_entities_share_device_and_naming(module) -> None:
    """Every entity joins the one fridge device and uses device-relative names."""
    entities = await _entities(module)
    assert entities
    for entity in entities:
        assert entity.has_entity_name is True
        info = entity.device_info
        assert info["identifiers"] == {(DOMAIN, ADDRESS)}
        assert info["name"] == "Iceco Refrigerator"
        assert info["manufacturer"] == "Iceco"
        assert info["model"] == "Dual Zone Refrigerator"


async def test_entity_catalogue_is_stable() -> None:
    """Unique IDs, names and categories are what existing installs already have."""
    seen = {}
    for module in (binary_sensor, climate, select, sensor, switch):
        for entity in await _entities(module):
            seen[entity.unique_id] = (
                type(entity).__name__,
                entity.name,
                getattr(entity, "entity_category", None),
            )
    assert {uid.removeprefix(f"{ADDRESS}_"): v for uid, v in seen.items()} == EXPECTED


EXPECTED: dict = {
    "power_loss_alarm": ("IcecoPowerLossAlarm", "Power Loss Alarm", None),
    "temp_alarm_left": ("IcecoTempAlarm", "Left Zone Temperature Alarm", None),
    "temp_alarm_right": ("IcecoTempAlarm", "Right Zone Temperature Alarm", None),
    "low_battery": ("IcecoLowBattery", "Low Battery", None),
    "climate_left": ("IcecoClimate", "Left Zone", None),
    "climate_right": ("IcecoClimate", "Right Zone", None),
    "eco_mode": ("IcecoModeSelect", "Mode", EntityCategory.CONFIG),
    "battery_protection": ("IcecoBatteryProtectionSelect", "Battery Protection", EntityCategory.CONFIG),
    "display_unit": ("IcecoDisplayUnitSelect", "Display Unit", EntityCategory.CONFIG),
    "battery_voltage": ("IcecoBatterySensor", "Battery Voltage", EntityCategory.DIAGNOSTIC),
    "power_switch": ("IcecoPowerSwitch", "Power", None),
    "connection": ("IcecoConnectionSwitch", "BLE Connection", EntityCategory.CONFIG),
}
