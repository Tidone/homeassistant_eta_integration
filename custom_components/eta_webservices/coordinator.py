"""The Airzone integration."""

from __future__ import annotations

import asyncio
from asyncio import timeout
from datetime import timedelta
import logging

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    FLOAT_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    FORCE_LEGACY_MODE,
    DATA_UPDATE_COORDINATOR,
)
from .api import EtaAPI, ETAError, ETAEndpoint

DATA_SCAN_INTERVAL = timedelta(minutes=1)
# the error endpoint doesn't have to be updated as often because we don't expect any updates most of the time
ERROR_SCAN_INTERVAL = timedelta(minutes=2)

_LOGGER = logging.getLogger(__name__)


class EtaDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the ETA terminal."""

    def __init__(
        self, hass: HomeAssistant, config: dict, device_name: str, entry_id: str
    ) -> None:
        """Initialize."""
        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)
        self.device_name = device_name
        self.entry_id = entry_id
        self.config = config

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_name}",
            update_interval=DATA_SCAN_INTERVAL,
        )

    def _should_force_number_handling(self, unit):
        return unit == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT

    async def _async_update_data(self) -> dict:
        """Update data via library, using cached entities if available."""

        data = self.data if self.data is not None else {}

        # Discover entities only if not already populated
        if not data:
            config_entry = self.hass.config_entries.async_get_entry(self.entry_id)
            # Try to load from cache first
            stored_entities = config_entry.data.get("scanned_devices_data", {}).get(
                self.device_name
            )

            if stored_entities:
                _LOGGER.info("Using cached entities for device %s", self.device_name)
                data = stored_entities
            else:
                # If not in cache, perform discovery
                _LOGGER.info(
                    "No cached entities found. Discovering entities for device %s. This may take a moment.",
                    self.device_name,
                )
                eta_client = EtaAPI(self.session, self.host, self.port)
                entity_structure = await eta_client.get_entity_structure(
                    self.device_name
                )

                leaf_nodes = []

                def collect_leaf_nodes(node, path=""):
                    name = node.get("name")
                    uri = node.get("uri")
                    current_path = f"{path}_{name}" if path else f"_{name}"

                    if uri and not node.get("children"):
                        leaf_nodes.append({"uri": uri, "path": current_path})

                    for child in node.get("children", []):
                        collect_leaf_nodes(child, current_path)

                if entity_structure:
                    collect_leaf_nodes(entity_structure)

                semaphore = asyncio.Semaphore(5)  # Limit concurrency to 5

                async def fetch_metadata(leaf_node):
                    async with semaphore:
                        uri = leaf_node["uri"]
                        metadata = await eta_client.async_get_entity_metadata(uri)
                        return leaf_node, metadata

                metadata_tasks = [fetch_metadata(node) for node in leaf_nodes]

                float_dict = {}
                switches_dict = {}
                text_dict = {}
                writable_dict = {}

                if metadata_tasks:
                    results = await asyncio.gather(
                        *metadata_tasks, return_exceptions=True
                    )

                    for result in results:
                        if isinstance(result, Exception):
                            _LOGGER.warning("A metadata fetch task failed: %s", result)
                            continue

                        leaf_node, metadata = result
                        if not metadata:
                            _LOGGER.warning(
                                "Failed to get metadata for node %s", leaf_node["uri"]
                            )
                            continue

                        current_path = leaf_node["path"]
                        entity_type = eta_client.classify_entity(metadata)
                        unique_key = f"eta_{self.host.replace('.', '_')}_{current_path.lower().replace(' ', '_')}"
                        metadata["friendly_name"] = " > ".join(
                            current_path.split("_")[2:]
                        )

                        if entity_type == "sensor":
                            if metadata.get("unit") == "":
                                text_dict[unique_key] = metadata
                            else:
                                float_dict[unique_key] = metadata
                        elif entity_type == "switch":
                            switches_dict[unique_key] = metadata
                        elif entity_type == "number":
                            writable_dict[unique_key] = metadata
                        elif entity_type == "time":
                            writable_dict[unique_key] = metadata

                discovered_data = {
                    FLOAT_DICT: float_dict,
                    SWITCHES_DICT: switches_dict,
                    TEXT_DICT: text_dict,
                    WRITABLE_DICT: writable_dict,
                    "values": {},
                }

                # Persist the discovered data for next restart
                _LOGGER.info(
                    "Discovered %d entities. Caching for future restarts.",
                    len(leaf_nodes),
                )
                new_entry_data = {**config_entry.data}
                if "scanned_devices_data" not in new_entry_data:
                    new_entry_data["scanned_devices_data"] = {}
                new_entry_data["scanned_devices_data"][
                    self.device_name
                ] = discovered_data
                self.hass.config_entries.async_update_entry(
                    config_entry, data=new_entry_data
                )

                data = discovered_data

        # Update the values for all chosen sensors
        eta_client = EtaAPI(self.session, self.host, self.port)
        config_entry = self.hass.config_entries.async_get_entry(self.entry_id)
        options = config_entry.options

        all_sensors = {
            **data.get(FLOAT_DICT, {}),
            **data.get(SWITCHES_DICT, {}),
            **data.get(TEXT_DICT, {}),
            **data.get(WRITABLE_DICT, {}),
        }

        # If options are not set, update all discovered sensors
        chosen_sensors_keys = [
            *options.get(CHOSEN_FLOAT_SENSORS, list(data.get(FLOAT_DICT, {}).keys())),
            *options.get(CHOSEN_SWITCHES, list(data.get(SWITCHES_DICT, {}).keys())),
            *options.get(CHOSEN_TEXT_SENSORS, list(data.get(TEXT_DICT, {}).keys())),
            *options.get(
                CHOSEN_WRITABLE_SENSORS, list(data.get(WRITABLE_DICT, {}).keys())
            ),
        ]

        updated_values = {}
        for sensor_key in chosen_sensors_keys:
            if sensor_key in all_sensors:
                sensor_endpoint = all_sensors[sensor_key]
                try:
                    async with timeout(10):
                        value, _ = await eta_client.get_data(
                            sensor_endpoint["url"],
                            self._should_force_number_handling(sensor_endpoint["unit"]),
                        )
                        updated_values[sensor_key] = value
                except Exception as e:
                    _LOGGER.error(
                        "Error updating sensor %s for device %s: %s",
                        sensor_key,
                        self.device_name,
                        e,
                    )

        # Return a new data object with updated values
        return {**data, "values": updated_values}


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
