"""Various utility functions."""

from homeassistant.helpers.device_registry import DeviceInfo

from .const import CUSTOM_UNIT_UNITLESS, DOMAIN


def create_device_info(host: str, port: str):
    """Create a common DeviceInfo object."""
    return DeviceInfo(
        identifiers={(DOMAIN, "eta_" + host.replace(".", "_") + "_" + str(port))},
        name="ETA",
        manufacturer="ETA",
        configuration_url="https://www.meineta.at",
    )


def get_native_unit(unit):
    """Convert ETA API units to Home Assistant native units."""
    if unit == "%rH":
        return "%"
    if unit == "":
        return None
    if unit == CUSTOM_UNIT_UNITLESS:
        return None
    return unit
