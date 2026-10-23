"""Tests for Iceco config flow and options flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iceco.const import (
    CONF_DEVICE_ADDRESS,
    CONF_POLL_INTERVAL,
    CONF_POWER_LOSS_TIMEOUT,
    CONF_TEMP_DEVIATION_DURATION,
    CONF_TEMP_DEVIATION_THRESHOLD,
    DOMAIN,
)

TEST_ADDRESS = "AA:BB:CC:DD:EE:FF"
TEST_NAME = "Iceco Fridge"


def _make_bt_discovery(address: str = TEST_ADDRESS, name: str = TEST_NAME):
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data={45042: b"\x39\xf1\xd1\x13"},
        service_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=MagicMock(),
        advertisement=MagicMock(),
        connectable=True,
        time=0.0,
        tx_power=-127,
    )


def _make_discovered_device(address: str = TEST_ADDRESS, name: str = TEST_NAME):
    device = MagicMock()
    device.address = address
    device.name = name
    device.service_uuids = ["0000fff0-0000-1000-8000-00805f9b34fb"]
    device.manufacturer_data = {45042: b"\x39\xf1\xd1\x13"}
    return device


# ---------------------------------------------------------------------------
# Bluetooth discovery path
# ---------------------------------------------------------------------------


class TestBluetoothDiscovery:
    async def test_discovery_shows_confirm_form(self, hass):
        discovery = _make_bt_discovery()
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "confirm"

    async def test_discovery_creates_entry_on_confirm(self, hass):
        discovery = _make_bt_discovery()
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_DEVICE_ADDRESS] == TEST_ADDRESS

    async def test_discovery_duplicate_aborts(self, hass):
        existing = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_DEVICE_ADDRESS: TEST_ADDRESS},
            unique_id=TEST_ADDRESS,
        )
        existing.add_to_hass(hass)

        discovery = _make_bt_discovery()
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_discovery_title_uses_device_name(self, hass):
        discovery = _make_bt_discovery(name="My Iceco")
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result["title"] == "My Iceco"

    async def test_discovery_falls_back_title_when_no_name(self, hass):
        discovery = MagicMock(spec=BluetoothServiceInfoBleak)
        discovery.address = TEST_ADDRESS
        discovery.name = None
        discovery.service_uuids = ["0000fff0-0000-1000-8000-00805f9b34fb"]
        discovery.manufacturer_data = {45042: b"\x39\xf1\xd1\x13"}
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result["title"] == "Iceco Refrigerator"

    async def test_discovery_aborts_for_non_iceco_fff0_device(self, hass):
        discovery = _make_bt_discovery()
        discovery = BluetoothServiceInfoBleak(
            name="tps",
            address="11:22:33:44:55:66",
            rssi=-60,
            manufacturer_data={2300: b"\x00\x00\x00"},  # not Iceco
            service_data={},
            service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
            source="local",
            device=MagicMock(),
            advertisement=MagicMock(),
            connectable=True,
            time=0.0,
            tx_power=-127,
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )
        assert result["type"] == FlowResultType.ABORT


# ---------------------------------------------------------------------------
# Manual user path — no devices found
# ---------------------------------------------------------------------------


class TestManualFlowNoDevices:
    async def test_shows_manual_entry_form_when_no_devices(self, hass):
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

    async def test_manual_entry_creates_entry(self, hass):
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        with patch(
            "custom_components.iceco.config_flow.async_ble_device_from_address",
            return_value=MagicMock(),
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={"address": TEST_ADDRESS},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_DEVICE_ADDRESS] == TEST_ADDRESS

    async def test_manual_entry_unreachable_device_errors_then_recovers(self, hass):
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        with patch(
            "custom_components.iceco.config_flow.async_ble_device_from_address",
            return_value=None,
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={"address": TEST_ADDRESS},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "cannot_connect"}

        with patch(
            "custom_components.iceco.config_flow.async_ble_device_from_address",
            return_value=MagicMock(),
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={"address": TEST_ADDRESS},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY

    async def test_manual_entry_duplicate_aborts(self, hass):
        MockConfigEntry(
            domain=DOMAIN,
            data={CONF_DEVICE_ADDRESS: TEST_ADDRESS},
            unique_id=TEST_ADDRESS,
        ).add_to_hass(hass)
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"address": TEST_ADDRESS},
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Manual user path — devices found (select_device step)
# ---------------------------------------------------------------------------


class TestManualFlowWithDevices:
    async def test_shows_select_device_form_when_devices_found(self, hass):
        fake_device = _make_discovered_device()
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[fake_device],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "select_device"

    async def test_non_iceco_fff0_device_is_ignored(self, hass):
        """A device advertising only the generic FFF0 UUID must not be offered."""
        impostor = _make_discovered_device(address="11:22:33:44:55:66")
        impostor.manufacturer_data = {2300: b"\x00\x00\x00"}  # not Iceco
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[impostor],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        # Falls through to the manual-address form, not the device picker.
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

    async def test_select_device_creates_entry(self, hass):
        fake_device = _make_discovered_device()
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[fake_device],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"address": TEST_ADDRESS},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_DEVICE_ADDRESS] == TEST_ADDRESS

    async def test_select_device_duplicate_aborts(self, hass):
        existing = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_DEVICE_ADDRESS: TEST_ADDRESS},
            unique_id=TEST_ADDRESS,
        )
        existing.add_to_hass(hass)

        fake_device = _make_discovered_device()
        with patch(
            "custom_components.iceco.config_flow.async_discovered_service_info",
            return_value=[fake_device],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"address": TEST_ADDRESS},
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class TestOptionsFlow:
    async def test_options_flow_shows_init_form(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_DEVICE_ADDRESS: TEST_ADDRESS},
            unique_id=TEST_ADDRESS,
            options={},
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_options_flow_saves_values(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_DEVICE_ADDRESS: TEST_ADDRESS},
            unique_id=TEST_ADDRESS,
            options={},
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_POLL_INTERVAL: 90,
                CONF_POWER_LOSS_TIMEOUT: 20,
                CONF_TEMP_DEVIATION_THRESHOLD: 4,
                CONF_TEMP_DEVIATION_DURATION: 10,
            },
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_POLL_INTERVAL] == 90
        assert result["data"][CONF_POWER_LOSS_TIMEOUT] == 20
