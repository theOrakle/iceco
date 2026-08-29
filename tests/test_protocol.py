"""Tests for IcecoProtocol command builders and notification parsers.

No Home Assistant dependencies — pure protocol logic only.
"""

from __future__ import annotations

import pytest

from custom_components.iceco.const import battery_thresholds
from custom_components.iceco.iceco_protocol.protocol import IcecoProtocol, IcecoStatus


# ---------------------------------------------------------------------------
# Command builder tests
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_format(self):
        result = IcecoProtocol.build_command("03", "-18")
        assert result == b"/S03/1/-18\n"

    def test_returns_bytes(self):
        result = IcecoProtocol.build_command("00", "-01")
        assert isinstance(result, bytes)

    def test_ascii_encoding(self):
        result = IcecoProtocol.build_command("05", "010")
        result.decode("ascii")  # should not raise


class TestSetTemperature:
    def test_negative_temperature_left(self):
        # -18°C should format as "-18"
        assert IcecoProtocol.set_left_temperature(-18) == b"/S03/1/-18\n"

    def test_negative_single_digit_left(self):
        # -5°C should format as "-05"
        assert IcecoProtocol.set_left_temperature(-5) == b"/S03/1/-05\n"

    def test_positive_temperature_left(self):
        # 4°C should format as "004"
        assert IcecoProtocol.set_left_temperature(4) == b"/S03/1/004\n"

    def test_zero_temperature_left(self):
        assert IcecoProtocol.set_left_temperature(0) == b"/S03/1/000\n"

    def test_max_temperature_left(self):
        # 10°C (MAX_TEMP) should format as "010"
        assert IcecoProtocol.set_left_temperature(10) == b"/S03/1/010\n"

    def test_min_temperature_left(self):
        # -22°C (MIN_TEMP) should format as "-22"
        assert IcecoProtocol.set_left_temperature(-22) == b"/S03/1/-22\n"

    def test_negative_temperature_right(self):
        assert IcecoProtocol.set_right_temperature(-15) == b"/S05/1/-15\n"

    def test_positive_temperature_right(self):
        assert IcecoProtocol.set_right_temperature(4) == b"/S05/1/004\n"

    def test_left_uses_s03(self):
        cmd = IcecoProtocol.set_left_temperature(-10)
        assert b"/S03/" in cmd

    def test_right_uses_s05(self):
        cmd = IcecoProtocol.set_right_temperature(-10)
        assert b"/S05/" in cmd


class TestSetPower:
    def test_on(self):
        assert IcecoProtocol.set_power(True) == b"/S01/1/001\n"

    def test_off(self):
        assert IcecoProtocol.set_power(False) == b"/S01/1/000\n"


class TestTogglePower:
    def test_legacy_apl35_format(self):
        assert IcecoProtocol.toggle_power() == b"/S00/1/-01\n"


class TestSetEcoMode:
    def test_eco(self):
        assert IcecoProtocol.set_eco_mode(True) == b"/S06/1/001\n"

    def test_max(self):
        assert IcecoProtocol.set_eco_mode(False) == b"/S06/1/002\n"


class TestSetBatteryProtection:
    def test_levels(self):
        assert IcecoProtocol.set_battery_protection(1) == b"/S04/1/001\n"
        assert IcecoProtocol.set_battery_protection(2) == b"/S04/1/002\n"
        assert IcecoProtocol.set_battery_protection(3) == b"/S04/1/003\n"

    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            IcecoProtocol.set_battery_protection(0)


class TestSetDisplayUnit:
    def test_celsius(self):
        assert IcecoProtocol.set_display_unit(True) == b"/S07/1/001\n"

    def test_fahrenheit(self):
        assert IcecoProtocol.set_display_unit(False) == b"/S07/1/002\n"


# ---------------------------------------------------------------------------
# PRIMARY notification parser tests
# ---------------------------------------------------------------------------


# Valid PRIMARY: ,<L_setpoint>,<R_setpoint>,<batt_protect>,<voltage_x10>,<power_status>
PRIMARY_BASIC = b",-18,-15,1,126,1\n"
PRIMARY_LOCKED = b",-18,-15,1,126,2\n"
PRIMARY_OFF = b",-18,-15,1,126,0\n"
PRIMARY_POSITIVE = b",4,0,2,130,1\n"


