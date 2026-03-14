"""Constants for Room Climate integration."""

DOMAIN = "room_climate"

# Config flow keys
CONF_TADO_ENTITY = "tado_entity"
CONF_AC_ENTITY = "ac_entity"
CONF_TEMP_SENSOR = "temp_sensor"
CONF_WINDOW_SENSOR = "window_sensor"
CONF_CALIBRATION_MODE = "calibration_mode"
CONF_WINDOW_OPEN_DELAY = "window_open_delay"
CONF_WINDOW_CLOSE_DELAY = "window_close_delay"
CONF_ADDITIONAL_TRVS = "additional_trvs"
CONF_COMFORT_TEMP = "comfort_temp"
CONF_ECO_TEMP = "eco_temp"

# Calibration
CALIBRATION_NORMAL = "normal"
CALIBRATION_AGGRESSIVE = "aggressive"
CALIBRATION_MODES = [CALIBRATION_NORMAL, CALIBRATION_AGGRESSIVE]
AGGRESSIVE_MULTIPLIER = 1.5

# Defaults
DEFAULT_WINDOW_OPEN_DELAY = 30
DEFAULT_WINDOW_CLOSE_DELAY = 5
DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 35.0
DEFAULT_TEMP_STEP = 0.5
DEFAULT_TARGET_TEMP = 20.0

# Boost: drives TRV setpoint to max to open valve fully
BOOST_SETPOINT = 25.0

# Dry mode AC setpoint
DRY_MODE_TEMP = 16.0

# Preset temperature defaults (fixed comfort/eco)
DEFAULT_COMFORT_TEMP = 20.0
DEFAULT_ECO_TEMP = 17.0

# Preset mode names (Comfort and Eco only; boost is a separate setting)
PRESET_COMFORT = "comfort"
PRESET_ECO = "eco"
PRESET_MODES = [PRESET_COMFORT, PRESET_ECO]

# Fan mode fallback when AC doesn't report its own modes
FAN_AUTO = "auto"
FAN_LOW = "low"
FAN_MEDIUM = "medium"
FAN_HIGH = "high"
DEFAULT_FAN_MODES = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
