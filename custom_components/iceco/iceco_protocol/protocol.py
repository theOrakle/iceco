"""
Iceco Refrigerator BLE Protocol Implementation

This module implements the command construction and notification parsing
for the Iceco refrigerator BLE protocol.

Protocol details:
- Service UUID: FFF0
- Commands: ASCII strings sent to characteristic FFF1
- Notifications: ASCII strings received from characteristic FFF4
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class IcecoStatus:
    """Represents the status parsed from PRIMARY notification.

    PRIMARY notification contains SETPOINTS (target temperatures) always in °C,
    plus battery and power state. Updates immediately when a setpoint command is
    accepted.
    """

    # Setpoint temperatures always in °C regardless of device display unit
    left_temp: int   # Left zone setpoint
    right_temp: int  # Right zone setpoint

    # Battery information
    battery_protection_level: int  # 1, 2, or 3
    battery_voltage: float  # Volts (e.g., 12.6)

    # Power and lock state (from PRIMARY field 5: 0=off, 1=on+unlocked, 2=on+locked)
    power_on: bool  # True if on (field 5 != 0)
    locked: bool    # True if control panel is locked (field 5 == 2)

    left_set_temp: Optional[int] = None
    right_set_temp: Optional[int] = None


class IcecoProtocol:
    """
    Handles command construction and notification parsing for Iceco protocol.

    Command format: /S<ID>/1/<Value>\n
    - S03: Left zone temperature
    - S05: Right zone temperature
    - S00: Power state toggle
    - S01: ECO/MAX mode toggle
    - S06: Lock/unlock toggle

    PRIMARY notification: ,<L_Setpoint>,<R_Setpoint>,<BattProtect>,<Voltage>,<PowerStatus>\n
    - Contains SETPOINTS in the fridge's native display unit (same unit as commands).
    - Updates immediately when a setpoint command is accepted by the fridge.

    SECONDARY notification: /S00/U/<zones>,<eco_max>,<unit_mode>,<L_Temp>,<R_Temp>\n
    - Contains CURRENT PHYSICAL TEMPERATURES in the fridge's display unit.
    - Also carries eco_max (1=ECO, 0=MAX) and unit_mode (1=°C, 2=°F).
    - Always reflects actual sensor readings — confirmed via hardware testing.
    """

    # BLE characteristics
    SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"  # Main service
    WRITE_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"    # Send commands
    NOTIFY_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"   # Receive status

    # Command IDs for the /S00/0L firmware, all verified on a VL PRO Dual Zone
    # (2026-08) by sending each and watching the status frame change:
    #   S01 power       001 = on,  000 = standby
    #   S03 left setpoint   signed °C   (/S03/1/+04, /S03/1/-18)
    #   S04 battery protect 001 = Low, 002 = Medium, 003 = High
    #   S05 right setpoint  signed °C
    #   S06 mode        001 = ECO, 002 = MAX
    #   S07 display unit 001 = °C,  002 = °F
    # (S00 carries the status frames; the APL35 ids S00 power / S01 ECO / S06 lock
    #  do NOT apply here.)
    CMD_POWER = "01"
    CMD_LEFT_TEMP = "03"
    CMD_BATTERY_PROTECTION = "04"
    CMD_RIGHT_TEMP = "05"
    CMD_MODE = "06"
    CMD_DISPLAY_UNIT = "07"
    CMD_POWER_APL35 = "00"    # APL35 power toggle (kept for reference)

    @staticmethod
    def build_command(command_id: str, value: str) -> bytes:
        """
        Build a command string for the refrigerator.

        Args:
            command_id: Command ID (e.g., "S03", "S05")
            value: Value to set (e.g., "-18", "004", "-01")

        Returns:
            ASCII-encoded bytes ready to send to characteristic FFF1
        """
        # Format: /S<ID>/1/<Value>\n
        command = f"/S{command_id}/1/{value}\n"
        return command.encode('ascii')

    @staticmethod
    def set_left_temperature(temp: int) -> bytes:
        """
        Build command to set left zone temperature.

        Args:
            temp: Temperature in fridge's configured unit (F or C)

        Returns:
            Command bytes
        """
        # Format temperature as 3 digits with leading zeros for positive, minus sign for negative
        if temp < 0:
            value = f"-{abs(temp):02d}"
        else:
            value = f"{temp:03d}"
        return IcecoProtocol.build_command(IcecoProtocol.CMD_LEFT_TEMP, value)

    @staticmethod
    def set_right_temperature(temp: int) -> bytes:
        """
        Build command to set right zone temperature.

        Args:
            temp: Temperature in fridge's configured unit (F or C)

        Returns:
            Command bytes
        """
        # Format temperature as 3 digits with leading zeros for positive, minus sign for negative
        if temp < 0:
            value = f"-{abs(temp):02d}"
        else:
            value = f"{temp:03d}"
        return IcecoProtocol.build_command(IcecoProtocol.CMD_RIGHT_TEMP, value)

    @staticmethod
    def set_power(on: bool) -> bytes:
        """Power on (/S01/1/001) or standby (/S01/1/000).

        After power-on the compressor starts after a short protection delay,
        not immediately.
        """
        return IcecoProtocol.build_command(
            IcecoProtocol.CMD_POWER, "001" if on else "000"
        )

    @staticmethod
    def toggle_power() -> bytes:
        """Legacy APL35 power toggle (/S00/1/-01). Unused on /S00/0L firmware."""
        return IcecoProtocol.build_command(IcecoProtocol.CMD_POWER_APL35, "-01")

    @staticmethod
    def set_eco_mode(eco_on: bool) -> bytes:
        """Mode: ECO (/S06/1/001) or MAX (/S06/1/002)."""
        return IcecoProtocol.build_command(
            IcecoProtocol.CMD_MODE, "001" if eco_on else "002"
        )

    @staticmethod
    def set_battery_protection(level: int) -> bytes:
        """Battery protection cut-off: 1 = Low, 2 = Medium, 3 = High (/S04/1/00X)."""
        if level not in (1, 2, 3):
            raise ValueError(f"battery protection level must be 1-3, got {level}")
        return IcecoProtocol.build_command(
            IcecoProtocol.CMD_BATTERY_PROTECTION, f"00{level}"
        )

    @staticmethod
    def set_display_unit(celsius: bool) -> bytes:
        """Fridge display unit: °C (/S07/1/001) or °F (/S07/1/002)."""
        return IcecoProtocol.build_command(
            IcecoProtocol.CMD_DISPLAY_UNIT, "001" if celsius else "002"
        )

    @staticmethod
    def parse_notification(data: bytes) -> Optional[IcecoStatus]:
        """
        Parse PRIMARY notification from the refrigerator.

        PRIMARY contains SETPOINTS in the fridge's native display unit, plus
        battery protection level, battery voltage, and power state.

        Args:
            data: Raw bytes from characteristic FFF4

        Returns:
            IcecoStatus with setpoints/battery/power if parsing succeeds, None otherwise
        """
        try:
            # Decode ASCII data
            message = data.decode('ascii').strip()

            # Check if this is a primary status notification
            # Format: ,<L_Setpoint_C>,<R_Setpoint_C>,<BattProtect>,<Voltage>,<PowerStatus>
            if message.startswith(','):
                parts = message[1:].split(',')
                if len(parts) == 5:
                    left_temp = int(parts[0])
                    right_temp = int(parts[1])
                    batt_protect = int(parts[2])
                    # Voltage is sent as integer (e.g., 126 = 12.6V)
                    voltage = int(parts[3]) / 10.0
                    power_status = int(parts[4])

                    return IcecoStatus(
                        left_temp=left_temp,
                        right_temp=right_temp,
                        battery_protection_level=batt_protect,
                        battery_voltage=voltage,
                        # power_status: 0=off, 1=on+unlocked, 2=on+locked
                        power_on=(power_status != 0),
                        locked=(power_status == 2)
                    )

            # Secondary status is parsed separately
            # Unknown notification format
            return None

        except (ValueError, UnicodeDecodeError, IndexError):
            # Parsing failed
            return None

    @staticmethod
    def parse_full_status(data: bytes) -> Optional[dict]:
        """Parse the unified status frame emitted by newer Iceco firmware.

        Format (characteristic FFF4)::

            /S00/0L/<f0>,<f1>,<f2>,<f3>,<f4>,<f5>,<f6>,<f7>,<f8>,<f9>,<f10>,<f11>

        This single frame carries everything the older firmware split across the
        PRIMARY (``,...``) and SECONDARY (``/S00/U/...``) notifications.

        Field mapping (confirmed against a live dual-zone unit by isolated
        single-variable changes, 2026-08):

        =====  ==================  ================================================
        idx    key                 notes
        =====  ==================  ================================================
        0      zone_count          2 = dual zone
        1      power_on            CONFIRMED 1 = display + compressor on,
                                   0 = standby. (Isolated by toggling it live.)
        2      unit_mode           1 = °C, 2 = °F (display unit for f3/f4)
        3      left_current_temp   CONFIRMED, in ``unit_mode``
        4      right_current_temp  CONFIRMED, in ``unit_mode``
        5      left_setpoint       CONFIRMED, always °C
        6      right_setpoint      CONFIRMED, always °C
        7      battery_protection  CONFIRMED 1 = L, 2 = M, 3 = H
        8      battery_voltage_raw CONFIRMED input voltage x10 (12.7 on a 12 V
                                   pack, ~26.8 on the AC adapter)
        9      mode                CONFIRMED 1 = ECO, 2 = MAX (0 presumably off,
                                   never seen — the fridge only streams while on)
        10     f10                 UNKNOWN — constant 0 across MAX/ECO, all battery
                                   levels, cooling/at-temp, AC/battery (fault code?)
        11     f11                 UNKNOWN — constant 000 in the same tests
        =====  ==================  ================================================

        Returns a dict, or ``None`` if the frame isn't this type / can't parse.
        """
        try:
            message = data.decode("ascii").strip()
        except UnicodeDecodeError:
            return None

        if not message.startswith("/S00/0L/"):
            return None

        try:
            payload = message.split("/", 3)[3]  # everything after "/S00/0L/"
            parts = payload.split(",")
            if len(parts) < 10:
                return None

            mode = int(parts[9])
            return {
                "zone_count": int(parts[0]),
                "power_on": parts[1] == "1",
                "unit_mode": int(parts[2]),  # 1=C, 2=F
                "left_current_temp": int(parts[3]),
                "right_current_temp": int(parts[4]),
                "left_setpoint": int(parts[5]),
                "right_setpoint": int(parts[6]),
                "battery_protection_level": int(parts[7]),  # 1=L 2=M 3=H
                "battery_voltage": int(parts[8]) / 10.0,
                "mode": mode,  # 1=ECO, 2=MAX
                "eco_on": mode == 1,
                # f10/f11 still unidentified — keep raw, don't act on them
                "unknown_fields": parts[10:],
            }
        except (ValueError, IndexError):
            return None

    @staticmethod
    def parse_secondary_status(data: bytes) -> Optional[dict]:
        """
        Parse secondary status notification to extract current temperatures.

        SECONDARY contains CURRENT PHYSICAL TEMPERATURES in the fridge's display unit,
        plus eco mode and unit mode. Always reflects actual sensor readings — confirmed
        via hardware testing. No echo behavior.

        Args:
            data: Raw bytes from characteristic FFF4

        Returns:
            Dict with 'left_setpoint', 'right_setpoint', 'eco_max', 'unit_mode', 'zone_count'
            (keys use 'setpoint' naming for legacy reasons — these are actual current temps)
            unit_mode: 1 = Celsius, 2 = Fahrenheit
            eco_max: 1 = ECO mode, 0 = MAX mode
            zone_count: from /S00/U/X field (2 = dual-zone)
        """
        try:
            message = data.decode('ascii').strip()

            # Format: /S00/U/<zone_count>,<eco_max>,<unit_mode>,<L_Temp>,<R_Temp>
            if message.startswith('/S00/U/'):
                # Extract zone count from the header (e.g., /S00/U/2)
                header_end = message.index(',')
                header = message[:header_end]  # e.g., "/S00/U/2"
                zone_count = int(header.split('/')[-1])  # Extract the "2"

                parts = message.split(',')
                if len(parts) >= 5:
                    eco_max = int(parts[1])  # 1=ECO, 0=MAX
                    unit_mode = int(parts[2])  # 1=C, 2=F
                    left_setpoint = int(parts[3])
                    right_setpoint = int(parts[4])
                    return {
                        'left_setpoint': left_setpoint,
                        'right_setpoint': right_setpoint,
                        'unit_mode': unit_mode,
                        'zone_count': zone_count,
                        'eco_max': eco_max,
                    }

            return None

        except (ValueError, UnicodeDecodeError, IndexError):
            return None