class TestParseNotification:
    def test_returns_iceco_status(self):
        result = IcecoProtocol.parse_notification(PRIMARY_BASIC)
        assert isinstance(result, IcecoStatus)

    def test_left_setpoint(self):
        result = IcecoProtocol.parse_notification(PRIMARY_BASIC)
        assert result.left_temp == -18

    def test_right_setpoint(self):
        result = IcecoProtocol.parse_notification(PRIMARY_BASIC)
        assert result.right_temp == -15

    def test_battery_protection_level(self):
        result = IcecoProtocol.parse_notification(PRIMARY_BASIC)
        assert result.battery_protection_level == 1

    def test_battery_voltage(self):
        # 126 → 12.6V
        result = IcecoProtocol.parse_notification(PRIMARY_BASIC)
        assert result.battery_voltage == pytest.approx(12.6)

    def test_power_status_1_is_on_and_unlocked(self):
        result = IcecoProtocol.parse_notification(PRIMARY_BASIC)
        assert result.power_on is True
        assert result.locked is False

    def test_power_status_2_is_on_and_locked(self):
        result = IcecoProtocol.parse_notification(PRIMARY_LOCKED)
        assert result.power_on is True
        assert result.locked is True

    def test_power_status_0_is_off(self):
        result = IcecoProtocol.parse_notification(PRIMARY_OFF)
        assert result.power_on is False
        assert result.locked is False

    def test_positive_setpoints(self):
        result = IcecoProtocol.parse_notification(PRIMARY_POSITIVE)
        assert result.left_temp == 4
        assert result.right_temp == 0

    def test_returns_none_for_secondary(self):
        result = IcecoProtocol.parse_notification(b"/S00/U/2,1,1,-15,-12\n")
        assert result is None

    def test_returns_none_for_wrong_field_count(self):
        result = IcecoProtocol.parse_notification(b",-18,-15,1,126\n")  # only 4 fields
        assert result is None

    def test_returns_none_for_non_ascii(self):
        result = IcecoProtocol.parse_notification(b"\xff\xfe\xfd")
        assert result is None

    def test_returns_none_for_malformed_integers(self):
        result = IcecoProtocol.parse_notification(b",-18,abc,1,126,1\n")
        assert result is None

    def test_returns_none_for_empty(self):
        result = IcecoProtocol.parse_notification(b"")
        assert result is None


# ---------------------------------------------------------------------------
# SECONDARY notification parser tests
# ---------------------------------------------------------------------------


# Valid SECONDARY: /S00/U/<zones>,<eco_max>,<unit_mode>,<L_temp>,<R_temp>
SECONDARY_CELSIUS = b"/S00/U/2,1,1,-15,-12\n"   # ECO on, Celsius
SECONDARY_FAHRENHEIT = b"/S00/U/2,0,2,14,32\n"   # MAX mode, Fahrenheit
SECONDARY_SINGLE_ZONE = b"/S00/U/1,0,1,-10,-10\n"


class TestParseSecondaryStatus:
    def test_returns_dict(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_CELSIUS)
        assert isinstance(result, dict)

    def test_left_temp_celsius(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_CELSIUS)
        assert result["left_setpoint"] == -15

    def test_right_temp_celsius(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_CELSIUS)
        assert result["right_setpoint"] == -12

    def test_unit_mode_celsius(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_CELSIUS)
        assert result["unit_mode"] == 1

    def test_unit_mode_fahrenheit(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_FAHRENHEIT)
        assert result["unit_mode"] == 2

    def test_eco_max_1_means_eco_on(self):
        # eco_max=1 in SECONDARY means ECO mode is active
        result = IcecoProtocol.parse_secondary_status(SECONDARY_CELSIUS)
        assert result["eco_max"] == 1

    def test_eco_max_0_means_max_mode(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_FAHRENHEIT)
        assert result["eco_max"] == 0

    def test_zone_count_dual(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_CELSIUS)
        assert result["zone_count"] == 2

    def test_zone_count_single(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_SINGLE_ZONE)
        assert result["zone_count"] == 1

    def test_fahrenheit_temps(self):
        result = IcecoProtocol.parse_secondary_status(SECONDARY_FAHRENHEIT)
        assert result["left_setpoint"] == 14
        assert result["right_setpoint"] == 32

    def test_returns_none_for_primary(self):
        result = IcecoProtocol.parse_secondary_status(b",-18,-15,1,126,1\n")
        assert result is None

    def test_returns_none_for_wrong_prefix(self):
        result = IcecoProtocol.parse_secondary_status(b"/S01/U/2,1,1,-15,-12\n")
        assert result is None

    def test_returns_none_for_too_few_fields(self):
        result = IcecoProtocol.parse_secondary_status(b"/S00/U/2,1,1,-15\n")  # missing right
        assert result is None

    def test_returns_none_for_non_ascii(self):
        result = IcecoProtocol.parse_secondary_status(b"\xff\xfe")
        assert result is None

    def test_returns_none_for_empty(self):
        result = IcecoProtocol.parse_secondary_status(b"")
        assert result is None


