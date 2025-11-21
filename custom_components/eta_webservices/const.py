NAME = "eta_webservices"
DOMAIN = "eta_webservices"
ISSUE_URL = "https://github.com/Tidone/homeassistant_eta_integration/issues"


FLOAT_DICT = "FLOAT_DICT"
SWITCHES_DICT = "SWITCHES_DICT"
TEXT_DICT = "TEXT_DICT"
WRITABLE_DICT = "WRITABLE_DICT"
CHOSEN_FLOAT_SENSORS = "chosen_float_sensors"
CHOSEN_SWITCHES = "chosen_switches"
CHOSEN_TEXT_SENSORS = "chosen_text_sensors"
CHOSEN_WRITABLE_SENSORS = "chosen_writable_sensors"

FORCE_LEGACY_MODE = "force_legacy_mode"
ENABLE_DEBUG_LOGGING = "enable_debug_logging"

OPTIONS_UPDATE_SENSOR_VALUES = "update_sensor_values"
OPTIONS_ENUMERATE_NEW_ENDPOINTS = "enumerate_new_endpoints"
ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION = (
    "ignore_decimal_places_restriction_for_writable_entities"
)

ERROR_UPDATE_COORDINATOR = "error_update_coordinator"
WRITABLE_UPDATE_COORDINATOR = "writable_update_coordinator"

CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT = "minutes_since_midnight"
INVISIBLE_UNITS = [CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT]

# Defaults
DEFAULT_NAME = DOMAIN
REQUEST_TIMEOUT = 60

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
