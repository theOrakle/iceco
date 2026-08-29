"""Constants for Iceco integration."""

DOMAIN = "iceco"

# BLE identity
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
# Manufacturer ID (0xAFF2) present in Iceco advertisements. The bare FFF0 service
# UUID is a generic placeholder shared by many unrelated cheap BLE devices, so
# discovery also requires this manufacturer ID. Observed on an APL-series unit —
# widen this check if other models advertise differently.
ICECO_MANUFACTURER_ID = 45042

# Configuration keys
CONF_DEVICE_ADDRESS = "device_address"

# Options keys (user-configurable)
CONF_POLL_INTERVAL = "poll_interval"
CONF_POWER_LOSS_TIMEOUT = "power_loss_timeout"
CONF_TEMP_DEVIATION_THRESHOLD = "temp_deviation_threshold"
CONF_TEMP_DEVIATION_DURATION = "temp_deviation_duration"

# Default values
DEFAULT_POLL_INTERVAL = 60  # seconds
DEFAULT_POWER_LOSS_TIMEOUT = 15  # minutes (lowered from 30 for faster alerts)
DEFAULT_TEMP_DEVIATION_THRESHOLD = 5  # degrees Celsius
DEFAULT_TEMP_DEVIATION_DURATION = 5  # minutes (lowered from 15 for faster alerts)

# Validation ranges
MIN_POLL_INTERVAL = 30
MAX_POLL_INTERVAL = 300
MIN_POWER_LOSS_TIMEOUT = 10
MAX_POWER_LOSS_TIMEOUT = 120
MIN_TEMP_DEVIATION_THRESHOLD = 1
MAX_TEMP_DEVIATION_THRESHOLD = 10
MIN_TEMP_DEVIATION_DURATION = 5
MAX_TEMP_DEVIATION_DURATION = 60

# Entity unique ID suffixes
ENTITY_CLIMATE_LEFT = "climate_left"
ENTITY_CLIMATE_RIGHT = "climate_right"
ENTITY_BATTERY_VOLTAGE = "battery_voltage"
ENTITY_BATTERY_PROTECTION = "battery_protection"
ENTITY_LOW_BATTERY = "low_battery"

# Battery protection level (frame field 7): 1 = Low, 2 = Medium, 3 = High cutoff
BATTERY_PROTECTION_LEVELS = {1: "L", 2: "M", 3: "H"}

# Compressor cut-out / cut-in voltages per protection level, from the VL PRO
# manual. {level: {"12V": (cut_out, cut_in), "24V": (cut_out, cut_in)}}
BATTERY_PROTECTION_VOLTAGES = {
    1: {"12V": (9.6, 10.9), "24V": (21.3, 22.7)},   # LOW
    2: {"12V": (10.1, 11.4), "24V": (22.3, 23.7)},  # MED
    3: {"12V": (11.1, 12.4), "24V": (24.3, 25.7)},  # HIGH
}
# Below this measured voltage the fridge is on a 12 V supply, otherwise 24 V.
SYSTEM_VOLTAGE_SPLIT = 17.0


def battery_thresholds(level: int | None, voltage: float | None):
    """Return (system, cut_out, cut_in) for the given protection level / reading."""
    if level not in BATTERY_PROTECTION_VOLTAGES or voltage is None:
        return None, None, None
    system = "12V" if voltage < SYSTEM_VOLTAGE_SPLIT else "24V"
    cut_out, cut_in = BATTERY_PROTECTION_VOLTAGES[level][system]
    return system, cut_out, cut_in
ENTITY_POWER_LOSS_ALARM = "power_loss_alarm"
ENTITY_TEMP_ALARM_LEFT = "temp_alarm_left"
ENTITY_TEMP_ALARM_RIGHT = "temp_alarm_right"
ENTITY_POWER_SWITCH = "power_switch"
ENTITY_ECO_MODE = "eco_mode"
ENTITY_LOCK = "lock"
ENTITY_CONNECTION = "connection"
ENTITY_DISPLAY_UNIT = "display_unit"

# Select option labels (verified command values for the /S00/0L firmware)
MODE_OPTIONS = ("ECO", "MAX")                       # S06: 001=ECO, 002=MAX
BATTERY_PROTECTION_OPTIONS = ("Low", "Medium", "High")  # S04: 001/002/003
DISPLAY_UNIT_OPTIONS = ("°C", "°F")                 # S07: 001=°C, 002=°F

# Attribute keys
ATTR_BATTERY_PROTECTION_LEVEL = "battery_protection_level"
ATTR_LAST_UPDATE = "last_update"
ATTR_CONNECTION_STATE = "connection_state"
ATTR_SET_TEMPERATURE = "set_temperature"
ATTR_CURRENT_TEMPERATURE = "current_temperature"
ATTR_DEVIATION = "deviation"
ATTR_THRESHOLD = "threshold"
ATTR_TIMEOUT_MINUTES = "timeout_minutes"

# Temperature limits (Celsius — HA auto-converts for display)
MIN_TEMP = -22  # °C
MAX_TEMP = 10   # °C
TEMP_STEP = 1

# Hysteresis for alarm clearing (degrees Celsius)
ALARM_HYSTERESIS = 2
