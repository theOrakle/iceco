"""Tests for IcecoDataUpdateCoordinator notification processing and alarm logic.

BLE client calls are mocked — no hardware required.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.iceco.const import (
    CONF_POWER_LOSS_TIMEOUT,
    CONF_TEMP_DEVIATION_DURATION,
    CONF_TEMP_DEVIATION_THRESHOLD,
    DEFAULT_POWER_LOSS_TIMEOUT,
    DEFAULT_TEMP_DEVIATION_DURATION,
    DEFAULT_TEMP_DEVIATION_THRESHOLD,
)
from custom_components.iceco.coordinator import IcecoDataUpdateCoordinator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_ADDRESS = "AA:BB:CC:DD:EE:FF"


def _make_entry(address: str = TEST_ADDRESS, options: dict | None = None):
    entry = MagicMock()
    entry.data = {"device_address": address}
    entry.options = options or {}
    entry.entry_id = "test_entry_id"
    return entry


def _make_hass(entry=None):
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry or _make_entry()
    return hass


def _make_coord(address: str = TEST_ADDRESS, options: dict | None = None):
    entry = _make_entry(address, options)
    hass = _make_hass(entry)
    ble_device = MagicMock()
    ble_device.address = address
    coord = IcecoDataUpdateCoordinator(hass, ble_device, entry)
    # Suppress HA coordinator machinery — we're testing data logic only
    coord.async_set_updated_data = MagicMock()
    # async_create_task on a MagicMock hass never awaits the coro; close it so
    # pytest doesn't warn about "coroutine was never awaited".
    coord.hass.async_create_task.side_effect = lambda coro, *a, **k: (
        coro.close() or MagicMock(done=lambda: True)
    )
    return coord


# Raw notification bytes
PRIMARY_ON_UNLOCKED = b",-18,-15,1,126,1\n"   # power_status=1: on, unlocked
PRIMARY_ON_LOCKED = b",-18,-15,1,126,2\n"      # power_status=2: on, locked
PRIMARY_OFF = b",-18,-15,1,126,0\n"            # power_status=0: off
PRIMARY_POSITIVE = b",4,0,2,130,1\n"           # positive setpoints, 13.0V
SECONDARY_CELSIUS = b"/S00/U/2,1,1,-15,-12\n"  # ECO on, Celsius current temps
SECONDARY_FAHRENHEIT = b"/S00/U/2,0,2,14,32\n" # MAX mode, Fahrenheit current temps
SECONDARY_MAX = b"/S00/U/2,0,1,-15,-12\n"      # MAX mode, Celsius


# ---------------------------------------------------------------------------
# PRIMARY notification processing
# ---------------------------------------------------------------------------


class TestPrimaryNotification:
    def test_sets_left_setpoint(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.left_setpoint == -18

    def test_sets_right_setpoint(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.right_setpoint == -15

    def test_power_status_1_is_on(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.power_on is True

    def test_power_status_2_is_on(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_LOCKED)
        assert coord.data.power_on is True

    def test_power_status_0_is_off(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_OFF)
        assert coord.data.power_on is False

    def test_power_status_2_sets_locked(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_LOCKED)
        assert coord.data.locked is True

    def test_power_status_1_is_unlocked(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.locked is False

    def test_battery_voltage_decoded(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.status.battery_voltage == pytest.approx(12.6)

    def test_clears_power_loss_alarm(self):
        coord = _make_coord()
        coord.data.power_loss_alarm = True
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.power_loss_alarm is False

    def test_sets_last_update(self):
        coord = _make_coord()
        before = dt_util.utcnow()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        assert coord.data.last_update >= before

    def test_triggers_ha_update(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_ON_UNLOCKED)
        coord.async_set_updated_data.assert_called_once()

    def test_positive_setpoints(self):
        coord = _make_coord()
        coord._notification_callback(0, PRIMARY_POSITIVE)
        assert coord.data.left_setpoint == 4
        assert coord.data.right_setpoint == 0


# ---------------------------------------------------------------------------
# SECONDARY notification processing
# ---------------------------------------------------------------------------


class TestSecondaryNotification:
    def test_sets_left_current_temp_celsius(self):
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_CELSIUS)
        assert coord.data.left_current_temp == -15

    def test_sets_right_current_temp_celsius(self):
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_CELSIUS)
        assert coord.data.right_current_temp == -12

    def test_fahrenheit_converts_left_to_celsius(self):
        # 14°F → (14-32)*5/9 = -10°C
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_FAHRENHEIT)
        assert coord.data.left_current_temp == -10

    def test_fahrenheit_converts_right_to_celsius(self):
        # 32°F → 0°C
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_FAHRENHEIT)
        assert coord.data.right_current_temp == 0

    def test_eco_max_1_means_eco_mode_true(self):
        # eco_max=1 in SECONDARY → ECO mode is active
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_CELSIUS)
        assert coord.data.eco_mode is True

    def test_eco_max_0_means_eco_mode_false(self):
        # eco_max=0 → MAX mode
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_MAX)
        assert coord.data.eco_mode is False

    def test_unit_mode_celsius(self):
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_CELSIUS)
        assert coord.data.unit_mode == "C"

    def test_unit_mode_fahrenheit(self):
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_FAHRENHEIT)
        assert coord.data.unit_mode == "F"

    def test_triggers_ha_update(self):
        coord = _make_coord()
        coord._notification_callback(0, SECONDARY_CELSIUS)
        coord.async_set_updated_data.assert_called_once()


# ---------------------------------------------------------------------------
# Unknown / malformed notifications
# ---------------------------------------------------------------------------


class TestUnknownNotification:
    def test_garbage_data_does_not_update(self):
        coord = _make_coord()
        coord._notification_callback(0, b"garbage\n")
        coord.async_set_updated_data.assert_not_called()

    def test_empty_bytes_does_not_raise(self):
        coord = _make_coord()
        coord._notification_callback(0, b"")
        coord.async_set_updated_data.assert_not_called()

    def test_non_ascii_does_not_raise(self):
        coord = _make_coord()
        coord._notification_callback(0, b"\xff\xfe\xfd")
        coord.async_set_updated_data.assert_not_called()


# ---------------------------------------------------------------------------
# Temperature alarm logic
# ---------------------------------------------------------------------------


class TestZoneAlarm:
    def test_no_alarm_without_current_temp(self):
        coord = _make_coord()
        coord.data.left_setpoint = -18
        # left_current_temp is None
        assert coord._check_zone_alarm("left") is False

    def test_no_alarm_without_setpoint(self):
        coord = _make_coord()
        coord.data.left_current_temp = -10
        # left_setpoint is None
        assert coord._check_zone_alarm("left") is False

    def test_no_alarm_within_threshold(self):
        coord = _make_coord()
        coord.data.left_current_temp = -15
        coord.data.left_setpoint = -18  # deviation=3, threshold=5
        assert coord._check_zone_alarm("left") is False

    def test_no_alarm_immediately_when_threshold_exceeded(self):
        # First observation above threshold starts the timer but does not alarm yet
        coord = _make_coord()
        coord.data.left_current_temp = -10
        coord.data.left_setpoint = -18  # deviation=8 > threshold=5
        result = coord._check_zone_alarm("left")
        assert result is False
        assert coord.data._left_alarm_start is not None

    def test_alarm_fires_after_duration(self):
        coord = _make_coord(options={
            CONF_TEMP_DEVIATION_THRESHOLD: DEFAULT_TEMP_DEVIATION_THRESHOLD,
            CONF_TEMP_DEVIATION_DURATION: DEFAULT_TEMP_DEVIATION_DURATION,
        })
        coord.data.left_current_temp = -10
        coord.data.left_setpoint = -18  # deviation=8 > threshold=5
        # Simulate alarm_start exceeding duration threshold
        coord.data._left_alarm_start = dt_util.utcnow() - timedelta(
            minutes=DEFAULT_TEMP_DEVIATION_DURATION + 1
        )
        assert coord._check_zone_alarm("left") is True

    def test_alarm_does_not_fire_before_duration(self):
        coord = _make_coord(options={
            CONF_TEMP_DEVIATION_THRESHOLD: DEFAULT_TEMP_DEVIATION_THRESHOLD,
            CONF_TEMP_DEVIATION_DURATION: DEFAULT_TEMP_DEVIATION_DURATION,
        })
        coord.data.left_current_temp = -10
        coord.data.left_setpoint = -18
        # alarm_start less than duration threshold ago
        coord.data._left_alarm_start = dt_util.utcnow() - timedelta(
            minutes=DEFAULT_TEMP_DEVIATION_DURATION - 1
        )
        assert coord._check_zone_alarm("left") is False

    def test_alarm_clears_when_back_within_threshold(self):
        coord = _make_coord()
        coord.data.left_current_temp = -18
        coord.data.left_setpoint = -18  # deviation=0
        coord.data.left_temp_alarm = True
        result = coord._check_zone_alarm("left")
        assert result is False
        assert coord.data._left_alarm_start is None

    def test_hysteresis_prevents_clear_near_threshold(self):
        # Alarm was active; deviation=4, effective clear threshold=5-2=3.
        # 4 > 3, so alarm should stay active.
        coord = _make_coord(options={CONF_TEMP_DEVIATION_THRESHOLD: 5})
        coord.data.left_current_temp = -14
        coord.data.left_setpoint = -18  # deviation=4
        coord.data.left_temp_alarm = True
        coord.data._left_alarm_start = dt_util.utcnow() - timedelta(
            minutes=DEFAULT_TEMP_DEVIATION_DURATION + 1
        )
        assert coord._check_zone_alarm("left") is True

    def test_hysteresis_allows_clear_below_effective_threshold(self):
        # Alarm was active; deviation=2, effective clear threshold=5-2=3.
        # 2 <= 3, so alarm should clear.
        coord = _make_coord(options={CONF_TEMP_DEVIATION_THRESHOLD: 5})
        coord.data.left_current_temp = -16
        coord.data.left_setpoint = -18  # deviation=2
        coord.data.left_temp_alarm = True
        assert coord._check_zone_alarm("left") is False

    def test_right_zone_alarm(self):
        coord = _make_coord(options={
            CONF_TEMP_DEVIATION_THRESHOLD: DEFAULT_TEMP_DEVIATION_THRESHOLD,
            CONF_TEMP_DEVIATION_DURATION: DEFAULT_TEMP_DEVIATION_DURATION,
        })
        coord.data.right_current_temp = -5
        coord.data.right_setpoint = -18  # deviation=13 > threshold=5
        coord.data._right_alarm_start = dt_util.utcnow() - timedelta(
            minutes=DEFAULT_TEMP_DEVIATION_DURATION + 1
        )
        assert coord._check_zone_alarm("right") is True


# ---------------------------------------------------------------------------
# Power loss detection
# ---------------------------------------------------------------------------


class TestPowerLossAlarm:
    async def test_power_loss_alarm_triggers_when_link_dead_past_timeout(self):
        coord = _make_coord(options={CONF_POWER_LOSS_TIMEOUT: DEFAULT_POWER_LOSS_TIMEOUT})
        coord._link_alive_at = dt_util.utcnow() - timedelta(
            minutes=DEFAULT_POWER_LOSS_TIMEOUT + 1
        )
        coord.data.connection_state = "connected"
        # A dead link also trips the stale-connection recovery — stub it out.
        coord._async_disconnect = AsyncMock()
        coord._ensure_reconnecting = MagicMock()

        await coord._async_update_data()

        assert coord.data.power_loss_alarm is True

    async def test_power_loss_alarm_clears_when_keepalive_recent(self):
        coord = _make_coord(options={CONF_POWER_LOSS_TIMEOUT: DEFAULT_POWER_LOSS_TIMEOUT})
        coord._link_alive_at = dt_util.utcnow() - timedelta(seconds=10)  # keepalive is fine
        coord.data.power_loss_alarm = True
        coord.data.connection_state = "connected"

        await coord._async_update_data()

        assert coord.data.power_loss_alarm is False

    async def test_no_alarm_before_any_contact(self):
        coord = _make_coord()
        coord._link_alive_at = None
        coord._reconnect_task = MagicMock(done=lambda: False)

        await coord._async_update_data()

        assert coord.data.power_loss_alarm is False


# ---------------------------------------------------------------------------
# Connection lifecycle (lock, single disconnect path, shutdown release)
# ---------------------------------------------------------------------------


def _fake_client(coord, *, notify_error: Exception | None = None) -> MagicMock:
    """Build a mock BleakClient wired to the coordinator's notification event."""
    client = MagicMock()
    client.is_connected = True

    async def _start_notify(*_args, **_kwargs):
        if notify_error is not None:
            raise notify_error
        coord._first_notification_event.set()

    client.start_notify = AsyncMock(side_effect=_start_notify)
    client.disconnect = AsyncMock()
    return client


