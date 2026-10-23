"""Config flow for Iceco Refrigerator integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_ADDRESS,
    ICECO_MANUFACTURER_ID,
    SERVICE_UUID,
    CONF_POLL_INTERVAL,
    CONF_POWER_LOSS_TIMEOUT,
    CONF_TEMP_DEVIATION_DURATION,
    CONF_TEMP_DEVIATION_THRESHOLD,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POWER_LOSS_TIMEOUT,
    DEFAULT_TEMP_DEVIATION_DURATION,
    DEFAULT_TEMP_DEVIATION_THRESHOLD,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MAX_POWER_LOSS_TIMEOUT,
    MAX_TEMP_DEVIATION_DURATION,
    MAX_TEMP_DEVIATION_THRESHOLD,
    MIN_POLL_INTERVAL,
    MIN_POWER_LOSS_TIMEOUT,
    MIN_TEMP_DEVIATION_DURATION,
    MIN_TEMP_DEVIATION_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)


def _is_iceco(device: BluetoothServiceInfoBleak) -> bool:
    """Return True only for genuine Iceco advertisements.

    The FFF0 service UUID alone is a generic placeholder used by many unrelated
    BLE devices, so we also require the Iceco manufacturer ID.
    """
    return (
        SERVICE_UUID in device.service_uuids
        and ICECO_MANUFACTURER_ID in device.manufacturer_data
    )


class IcecoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Iceco Refrigerator."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: list[BluetoothServiceInfoBleak] = []

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle bluetooth discovery."""
        _LOGGER.debug(
            "Bluetooth discovery: %s (mfr_ids=%s)",
            discovery_info.address,
            list(discovery_info.manufacturer_data),
        )

        # The bare FFF0 service UUID is a generic placeholder used by many
        # unrelated BLE gadgets. Only surface a setup card for real Iceco units.
        # (Kept out of the manifest matcher so HA still tracks the device as
        # connectable even for adverts that omit the manufacturer data.)
        if not _is_iceco(discovery_info):
            return self.async_abort(reason="not_supported")

        # Check if already configured
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        self.context["title_placeholders"] = {
            "name": discovery_info.name or "Iceco Refrigerator",
            "address": discovery_info.address,
        }

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or "Iceco Refrigerator",
                data={CONF_DEVICE_ADDRESS: self._discovery_info.address},
            )

        placeholders = self.context.get("title_placeholders", {})

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": placeholders.get("name", "Unknown"),
                "address": placeholders.get("address", "Unknown"),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user-initiated setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]

            # Check if already configured
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            # A typed-in address must belong to a fridge a Bluetooth adapter can
            # currently reach, the BLE equivalent of testing a connection.
            if async_ble_device_from_address(self.hass, address, connectable=True):
                return self.async_create_entry(
                    title=f"Iceco Refrigerator ({address})",
                    data={CONF_DEVICE_ADDRESS: address},
                )
            errors["base"] = "cannot_connect"

        # Scan for devices
        self._discovered_devices = list(
            async_discovered_service_info(self.hass, connectable=True)
        )

        # Filter for genuine Iceco devices
        iceco_devices = [
            device for device in self._discovered_devices if _is_iceco(device)
        ]

        if iceco_devices:
            # Show discovered devices
            return await self.async_step_select_device()

        # No devices found, ask for manual entry
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS, default=(user_input or {}).get(CONF_ADDRESS, "")
                    ): str
                }
            ),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let user select from discovered devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]

            # Check if already configured
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            # Find the selected device
            selected_device = next(
                (d for d in self._discovered_devices if d.address == address), None
            )

            if selected_device:
                return self.async_create_entry(
                    title=selected_device.name or f"Iceco Refrigerator ({address})",
                    data={CONF_DEVICE_ADDRESS: address},
                )

        # Build list of discovered devices
        devices = {
            device.address: f"{device.name or 'Unknown'} ({device.address})"
            for device in self._discovered_devices
            if _is_iceco(device)
        }

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(devices)}),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> IcecoOptionsFlow:
        """Get the options flow for this handler."""
        return IcecoOptionsFlow()


class IcecoOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Iceco integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                    vol.Optional(
                        CONF_POWER_LOSS_TIMEOUT,
                        default=self.config_entry.options.get(
                            CONF_POWER_LOSS_TIMEOUT, DEFAULT_POWER_LOSS_TIMEOUT
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_POWER_LOSS_TIMEOUT, max=MAX_POWER_LOSS_TIMEOUT
                        ),
                    ),
                    vol.Optional(
                        CONF_TEMP_DEVIATION_THRESHOLD,
                        default=self.config_entry.options.get(
                            CONF_TEMP_DEVIATION_THRESHOLD,
                            DEFAULT_TEMP_DEVIATION_THRESHOLD,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_TEMP_DEVIATION_THRESHOLD,
                            max=MAX_TEMP_DEVIATION_THRESHOLD,
                        ),
                    ),
                    vol.Optional(
                        CONF_TEMP_DEVIATION_DURATION,
                        default=self.config_entry.options.get(
                            CONF_TEMP_DEVIATION_DURATION,
                            DEFAULT_TEMP_DEVIATION_DURATION,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_TEMP_DEVIATION_DURATION,
                            max=MAX_TEMP_DEVIATION_DURATION,
                        ),
                    ),
                }
            ),
        )
