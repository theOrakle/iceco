"""Tests for Iceco integration setup and unload lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.setup import async_setup_component

import pytest

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iceco.const import CONF_DEVICE_ADDRESS, DOMAIN

TEST_ADDRESS = "AA:BB:CC:DD:EE:FF"


@pytest.fixture
def mock_config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_ADDRESS: TEST_ADDRESS},
        unique_id=TEST_ADDRESS,
    )


# ---------------------------------------------------------------------------
# Setup failure paths
# ---------------------------------------------------------------------------


class TestSetupEntry:
    async def test_setup_raises_config_entry_not_ready_when_no_ble_device(
        self, hass, mock_config_entry
    ):
        mock_config_entry.add_to_hass(hass)

        with patch(
            "custom_components.iceco.bluetooth.async_ble_device_from_address",
            return_value=None,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)

        assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY

    async def test_setup_raises_config_entry_not_ready_when_coordinator_fails(
        self, hass, mock_config_entry
    ):
        mock_config_entry.add_to_hass(hass)

        mock_ble_device = MagicMock()
        mock_ble_device.address = TEST_ADDRESS

        with patch(
            "custom_components.iceco.bluetooth.async_ble_device_from_address",
            return_value=mock_ble_device,
        ), patch(
            "custom_components.iceco.IcecoDataUpdateCoordinator"
        ) as mock_coord_cls:
            mock_coord = MagicMock()
            mock_coord.async_config_entry_first_refresh = AsyncMock(
                side_effect=ConfigEntryNotReady("BLE connection failed")
            )
            mock_coord_cls.return_value = mock_coord

            await hass.config_entries.async_setup(mock_config_entry.entry_id)

        assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY


# ---------------------------------------------------------------------------
# Unload
# ---------------------------------------------------------------------------


class TestUnloadEntry:
    async def test_unload_not_loaded_entry_is_safe(self, hass, mock_config_entry):
        # An entry that was never loaded (e.g. failed with SETUP_RETRY) can be
        # unloaded without error. HA returns False in this case.
        mock_config_entry.add_to_hass(hass)

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)

        assert mock_config_entry.state == ConfigEntryState.NOT_LOADED
        # HA returns True when unloading an entry that was never loaded (no-op)
        assert result is True


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


class TestDebugService:
    async def test_service_registered_once_at_component_setup(self, hass):
        """The action exists as soon as the integration is set up, with no entry loaded."""
        assert await async_setup_component(hass, DOMAIN, {})
        assert hass.services.has_service(DOMAIN, "send_command")

    async def test_service_without_fridge_raises(self, hass):
        await async_setup_component(hass, DOMAIN, {})
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "send_command", {"command": "/S01/1/002"}, blocking=True
            )

    async def test_service_sends_to_loaded_fridge(self, hass, mock_config_entry):
        await async_setup_component(hass, DOMAIN, {})
        mock_config_entry.add_to_hass(hass)
        coordinator = MagicMock()
        coordinator.async_send_raw_command = AsyncMock()
        mock_config_entry.runtime_data = coordinator

        await hass.services.async_call(
            DOMAIN, "send_command", {"command": "/S01/1/002"}, blocking=True
        )

        coordinator.async_send_raw_command.assert_awaited_once_with(b"/S01/1/002\n")
