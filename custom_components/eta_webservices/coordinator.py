"""Coordinator for ETA sensor updates."""

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
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
    CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
    CUSTOM_UNITS,
    DOMAIN,
    FLOAT_DICT,
    MAX_PARALLEL_REQUESTS,
    REQUEST_SEMAPHORE,
    REQUEST_TIMEOUT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
)

DATA_SCAN_INTERVAL = timedelta(minutes=1)
# The error endpoint does not have to be updated as often.
ERROR_SCAN_INTERVAL = timedelta(minutes=2)

_LOGGER = logging.getLogger(__name__)


class ETAErrorUpdateCoordinator(DataUpdateCoordinator[list[ETAError]]):
    """Class to manage fetching error data from the ETA terminal."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""
        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)
        self.max_parallel_requests = int(config.get(MAX_PARALLEL_REQUESTS, 5))
        self.request_semaphore = config.get(REQUEST_SEMAPHORE)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=ERROR_SCAN_INTERVAL,
        )

    def _handle_error_events(self, new_errors: list[ETAError]):
    def _create_eta_client(self):
        return EtaAPI(
            self.session,
            self.host,
            self.port,
            max_concurrent_requests=self.max_parallel_requests,
            request_semaphore=self.request_semaphore,
        )

    def _handle_error_events(self, new_errors: list[ETAError]):
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
        eta_client = self._create_eta_client()

        async with timeout(REQUEST_TIMEOUT):
            errors = await eta_client.get_errors()
            self._handle_error_events(errors)
            return errors


class ETASensorUpdateCoordinator(DataUpdateCoordinator[dict[str, float | str | bool]]):
    """Class to manage fetching data for normal sensor and switch entities."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""
        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)
        self.max_parallel_requests = int(config.get(MAX_PARALLEL_REQUESTS, 5))
        self.request_semaphore = config.get(REQUEST_SEMAPHORE)

        self.chosen_float_sensors: list[str] = config[CHOSEN_FLOAT_SENSORS]
        self.chosen_switches: list[str] = config[CHOSEN_SWITCHES]
        self.chosen_text_sensors: list[str] = config[CHOSEN_TEXT_SENSORS]
        self.chosen_writable_sensors: list[str] = config[CHOSEN_WRITABLE_SENSORS]

        self.all_float_sensors: dict[str, ETAEndpoint] = config[FLOAT_DICT]
        self.all_switches: dict[str, ETAEndpoint] = config[SWITCHES_DICT]
        self.all_text_sensors: dict[str, ETAEndpoint] = config[TEXT_DICT]
        self.all_writable_sensors: dict[str, ETAEndpoint] = config[WRITABLE_DICT]

        self.sensor_queries: dict[str, tuple[str, bool]] = {}
        self.switch_queries: dict[str, tuple[str, int, int]] = {}
        # Per-entity defaults are used for first refresh and as fallback on partial API failures.
        self.default_data: dict[str, float | str | bool] = {}
        self._build_queries()

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DATA_SCAN_INTERVAL,
        )

    def _create_eta_client(self):
        return EtaAPI(
            self.session,
            self.host,
            self.port,
            max_concurrent_requests=self.max_parallel_requests,
            request_semaphore=self.request_semaphore,
        )

    def _build_queries(self) -> None:
        # Exclude float sensors that are also writable, they are handled by writable coordinator.
        for sensor in self.chosen_float_sensors:
            if sensor + "_writable" in self.chosen_writable_sensors:
                continue
            if sensor not in self.all_float_sensors:
                continue
            endpoint = self.all_float_sensors[sensor]
            self.sensor_queries[sensor] = (endpoint["url"], False)
            self.default_data[sensor] = endpoint["value"]

        for sensor in self.chosen_text_sensors:
            if sensor not in self.all_text_sensors:
                continue
            endpoint = self.all_text_sensors[sensor]

            # These sensors are handled through the writable coordinator and are refreshed
            # immediately after user writes.
            if (
                sensor + "_writable" in self.chosen_writable_sensors
                and endpoint["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
            ):
                continue

            self.sensor_queries[sensor] = (
                endpoint["url"],
                endpoint["unit"] in CUSTOM_UNITS,
            )
            self.default_data[sensor] = endpoint["value"]

        for sensor in self.chosen_writable_sensors:
            if sensor not in self.all_writable_sensors:
                continue
            endpoint = self.all_writable_sensors[sensor]
            if endpoint["unit"] not in (
                CUSTOM_UNIT_TIMESLOT,
                CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
            ):
                continue
            self.sensor_queries[sensor] = (endpoint["url"], True)
            self.default_data[sensor] = endpoint["value"]

        for switch in self.chosen_switches:
            if switch not in self.all_switches:
                continue
            endpoint = self.all_switches[switch]
            valid_values = endpoint["valid_values"]
            on_value = 1803
            off_value = 1802
            if isinstance(valid_values, dict):
                on_value = int(valid_values.get("on_value", on_value))
                off_value = int(valid_values.get("off_value", off_value))

            self.switch_queries[switch] = (endpoint["url"], on_value, off_value)
            self.default_data[switch] = False

    async def _async_update_data(self) -> dict[str, float | str | bool]:
        """Update data via library."""
        eta_client = self._create_eta_client()
        data = dict(self.default_data)
        if self.data is not None:
            # Keep previous values if only a subset of endpoints fails in this refresh cycle.
            data.update(self.data)

        uri_sensor_queries: dict[str, dict[str, bool]] = {}
        # Multiple entities can point to the same URI; query each endpoint only once.
        for uri, force_string_handling in self.sensor_queries.values():
            if uri not in uri_sensor_queries:
                uri_sensor_queries[uri] = {}
            if force_string_handling:
                uri_sensor_queries[uri]["force_string_handling"] = True

        async with timeout(REQUEST_TIMEOUT):
            if uri_sensor_queries:
                all_sensor_data = await eta_client.get_all_data(uri_sensor_queries)
                for sensor, (uri, _) in self.sensor_queries.items():
                    result = all_sensor_data.get(uri)
                    if result is None:
                        _LOGGER.debug("Failed to update sensor '%s': %s", sensor, result)
                        continue
                    data[sensor] = result

            if self.switch_queries:
                unique_switch_uris = list(
                    # Query shared switch URIs once and map results back per entity.
                    dict.fromkeys([uri for uri, _, _ in self.switch_queries.values()])
                )
                all_switch_states = await eta_client.get_all_switch_states(
                    unique_switch_uris
                )
                for switch, (uri, on_value, _) in self.switch_queries.items():
                    result = all_switch_states.get(uri)
                    if result is None or isinstance(result, Exception):
                        _LOGGER.debug(
                            "Failed to update switch '%s' (%s): %s", switch, uri, result
                        )
                        continue
                    data[switch] = int(result) == on_value

        return data


class ETAWritableUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Class to manage fetching data from the ETA terminal."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize."""
        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)
        self.max_parallel_requests = int(config.get(MAX_PARALLEL_REQUESTS, 5))
        self.request_semaphore = config.get(REQUEST_SEMAPHORE)
        self.chosen_writable_sensors: list[str] = config[CHOSEN_WRITABLE_SENSORS]
        self.all_writable_sensors: dict[str, ETAEndpoint] = config[WRITABLE_DICT]

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DATA_SCAN_INTERVAL,
        )

    def _create_eta_client(self):
        return EtaAPI(
            self.session,
            self.host,
            self.port,
            max_concurrent_requests=self.max_parallel_requests,
            request_semaphore=self.request_semaphore,
        )

    def _should_force_number_handling(self, unit):
        return unit == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT

    async def _async_update_data(self) -> dict:
        """Update data via library."""
        eta_client = self._create_eta_client()
        sensor_list = {
            self.all_writable_sensors[sensor]["url"]: {
                "force_number_handling": self._should_force_number_handling(
                    self.all_writable_sensors[sensor]["unit"]
                )
            }
            for sensor in self.chosen_writable_sensors
        }
        return await eta_client.get_all_data(sensor_list)