# ---------------------------------------------------------------------------
# parse_full_status — unified /S00/0L/ frame (newer firmware)
# ---------------------------------------------------------------------------

# Real captures from a live dual-zone unit, cross-checked against the fridge
# panel by isolated single-variable changes (2026-08):
FULL_STANDBY_MAX = b"/S00/0L/2,0,2,+76,+76,+03,-12,3,267,2,0,000\n"  # standby, MAX, batt H, AC
FULL_ON_ECO = b"/S00/0L/2,1,2,+37,+50,+03,-12,3,268,1,0,000\n"       # on, ECO, batt H
FULL_ON_MAX_BATT_L = b"/S00/0L/2,1,2,+37,+10,+03,-12,1,269,2,0,000\n"  # on, MAX, batt L


class TestParseFullStatus:
    def test_mode_field(self):
        assert IcecoProtocol.parse_full_status(FULL_STANDBY_MAX)["mode"] == 2  # MAX
        assert IcecoProtocol.parse_full_status(FULL_ON_ECO)["mode"] == 1       # ECO
        assert IcecoProtocol.parse_full_status(FULL_ON_MAX_BATT_L)["mode"] == 2

    def test_eco_on_derived_from_mode(self):
        assert IcecoProtocol.parse_full_status(FULL_ON_ECO)["eco_on"] is True
        assert IcecoProtocol.parse_full_status(FULL_ON_MAX_BATT_L)["eco_on"] is False

    def test_power_on_flag(self):
        assert IcecoProtocol.parse_full_status(FULL_STANDBY_MAX)["power_on"] is False
        assert IcecoProtocol.parse_full_status(FULL_ON_ECO)["power_on"] is True

    def test_unit_mode_fahrenheit(self):
        assert IcecoProtocol.parse_full_status(FULL_STANDBY_MAX)["unit_mode"] == 2

    def test_current_temps_raw_in_display_unit(self):
        r = IcecoProtocol.parse_full_status(FULL_ON_ECO)
        assert r["left_current_temp"] == 37
        assert r["right_current_temp"] == 50

    def test_setpoints_are_celsius(self):
        r = IcecoProtocol.parse_full_status(FULL_STANDBY_MAX)
        assert r["left_setpoint"] == 3     # 37 °F
        assert r["right_setpoint"] == -12  # 10 °F

    def test_battery_protection_level(self):
        assert IcecoProtocol.parse_full_status(FULL_ON_ECO)["battery_protection_level"] == 3  # H
        assert IcecoProtocol.parse_full_status(FULL_ON_MAX_BATT_L)["battery_protection_level"] == 1  # L

    def test_battery_voltage_scale(self):
        assert IcecoProtocol.parse_full_status(FULL_ON_ECO)["battery_voltage"] == 26.8

    def test_unknown_fields_kept_raw(self):
        assert IcecoProtocol.parse_full_status(FULL_STANDBY_MAX)["unknown_fields"] == ["0", "000"]

    def test_returns_none_for_other_formats(self):
        assert IcecoProtocol.parse_full_status(b",-18,-15,1,126,1\n") is None
        assert IcecoProtocol.parse_full_status(b"/S00/U/2,1,2,14,32\n") is None
        assert IcecoProtocol.parse_full_status(b"\xff\xfe") is None
        assert IcecoProtocol.parse_full_status(b"") is None

    def test_returns_none_for_truncated_frame(self):
        assert IcecoProtocol.parse_full_status(b"/S00/0L/2,1,2,+37\n") is None


# ---------------------------------------------------------------------------
# battery_thresholds helper (const.py)
# ---------------------------------------------------------------------------


class TestBatteryThresholds:
    def test_12v_low(self):
        assert battery_thresholds(1, 12.7) == ("12V", 9.6, 10.9)

    def test_12v_high(self):
        assert battery_thresholds(3, 13.3) == ("12V", 11.1, 12.4)

    def test_24v_detected_from_voltage(self):
        assert battery_thresholds(2, 25.0) == ("24V", 22.3, 23.7)

    def test_unknown_level(self):
        assert battery_thresholds(0, 12.0) == (None, None, None)
        assert battery_thresholds(None, 12.0) == (None, None, None)

    def test_no_voltage(self):
        assert battery_thresholds(1, None) == (None, None, None)
