"""Diagnostics support for ETA Sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EtaAPI
from .const import (
    DEFAULT_MAX_PARALLEL_REQUESTS,
    DOMAIN,
    MAX_PARALLEL_REQUESTS,
    REQUEST_SEMAPHORE,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    config = hass.data[DOMAIN][entry.entry_id]

    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    session = async_get_clientsession(hass)

    eta_client = EtaAPI(
        session,
        host,
        port,
        max_concurrent_requests=config.get(
            MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS
        ),
        request_semaphore=config.get(REQUEST_SEMAPHORE),
    )
    user_menu = await eta_client.get_menu()
    api_version = await eta_client.get_api_version()

    return {"config": config, "api_version": str(api_version), "menu": user_menu}