class TestConnectionLifecycle:
    async def test_connect_is_noop_when_already_connected(self):
        coord = _make_coord()
        coord._client = _fake_client(coord)  # already "connected"

        with patch(
            "custom_components.iceco.coordinator.establish_connection"
        ) as establish, patch(
            "custom_components.iceco.coordinator.close_stale_connections",
            AsyncMock(),
        ):
            await coord._async_connect()

        establish.assert_not_called()
        assert coord.data.connection_state == "connected"

    async def test_failed_start_notify_releases_the_link(self):
        coord = _make_coord()
        client = _fake_client(coord, notify_error=RuntimeError("boom"))

        with patch(
            "custom_components.iceco.coordinator.establish_connection",
            AsyncMock(return_value=client),
        ), patch(
            "custom_components.iceco.coordinator.close_stale_connections", AsyncMock()
        ):
            with pytest.raises(Exception):
                await coord._async_connect()

        client.disconnect.assert_awaited_once()
        assert coord._client is None
        assert coord.data.connection_state == "disconnected"

    async def test_concurrent_connects_open_a_single_link(self):
        coord = _make_coord()
        coord.hass.async_create_task.side_effect = lambda coro, *a, **k: (
            coro.close() or MagicMock(done=lambda: True)
        )

        async def _establish(*_args, **_kwargs):
            await asyncio.sleep(0)
            return _fake_client(coord)

        establish = AsyncMock(side_effect=_establish)
        with patch(
            "custom_components.iceco.coordinator.establish_connection", establish
        ), patch(
            "custom_components.iceco.coordinator.close_stale_connections", AsyncMock()
        ):
            await asyncio.gather(coord._async_connect(), coord._async_connect())

        assert establish.call_count == 1
        assert coord.data.connection_state == "connected"

    async def test_shutdown_disconnects_and_blocks_reconnect(self):
        coord = _make_coord()
        client = _fake_client(coord)
        coord._client = client

        with patch(
            "custom_components.iceco.coordinator.close_stale_connections", AsyncMock()
        ):
            await coord.async_shutdown()

        client.disconnect.assert_awaited_once()
        assert coord._client is None
        assert coord._shutting_down is True

        # A late disconnect callback after shutdown must not schedule a reconnect.
        coord.hass.async_create_task.reset_mock()
        coord._client = client
        coord._handle_disconnect(client)
        coord.hass.async_create_task.assert_not_called()

    async def test_unexpected_disconnect_schedules_reconnect(self):
        coord = _make_coord()
        client = _fake_client(coord)
        coord._client = client

        def _consume(coro, *_a, **_k):
            coro.close()  # avoid "coroutine was never awaited" warning
            return MagicMock(done=lambda: False)

        coord.hass.async_create_task.side_effect = _consume

        coord._handle_disconnect(client)

        assert coord._client is None
        assert coord.data.connection_state == "disconnected"
        coord.hass.async_create_task.assert_called_once()

    async def test_manual_disconnect_uses_expected_flag(self):
        coord = _make_coord()
        client = _fake_client(coord)
        coord._client = client

        with patch(
            "custom_components.iceco.coordinator.close_stale_connections", AsyncMock()
        ):
            await coord.async_manual_disconnect()

        client.disconnect.assert_awaited_once()
        assert coord._expected_disconnect is True
        assert coord._client is None


