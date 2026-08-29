"""Coordinator for Iceco refrigerator integration."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Optional

from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .iceco_protocol import IcecoProtocol, IcecoStatus

from .const import (
    ALARM_HYSTERESIS,
    CONF_POLL_INTERVAL,
    CONF_POWER_LOSS_TIMEOUT,
    CONF_TEMP_DEVIATION_DURATION,
    CONF_TEMP_DEVIATION_THRESHOLD,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POWER_LOSS_TIMEOUT,
    DEFAULT_TEMP_DEVIATION_DURATION,
    DEFAULT_TEMP_DEVIATION_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# How long to wait after subscribing for the first notification. Non-fatal now —
# just controls how long connect() blocks before completing anyway.
FIRST_NOTIFICATION_TIMEOUT = 25.0

# Keepalive: the fridge hangs up on a central that goes quiet once it stops
# streaming. Poke it periodically so the link survives idle periods.
#   "read"  — GATT-read a characteristic (silent, preferred)
#   "write" — re-send the current left setpoint (may beep)
#   "none"  — disabled
KEEPALIVE_MODE = "read"
KEEPALIVE_INTERVAL = 5.0


@dataclass
class IcecoData:
    """Data managed by coordinator."""

    status: Optional[IcecoStatus] = None
    last_update: Optional[datetime] = None
    connection_state: str = "disconnected"  # disconnected/connected/reconnecting

    # Current temps (from SECONDARY notification)
    left_current_temp: Optional[int] = None
    right_current_temp: Optional[int] = None

    # Setpoints in °C (read from PRIMARY notification — always °C)
    left_setpoint: Optional[int] = None
    right_setpoint: Optional[int] = None

    # Fridge display unit: "F" or "C" (detected from SECONDARY unit_mode field).
    # Used only to interpret SECONDARY current temperatures — not for commands or PRIMARY.
    unit_mode: str = "F"  # Default; overwritten on first SECONDARY received

    # Alarm states
    left_temp_alarm: bool = False
    right_temp_alarm: bool = False
    power_loss_alarm: bool = False

    # ECO mode state (from SECONDARY eco_max field: 1=ECO, 0=MAX)
    eco_mode: Optional[bool] = None  # True=ECO, False=MAX, None=unknown

    # Power and lock state (promoted from IcecoStatus for entity access)
    power_on: Optional[bool] = None  # True=on, False=off, None=unknown
    locked: Optional[bool] = None    # True=locked, False=unlocked, None=unknown

    # Alarm timing tracking
    _left_alarm_start: Optional[datetime] = field(default=None, repr=False)
    _right_alarm_start: Optional[datetime] = field(default=None, repr=False)


class IcecoDataUpdateCoordinator(DataUpdateCoordinator[IcecoData]):
    """Coordinator for managing Iceco refrigerator BLE connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        ble_device: BLEDevice,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

        self._ble_device = ble_device
        self._entry = entry
        self._client: Optional[BleakClientWithServiceCache] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_count = 0
        # True whenever *we* initiated the current disconnect (manual disconnect,
        # shutdown, stale-connection recovery). Tells _handle_disconnect not to
        # auto-reconnect and prevents disconnect callbacks from racing a reconnect.
        self._expected_disconnect = False
        # Set once during async_shutdown — permanently disables all reconnect paths.
        self._shutting_down = False
        # Serialises connect/disconnect so overlapping callers can never open two links.
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()  # Serialise BLE writes to prevent concurrent GATT ops
        self._bluetooth_unregister: Optional[callable] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._keepalive_char: Optional[str] = None
        # Last time we had ANY proof the fridge is reachable — a status frame or a
        # successful keepalive read. Distinct from data.last_update (frames only):
        # the fridge stops streaming when idle at temperature, but the link is
        # still fine, so connection-health checks must key off this, not frames.
        self._link_alive_at: Optional[datetime] = None


        # Event set on first received notification - used to verify data is flowing after connect
        self._first_notification_event = asyncio.Event()

        # Initialize data
        self.data = IcecoData()

    @property
    def _options(self) -> dict:
        """Get current options from config entry."""
        return self._entry.options

    async def _async_setup(self) -> None:
        """Set up the coordinator - called once on entry setup."""
        # Track the device with HA's bluetooth manager so we always connect with a
        # fresh BLEDevice and can recover when the fridge reappears after being
        # out of range or after a failed reconnect.
        self._bluetooth_unregister = bluetooth.async_register_callback(
            self.hass,
            self._async_bluetooth_event,
            bluetooth.BluetoothCallbackMatcher(
                address=self._ble_device.address, connectable=True
            ),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        await self._async_connect()

    @callback
    def _async_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Handle the fridge being seen by an adapter/proxy."""
        # Always keep the freshest BLEDevice for the next connection attempt.
        self._ble_device = service_info.device

        if self._shutting_down or self._expected_disconnect:
            return

        # We've been advertised but aren't connected and nothing is retrying —
        # kick a reconnect now instead of waiting for the backoff/health check.
        if self.data.connection_state != "connected" and (
            self._reconnect_task is None or self._reconnect_task.done()
        ):
            self._reconnect_count = 0
            self._reconnect_task = self.hass.async_create_task(
                self._schedule_reconnect()
            )

    async def _async_connect(self) -> None:
        """Establish BLE connection to refrigerator."""
        if self._shutting_down:
            return

        async with self._connect_lock:
            if self._shutting_down or self._expected_disconnect:
                return
            # Another caller may have connected while we waited for the lock.
            if self._client is not None and self._client.is_connected:
                self.data.connection_state = "connected"
                return
            await self._async_connect_locked()

    async def _async_connect_locked(self) -> None:
        """Establish the BLE connection. Caller must hold self._connect_lock."""
        try:
            _LOGGER.debug("Attempting to connect to %s", self._ble_device.address)
            self.data.connection_state = "connecting"
            self._expected_disconnect = False

            # Reset notification event before connecting so we can verify data flows after
            self._first_notification_event.clear()

            # Close any dangling connection this host still holds to the fridge
            # (e.g. a half-open link leaked by a previous failed attempt) so we
            # don't stack connections or exhaust adapter slots.
            await close_stale_connections(self._ble_device)

            # Use bleak-retry-connector for reliable connection.
            # Service cache is disabled: a stale cache causes "Characteristic not found"
            # errors after HA restarts or device power cycles, requiring multiple retries
            # or a power cycle to recover. Fresh GATT service discovery on every connection
            # is slightly slower but eliminates this failure mode.
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._ble_device.address,
                disconnected_callback=self._handle_disconnect,
                use_services_cache=False,
                ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                    self.hass, self._ble_device.address, connectable=True
                ),
            )

            self._log_gatt_table()
            self._keepalive_char = self._pick_keepalive_char()

            # Subscribe to status notifications from characteristic FFF4
            await self._client.start_notify(
                IcecoProtocol.NOTIFY_UUID, self._notification_callback
            )
            _LOGGER.debug(
                "start_notify on %s OK; keepalive=%s char=%s",
                IcecoProtocol.NOTIFY_UUID,
                KEEPALIVE_MODE,
                self._keepalive_char,
            )

            # Mark connected right away and start the keepalive. We used to require
            # the first notification here and fail setup otherwise, but that turns a
            # marginal link into a retry storm. Instead: complete setup, keep the
            # link alive, and let entities populate when data arrives.
            self.data.connection_state = "connected"
            self._reconnect_count = 0
            self._link_alive_at = dt_util.utcnow()
            self._start_keepalive()
            _LOGGER.info("Connected to Iceco refrigerator at %s", self._ble_device.address)

            # Give the fridge a short window to send its first frame so entities
            # aren't blank on startup — but don't fail if it doesn't.
            try:
                await asyncio.wait_for(
                    self._first_notification_event.wait(),
                    timeout=FIRST_NOTIFICATION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "No notification within %ss of connecting to %s — link is up, "
                    "waiting for the fridge to stream (is the Iceco app still connected?)",
                    FIRST_NOTIFICATION_TIMEOUT,
                    self._ble_device.address,
                )

        except Exception as err:
            _LOGGER.error("Failed to connect to refrigerator: %s", err)
            # establish_connection() may already have opened the link before a
            # later step (start_notify) failed. Release it so we never leave a
            # subscribed-but-unused connection holding an adapter slot and
            # blocking the mobile app.
            self._stop_keepalive()
            client = self._client
            self._client = None
            if client is not None:
                try:
                    await client.disconnect()
                except Exception as disc_err:  # noqa: BLE001
                    _LOGGER.debug("Error releasing failed connection: %s", disc_err)
            self.data.connection_state = "disconnected"
            # Don't schedule reconnect here - just fail and let HA retry
            raise UpdateFailed(f"Failed to connect: {err}")

    def _log_gatt_table(self) -> None:
        """Dump the discovered GATT table at debug level (once per connect)."""
        if self._client is None:
            return
        for svc in self._client.services:
            for ch in svc.characteristics:
                _LOGGER.debug(
                    "GATT service %s char %s props=%s handle=%s",
                    svc.uuid, ch.uuid, ",".join(ch.properties), ch.handle,
                )

    def _pick_keepalive_char(self) -> Optional[str]:
        """Choose a readable characteristic to poll as a keepalive."""
        if self._client is None:
            return None
        readable = [
            ch.uuid
            for svc in self._client.services
            for ch in svc.characteristics
            if "read" in ch.properties
        ]
        # Prefer something in the Iceco vendor service.
        for uuid in readable:
            if uuid.lower().startswith("0000fff"):
                return uuid
        return readable[0] if readable else None

    def _start_keepalive(self) -> None:
        self._stop_keepalive()
        if KEEPALIVE_MODE != "none":
            self._keepalive_task = self.hass.async_create_task(self._keepalive_loop())

    def _stop_keepalive(self) -> None:
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
        self._keepalive_task = None

    async def _keepalive_loop(self) -> None:
        """Poke the fridge periodically so it doesn't hang up on an idle link."""
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                client = self._client
                if client is None or not client.is_connected:
                    return
                try:
                    if KEEPALIVE_MODE == "read" and self._keepalive_char:
                        await client.read_gatt_char(self._keepalive_char)
                        self._link_alive_at = dt_util.utcnow()
                    elif KEEPALIVE_MODE == "write" and self.data.left_setpoint is not None:
                        async with self._write_lock:
                            await client.write_gatt_char(
                                IcecoProtocol.WRITE_UUID,
                                IcecoProtocol.set_left_temperature(self.data.left_setpoint),
                                response=False,
                            )
                        _LOGGER.debug("keepalive write left setpoint %s", self.data.left_setpoint)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("keepalive error: %s", err)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _to_celsius(value: int, unit_mode: int) -> int:
        """Convert a temperature reading to °C. unit_mode: 1=°C, 2=°F."""
        if unit_mode == 2:
            return round((value - 32) * 5 / 9)
        return value

    def _notification_callback(self, sender: int, data: bytes) -> None:
        """Handle incoming BLE notifications."""
        _LOGGER.debug("Notification from %s: %r", sender, data)
        # Signal that notifications are flowing (verifies connection quality on startup)
        self._first_notification_event.set()
        self._link_alive_at = dt_util.utcnow()

        # Newer firmware sends one unified frame carrying everything.
        full = IcecoProtocol.parse_full_status(data)
        if full:
            self._handle_full_status(full)
            return

        # Try parsing as PRIMARY notification (setpoints + battery/power status)
        status = IcecoProtocol.parse_notification(data)

        if status:
            # PRIMARY always in °C — store directly.
            self.data.status = status
            self.data.left_setpoint = status.left_temp
            self.data.right_setpoint = status.right_temp
            self.data.power_on = status.power_on
            self.data.locked = status.locked
            self.data.last_update = dt_util.utcnow()
            self.data.power_loss_alarm = False

            self._check_temperature_alarms()
            self.async_set_updated_data(self.data)
        else:
            # Try parsing as SECONDARY notification (current temperatures in fridge's display unit)
            secondary = IcecoProtocol.parse_secondary_status(data)
            if secondary:
                unit_mode = secondary['unit_mode']
                left_temp = secondary['left_setpoint']
                right_temp = secondary['right_setpoint']

                # SECONDARY reports in fridge's display unit — convert to °C for storage.
                if unit_mode == 2:  # Fahrenheit
                    left_temp = round((left_temp - 32) * 5 / 9)
                    right_temp = round((right_temp - 32) * 5 / 9)
                # unit_mode == 1 is already °C

                self.data.left_current_temp = left_temp
                self.data.right_current_temp = right_temp
                self.data.unit_mode = "C" if unit_mode == 1 else "F"

                new_eco_mode = (secondary['eco_max'] == 1)  # 1=ECO, 0=MAX
                if new_eco_mode != self.data.eco_mode:
                    _LOGGER.info("ECO mode changed: raw eco_max=%d → eco_mode=%s", secondary['eco_max'], new_eco_mode)
                self.data.eco_mode = new_eco_mode

                self.async_set_updated_data(self.data)

    def _handle_full_status(self, full: dict) -> None:
        """Apply a decoded unified status frame to coordinator data."""
        unit_mode = full["unit_mode"]

        # The fridge streams frames whether or not the compressor is running, so
        # field 1 (power_on) carries the real display/compressor state. Lock state
        # has no known field yet.
        self.data.status = IcecoStatus(
            left_temp=full["left_setpoint"],
            right_temp=full["right_setpoint"],
            battery_protection_level=full["battery_protection_level"],
            battery_voltage=full["battery_voltage"],
            power_on=full["power_on"],
            locked=None,
        )
        self.data.left_setpoint = full["left_setpoint"]      # always °C
        self.data.right_setpoint = full["right_setpoint"]
        self.data.left_current_temp = self._to_celsius(full["left_current_temp"], unit_mode)
        self.data.right_current_temp = self._to_celsius(full["right_current_temp"], unit_mode)
        self.data.unit_mode = "C" if unit_mode == 1 else "F"
        self.data.power_on = full["power_on"]
        self.data.locked = None

        new_eco_mode = full["eco_on"]  # mode field: 1=ECO, 2=MAX
        if new_eco_mode != self.data.eco_mode:
            _LOGGER.info("Mode changed: %s", "ECO" if new_eco_mode else "MAX")
        self.data.eco_mode = new_eco_mode

        self.data.last_update = dt_util.utcnow()
        self.data.power_loss_alarm = False

        _LOGGER.debug(
            "Full status: setpoints L=%d R=%d °C | current L=%s R=%s °C | unit=%s "
            "power=%s mode=%s batt_prot=%d(1=L,3=H) voltage=%.1fV | f10/11=%s",
            self.data.left_setpoint,
            self.data.right_setpoint,
            self.data.left_current_temp,
            self.data.right_current_temp,
            self.data.unit_mode,
            "on" if full["power_on"] else "standby",
            "ECO" if new_eco_mode else "MAX",
            full["battery_protection_level"],
            full["battery_voltage"],
            full["unknown_fields"],
        )

        self._check_temperature_alarms()
        self.async_set_updated_data(self.data)

    def _check_temperature_alarms(self) -> None:
        """Check for temperature deviation alarms."""
        self.data.left_temp_alarm = self._check_zone_alarm("left")
        self.data.right_temp_alarm = self._check_zone_alarm("right")

    def _check_zone_alarm(self, zone: str) -> bool:
        """Check if specific zone should alarm."""
        # Get current temp (from SECONDARY) and setpoint (from PRIMARY)
        if zone == "left":
            actual = self.data.left_current_temp
            setpoint = self.data.left_setpoint
            alarm_start = self.data._left_alarm_start
        else:
            actual = self.data.right_current_temp
            setpoint = self.data.right_setpoint
            alarm_start = self.data._right_alarm_start

        # No alarm if no current temp or setpoint available
        if actual is None or setpoint is None:
            return False

        # Calculate deviation (in Fahrenheit)
        deviation = abs(actual - setpoint)
        threshold = self._options.get(
            CONF_TEMP_DEVIATION_THRESHOLD, DEFAULT_TEMP_DEVIATION_THRESHOLD
        )

        # Check if currently alarmed
        currently_alarmed = (
            self.data.left_temp_alarm if zone == "left" else self.data.right_temp_alarm
        )

        # Apply hysteresis when clearing alarm
        effective_threshold = threshold - ALARM_HYSTERESIS if currently_alarmed else threshold

        if deviation > effective_threshold:
            # Deviation detected
            if alarm_start is None:
                # Start tracking
                if zone == "left":
                    self.data._left_alarm_start = dt_util.utcnow()
                else:
                    self.data._right_alarm_start = dt_util.utcnow()
                return False  # Don't alarm immediately
            else:
                # Check if sustained long enough
                duration = dt_util.utcnow() - alarm_start
                duration_threshold = timedelta(
                    minutes=self._options.get(CONF_TEMP_DEVIATION_DURATION, DEFAULT_TEMP_DEVIATION_DURATION)
                )
                return duration >= duration_threshold
        else:
            # Within threshold - reset alarm tracking
            if zone == "left":
                self.data._left_alarm_start = None
            else:
                self.data._right_alarm_start = None
            return False

    @callback
    def _handle_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Handle BLE disconnection."""
        # Ignore the callback for a connection we've already replaced.
        if client is not self._client:
            return

        self._stop_keepalive()
        self._client = None
        self.data.connection_state = "disconnected"
        self.async_set_updated_data(self.data)

        # Don't auto-reconnect when we asked for the disconnect or are unloading.
        if self._expected_disconnect or self._shutting_down:
            _LOGGER.debug("Expected disconnect from refrigerator")
            return

        _LOGGER.warning("Disconnected from refrigerator")
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_task(
                self._schedule_reconnect()
            )

    async def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff."""
        if self._shutting_down or self._expected_disconnect:
            return

        # Exponential backoff: 1s, 2s, 4s, 8s, ..., max 60s
        delay = min(2**self._reconnect_count, 60)
        self._reconnect_count += 1

        _LOGGER.info("Scheduling reconnection in %ds (attempt %d)", delay, self._reconnect_count)
        self.data.connection_state = "reconnecting"

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        if self._shutting_down or self._expected_disconnect:
            return

        try:
            await self._async_connect()
        except Exception as err:
            _LOGGER.error("Reconnection failed: %s", err)
            # Retry with a longer backoff until we succeed or are told to stop.
            if not self._shutting_down and not self._expected_disconnect:
                self._reconnect_task = self.hass.async_create_task(
                    self._schedule_reconnect()
                )

    async def _async_disconnect(self, *, expected: bool) -> None:
        """Tear down the BLE connection through a single code path.

        Setting ``expected`` suppresses auto-reconnect (manual disconnect,
        shutdown, stale-connection recovery all pass ``expected=True``).
        """
        self._expected_disconnect = expected

        task = self._reconnect_task
        self._reconnect_task = None
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        async with self._connect_lock:
            await self._async_disconnect_locked()

    async def _async_disconnect_locked(self) -> None:
        """Tear down the connection. Caller must hold self._connect_lock."""
        self._stop_keepalive()
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.disconnect()
                _LOGGER.info("Disconnected from refrigerator")
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error during disconnect: %s", err)

        # Drop any connection bleak-retry-connector is still holding for this host.
        try:
            await close_stale_connections(self._ble_device)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Error closing stale connections: %s", err)

        self.data.connection_state = "disconnected"

    def _ensure_reconnecting(self) -> None:
        """Start a reconnect task if the link is down and nothing is retrying."""
        if self._shutting_down:
            return
        self._expected_disconnect = False
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_task(self._schedule_reconnect())

    async def _async_update_data(self) -> IcecoData:
        """Periodic health check. Notifications carry the real data — this only
        watches connection liveness and the power-loss alarm."""
        now = dt_util.utcnow()
        power_loss_timeout = timedelta(
            minutes=self._options.get(CONF_POWER_LOSS_TIMEOUT, DEFAULT_POWER_LOSS_TIMEOUT)
        )

        # "Alive" = a status frame OR a successful keepalive read. The fridge keeps
        # streaming frames even in standby, so frames alone can go quiet only if
        # the link drops — the keepalive proves it every ~5s regardless.
        link_age = (now - self._link_alive_at) if self._link_alive_at else None

        # Power-loss alarm: we cannot reach the fridge at all (dead 12V battery,
        # unplugged, out of range) for the whole timeout window.
        prev_alarm = self.data.power_loss_alarm
        self.data.power_loss_alarm = link_age is not None and link_age > power_loss_timeout
        if prev_alarm != self.data.power_loss_alarm:
            _LOGGER.warning(
                "Power loss alarm %s (fridge unreachable for %s)",
                "TRIGGERED" if self.data.power_loss_alarm else "cleared",
                link_age,
            )

        # Connection health: only act if the KEEPALIVE has also gone quiet — that
        # means the link is genuinely dead, not just the fridge idling.
        stale_after = timedelta(seconds=max(30.0, KEEPALIVE_INTERVAL * 4))
        if self.data.connection_state == "connected" and (
            link_age is None or link_age > stale_after
        ):
            _LOGGER.warning(
                "Connection appears stale (no keepalive for %s), rebuilding", link_age
            )
            try:
                async with asyncio.timeout(60):
                    await self._async_disconnect(expected=True)
                self._ensure_reconnecting()
            except TimeoutError:
                _LOGGER.error("Timed out tearing down stale connection")
                self._ensure_reconnecting()
        elif self.data.connection_state != "connected":
            self._ensure_reconnecting()

        return self.data

    async def async_set_left_temperature(self, temp: int) -> None:
        """Set the left/zone-1 setpoint (°C)."""
        await self.async_send_raw_command(IcecoProtocol.set_left_temperature(temp))
        self.data.left_setpoint = temp
        _LOGGER.info("Left zone setpoint → %d°C", temp)
        self.async_set_updated_data(self.data)

    async def async_set_right_temperature(self, temp: int) -> None:
        """Set the right/zone-2 setpoint (°C)."""
        await self.async_send_raw_command(IcecoProtocol.set_right_temperature(temp))
        self.data.right_setpoint = temp
        _LOGGER.info("Right zone setpoint → %d°C", temp)
        self.async_set_updated_data(self.data)

    async def async_set_power(self, on: bool) -> None:
        """Turn the fridge's display + compressor on or off (command S01).

        This does NOT affect the BLE module — the fridge keeps its BLE up and
        keeps streaming status frames while the compressor is off, as long as it
        has DC/AC power. So we stay connected either way.
        """
        await self.async_send_raw_command(IcecoProtocol.set_power(on))
        _LOGGER.info("Compressor power → %s", "on" if on else "off")
        # Optimistic; refined by the next status frame once we can read this state.
        self.data.power_on = on
        self.async_set_updated_data(self.data)

    async def async_send_raw_command(self, command: bytes) -> None:
        """Write a raw ASCII command to the fridge's write characteristic.

        Used by async_set_* and by the iceco.send_command debug service while
        the ECO / lock command ids for this firmware are still unknown.
        """
        if not self._client or not self._client.is_connected:
            raise HomeAssistantError("Not connected to refrigerator")
        try:
            async with self._write_lock:
                await self._client.write_gatt_char(
                    IcecoProtocol.WRITE_UUID, command, response=False
                )
            _LOGGER.info("Sent command %r", command)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to send command %r: %s", command, err)
            raise HomeAssistantError(f"Failed to send command: {err}") from err

    async def async_set_eco_mode(self, eco_on: bool) -> None:
        """Set ECO (True) or MAX (False) mode — command S06."""
        await self.async_send_raw_command(IcecoProtocol.set_eco_mode(eco_on))
        self.data.eco_mode = eco_on
        _LOGGER.info("Mode → %s", "ECO" if eco_on else "MAX")
        self.async_set_updated_data(self.data)

    async def async_set_battery_protection(self, level: int) -> None:
        """Set the battery-protection cut-off: 1 = Low, 2 = Medium, 3 = High (S04)."""
        await self.async_send_raw_command(IcecoProtocol.set_battery_protection(level))
        if self.data.status is not None:
            self.data.status.battery_protection_level = level
        _LOGGER.info("Battery protection → %d", level)
        self.async_set_updated_data(self.data)

    async def async_set_display_unit(self, celsius: bool) -> None:
        """Set the fridge's display unit: °C (True) or °F (False) — command S07."""
        await self.async_send_raw_command(IcecoProtocol.set_display_unit(celsius))
        self.data.unit_mode = "C" if celsius else "F"
        _LOGGER.info("Display unit → %s", self.data.unit_mode)
        self.async_set_updated_data(self.data)

    async def async_manual_disconnect(self) -> None:
        """Manually disconnect from refrigerator (for mobile app access)."""
        _LOGGER.info("Manual disconnect requested")
        await self._async_disconnect(expected=True)
        self.async_set_updated_data(self.data)

    async def async_manual_reconnect(self) -> None:
        """Manually reconnect to refrigerator."""
        _LOGGER.info("Manual reconnect requested")
        self._expected_disconnect = False
        self._reconnect_count = 0
        await self._async_connect()
        self.async_set_updated_data(self.data)

    async def async_shutdown(self) -> None:
        """Clean shutdown of coordinator — always releases the BLE connection."""
        self._shutting_down = True

        if self._bluetooth_unregister is not None:
            self._bluetooth_unregister()
            self._bluetooth_unregister = None

        await self._async_disconnect(expected=True)
