"""Base entity for the Iceco integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ADDRESS, DOMAIN
from .coordinator import IcecoDataUpdateCoordinator


def build_device_info(address: str) -> DeviceInfo:
    """Return DeviceInfo for an Iceco device identified by BLE address."""
    return DeviceInfo(
        identifiers={(DOMAIN, address)},
        name="Iceco Refrigerator",
        manufacturer="Iceco",
        model="Dual Zone Refrigerator",
    )


class IcecoEntity(CoordinatorEntity[IcecoDataUpdateCoordinator]):
    """Base class: every Iceco entity belongs to the one fridge device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IcecoDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_device_info = build_device_info(entry.data[CONF_DEVICE_ADDRESS])
