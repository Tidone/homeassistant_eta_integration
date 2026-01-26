"""Coordinator for writable sensors and their normal sensor counterparts."""

from __future__ import annotations

from asyncio import timeout
from datetime import timedelta
import logging

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import EtaAPI, ETAEndpoint, ETAError
from .const import (
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    DOMAIN,
    WRITABLE_DICT,
)

DATA_SCAN_INTERVAL = timedelta(minutes=1)
# the error endpoint doesn't have to be updated as often because we don't expect any updates most of the time
ERROR_SCAN_INTERVAL = timedelta(minutes=2)

_LOGGER = logging.getLogger(__name__)


class ETAErrorUpdateCoordinator(DataUpdateCoordinator[list[ETAError]]):
    """Class to manage fetching error data from the ETA terminal."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""

        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=ERROR_SCAN_INTERVAL,
        )

    def _handle_error_events(self, new_errors):
        old_errors = self.data
        if old_errors is None:
            old_errors = []

        for error in old_errors:
            if error not in new_errors:
                self.hass.bus.async_fire(
                    "eta_webservices_error_cleared", event_data=error
                )

        for error in new_errors:
            if error not in old_errors:
                self.hass.bus.async_fire(
                    "eta_webservices_error_detected", event_data=error
                )

    async def _async_update_data(self) -> list[ETAError]:
        """Update data via library."""
        errors = []
        eta_client = EtaAPI(self.session, self.host, self.port)

        async with timeout(10):
            errors = await eta_client.get_errors()
            self._handle_error_events(errors)
            return errors


class ETAWritableUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Class to manage fetching data from the ETA terminal."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""

        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)
        self.chosen_writable_sensors: list[str] = config[CHOSEN_WRITABLE_SENSORS]
        self.all_writable_sensors: dict[str, ETAEndpoint] = config[WRITABLE_DICT]

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DATA_SCAN_INTERVAL,
        )

    def _should_force_number_handling(self, unit):
        return unit == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT

    async def _async_update_data(self) -> dict:
        """Update data via library."""
        data = {}
        eta_client = EtaAPI(self.session, self.host, self.port)

        for sensor in self.chosen_writable_sensors:
            async with timeout(10):
                value, _ = await eta_client.get_data(
                    self.all_writable_sensors[sensor]["url"],
                    # force the api to return the number value instead of the text value, even if the eta endpoint returns an invalid unit
                    # This is the case for e.g. time endpoints, which have an empty unit, but we still need the number value (minutes since midnight), instead of the text value ("19:00")
                    self._should_force_number_handling(
                        self.all_writable_sensors[sensor]["unit"]
                    ),
                )
                data[sensor] = value
                data[sensor.removesuffix("_writable")] = value

        return data
