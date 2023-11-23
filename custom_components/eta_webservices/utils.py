from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def create_device_info(host: str, port: str):
    return DeviceInfo(
        identifiers={(DOMAIN, "eta_" + host.replace(".", "_") + "_" + str(port))},
        name="ETA",
        manufacturer="ETA",
        configuration_url="https://www.meineta.at",
    )
