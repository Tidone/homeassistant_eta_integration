"""Various utility functions."""

from homeassistant.helpers.device_registry import DeviceInfo

from .const import CUSTOM_UNIT_UNITLESS, DOMAIN


def create_device_info(host: str, port: str, device_name: str | None) -> DeviceInfo:
    """Create a common DeviceInfo object."""

    # If no device name is provided fall back to the old style
    # This makes sure that meta-entities (error sensors) show up in the old "ETA" device,
    # while all other entities are grouped in a new device with the provided name (e.g. "ETA Living Room").

    # We have to assign a prefix ("ETA > ") because if we just used the device_name,
    # the Home Assistant UI would automatically strip this name from all entity names.
    # E.g. "Kessel > Kessel" would be shown as "> Kessel"
    # This is sone in the frontend with no way to disable this.
    eta_device_name = f"ETA > {device_name}" if device_name else "ETA"

    return DeviceInfo(
        identifiers={
            (
                DOMAIN,
                f"eta_{host.replace('.', '_')}_{port}{'_' + device_name if device_name else ''}",
            )
        },
        name=eta_device_name,
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
