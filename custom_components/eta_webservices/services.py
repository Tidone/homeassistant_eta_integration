import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
)

from .api import EtaAPI

WRITE_ENDPOINT_SCHEMA = vol.Schema(
    {
        vol.Required("endpoint_url"): cv.string,
        vol.Required("value"): cv.string,
        vol.Optional("begin"): vol.All(vol.Coerce(int), vol.Range(min=0, max=96)),
        vol.Optional("end"): vol.All(vol.Coerce(int), vol.Range(min=0, max=96))
    },
)

async def async_setup_services(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    session = async_get_clientsession(hass)
    config = hass.data[DOMAIN][config_entry.entry_id]

    async def handle_write(call: ServiceCall):
        """Handle the service call."""
        url = call.data.get("endpoint_url")
        value = call.data.get("value")
        begin = call.data.get("begin", None)
        end = call.data.get("end", None)
        eta_client = EtaAPI(session, config.get(CONF_HOST), config.get(CONF_PORT))
        success = await eta_client.write_endpoint(url, value, begin, end)
        if not success:
            raise HomeAssistantError("Could not write value, see log for details")


    hass.services.async_register(DOMAIN, "write_value", handle_write, schema=WRITE_ENDPOINT_SCHEMA)
