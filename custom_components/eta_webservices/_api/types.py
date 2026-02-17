"""Type definitions for ETA API."""

from datetime import datetime
from typing import TypedDict

from ..const import (  # noqa: TID252
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
    CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
    CUSTOM_UNIT_UNITLESS,
)


class ETAValidSwitchValues(TypedDict):
    """Dict providing the raw values for ETA switch sensors."""

    on_value: int
    off_value: int


class ETAValidWritableValues(TypedDict):
    """Dict providing the necessary metadata for ETA writable sensors."""

    scaled_min_value: float
    scaled_max_value: float
    scale_factor: int
    dec_places: int


class ETAEndpoint(TypedDict):
    """Dict providing metadata for a ETA sensor."""

    url: str
    value: float | str
    valid_values: dict | ETAValidSwitchValues | ETAValidWritableValues | None
    friendly_name: str
    unit: str
    endpoint_type: str


class ETAError(TypedDict):
    """Dict encapsulating all available data of an ETA Error."""

    msg: str
    priority: str
    time: datetime
    text: str
    fub: str
    host: str
    port: int


# Sensor unit constants
FLOAT_SENSOR_UNITS = [
    "%",
    "A",
    "Hz",
    "Ohm",
    "Pa",
    "U/min",
    "V",
    "W",
    "W/m²",
    "bar",
    "kW",
    "kWh",
    "kg",
    "l",
    "l/min",
    "mV",
    "m²",
    "s",
    "°C",
    "%rH",
    CUSTOM_UNIT_UNITLESS,
]
# The inclusion of CUSTOM_UNIT_UNITLESS in FLOAT_SENSOR_UNITS will also detect the serial number as a float sensor,
# but there is no way to exclude only this single endpoint without hardcoding it
# If you want to handle it as a string you can add a template helper in HA to convert it to a string

WRITABLE_SENSOR_UNITS = [
    "%",
    "°C",
    "kg",
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
    CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
    CUSTOM_UNIT_UNITLESS,
]

DEFAULT_VALID_WRITABLE_VALUES = {
    "%": ETAValidWritableValues(
        scaled_min_value=-100,
        scaled_max_value=100,
        scale_factor=1,
        dec_places=0,
    ),
    "°C": ETAValidWritableValues(
        scaled_min_value=-100,
        scaled_max_value=200,
        scale_factor=1,
        dec_places=0,
    ),
    "kg": ETAValidWritableValues(
        scaled_min_value=-100000,
        scaled_max_value=100000,
        scale_factor=1,
        dec_places=0,
    ),
}