# ---------------------------------------------------------------------------
# Command methods (/S00/0L firmware)
# ---------------------------------------------------------------------------


class TestCommands:
    def _connected(self):
        coord = _make_coord()
        client = MagicMock()
        client.is_connected = True
        client.write_gatt_char = AsyncMock()
        coord._client = client
        return coord, client

    async def test_set_eco_mode_sends_s06(self):
        coord, client = self._connected()
        await coord.async_set_eco_mode(True)
        assert client.write_gatt_char.await_args[0][1] == b"/S06/1/001\n"
        assert coord.data.eco_mode is True
        await coord.async_set_eco_mode(False)
        assert client.write_gatt_char.await_args[0][1] == b"/S06/1/002\n"

    async def test_set_battery_protection_sends_s04(self):
        coord, client = self._connected()
        await coord.async_set_battery_protection(2)
        assert client.write_gatt_char.await_args[0][1] == b"/S04/1/002\n"

    async def test_set_display_unit_sends_s07(self):
        coord, client = self._connected()
        await coord.async_set_display_unit(True)
        assert client.write_gatt_char.await_args[0][1] == b"/S07/1/001\n"
        assert coord.data.unit_mode == "C"

    async def test_setpoint_routes_through_raw_command(self):
        coord, client = self._connected()
        await coord.async_set_left_temperature(-18)
        assert client.write_gatt_char.await_args[0][1] == b"/S03/1/-18\n"
        assert coord.data.left_setpoint == -18

    async def test_command_when_disconnected_raises(self):
        coord = _make_coord()
        coord._client = None
        with pytest.raises(Exception):
            await coord.async_set_eco_mode(True)
