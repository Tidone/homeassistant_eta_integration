"""API v1.1 specific sensor discovery implementation."""

import asyncio
import logging

from .sensor_discovery_base import SensorDiscoveryBase
from .types import (
    DEFAULT_VALID_WRITABLE_VALUES,
    WRITABLE_SENSOR_UNITS,
    ETAEndpoint,
    ETAValidSwitchValues,
)

_LOGGER = logging.getLogger(__name__)


class SensorDiscoveryV11(SensorDiscoveryBase):
    """ETA API v1.1 specific sensor discovery implementation."""

    def _is_switch(
        self, endpoint_info: ETAEndpoint, raw_value: str | None = None
    ) -> bool:
        """Check if endpoint is a switch (v1.1 method)."""
        if endpoint_info["unit"] == "" and raw_value in ("1802", "1803"):
            return True
        return False

    def _parse_switch_values(self, endpoint_info: ETAEndpoint):
        """Parse switch values (v1.1 hardcoded values)."""
        endpoint_info["valid_values"] = ETAValidSwitchValues(
            on_value=1803, off_value=1802
        )

    def _is_writable(self, endpoint_info: ETAEndpoint) -> bool:
        """Check if endpoint is writable (v1.1 method)."""
        # API v1.1 lacks the necessary function to query detailed info about the endpoint
        # that's why we just check the unit to see if it is in the list of acceptable writable sensor units
        return endpoint_info["unit"] in WRITABLE_SENSOR_UNITS

    def _parse_valid_writable_values(self, endpoint_info: ETAEndpoint, raw_dict: dict):
        """Parse valid writable values (v1.1 uses defaults)."""
        # API v1.1 lacks the necessary function to query detailed info about the endpoint
        # that's why we have to assume sensible valid ranges for the endpoints based on their unit
        endpoint_info["valid_values"] = DEFAULT_VALID_WRITABLE_VALUES[
            endpoint_info["unit"]
        ]
        endpoint_info["valid_values"]["dec_places"] = int(raw_dict["@decPlaces"])
        endpoint_info["valid_values"]["scale_factor"] = int(raw_dict["@scaleFactor"])

    def _sanitize_duplicate_nodes(
        self,
        all_endpoints: dict[str, list[str]],
        endpoint_data: dict[str, tuple[float | str, str, dict]],
    ) -> int:
        """Sanitize duplicate nodes by removing invalid URIs (v1.1 version)."""
        nodes_to_check: list[tuple[str, list[str]]] = []
        for key, uris in all_endpoints.items():
            if len(uris) <= 1:
                continue
            uris_in_data = [uri for uri in uris if uri in endpoint_data]
            if len(uris_in_data) < 2:
                continue
            nodes_to_check.append((key, uris_in_data))

        if not nodes_to_check:
            return 0

        _LOGGER.debug(
            "Sanitizing duplicate nodes: found %d nodes with 2+ URIs",
            len(nodes_to_check),
        )

        uris_to_remove = []
        for key, uris in nodes_to_check:
            valid_uris = []
            invalid_uris = []

            for uri in uris:
                value = endpoint_data[uri][0]
                if value == "xxx":
                    invalid_uris.append(uri)
                else:
                    valid_uris.append(uri)

            if len(valid_uris) == 1 and len(invalid_uris) > 0:
                uris_to_remove.extend(invalid_uris)
                _LOGGER.debug(
                    "Node %s: keeping URI %s, removing %d invalid URIs",
                    key,
                    valid_uris[0],
                    len(invalid_uris),
                )
            elif len(valid_uris) == 0:
                _LOGGER.debug(
                    "Node %s: all %d URIs invalid, keeping all", key, len(invalid_uris)
                )
            elif len(valid_uris) > 1:
                _LOGGER.debug(
                    "Node %s: multiple valid URIs (%d), keeping all",
                    key,
                    len(valid_uris),
                )

        removed_count = 0
        for uri in set(uris_to_remove):
            if uri in endpoint_data:
                del endpoint_data[uri]
                removed_count += 1

        return removed_count

    # runlength w/o optimizations: 78s
    # runlength w/ optimizations (sem=1): 77s
    # runlength w/ optimizations (sem=2): 43s
    # runlength w/ optimizations (sem=3): 25s
    # runlength w/ optimizations (sem=4): 19s
    # runlength w/ optimizations (sem=5): 15s
    # runlength w/ optimizations (sem=10): 7s

    async def get_all_sensors(
        self, float_dict, switches_dict, text_dict, writable_dict
    ):
        """Enumerate all sensors using v1.1 methods."""
        self._http.num_duplicates = 0
        all_endpoints = await self._http.get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)

        # Flatten and deduplicate URIs
        deduplicated_uris = {}
        total_uris = 0
        for key, uri_list in all_endpoints.items():
            for uri in uri_list:
                total_uris += 1
                if uri not in deduplicated_uris:
                    deduplicated_uris[uri] = key
                else:
                    _LOGGER.debug(
                        "Skipping duplicate URI %s (key: %s, already have key: %s)",
                        uri,
                        key,
                        deduplicated_uris[uri],
                    )

        _LOGGER.debug(
            "Got %d endpoints total, %d unique URIs", total_uris, len(deduplicated_uris)
        )
        _LOGGER.debug(
            "Found %d duplicate keys with multiple URIs", self._http.num_duplicates
        )

        # Fetch all data concurrently
        semaphore = asyncio.Semaphore(self._http.max_concurrent_requests)

        async def fetch_data_limited(uri):
            async with semaphore:
                return await self._http.get_data_plus_raw(uri)

        data_tasks = [fetch_data_limited(uri) for uri in deduplicated_uris]
        data_results = await asyncio.gather(*data_tasks, return_exceptions=True)

        endpoint_data: dict[str, tuple[float | str, str, dict]] = {}
        for uri, result in zip(deduplicated_uris.keys(), data_results, strict=False):
            if isinstance(result, Exception):
                _LOGGER.debug("Failed to get data for %s: %s", uri, str(result))
            else:
                endpoint_data[uri] = result  # pyright: ignore[reportArgumentType]

        # Sanitize duplicates
        removed_count = self._sanitize_duplicate_nodes(all_endpoints, endpoint_data)
        if removed_count > 0:
            _LOGGER.info("Removed %d invalid URIs from duplicate nodes", removed_count)

        # Process endpoints
        for uri, key in deduplicated_uris.items():
            if uri not in endpoint_data:
                continue

            value, unit, raw_dict = endpoint_data[uri]

            try:
                endpoint_info = ETAEndpoint(
                    url=uri,
                    valid_values=None,
                    friendly_name=self._get_friendly_name(key),
                    unit=unit,
                    # Fallback: declare all endpoints as text sensors.
                    # If the unit is in the list of known units, the sensor will be detected as a float sensor anyway.
                    endpoint_type="TEXT",
                    value=value,
                )

                unique_key = (
                    "eta_"
                    + self._http.host.replace(".", "_")
                    + "_"
                    + key.lower().replace(" ", "_")
                )

                if self._is_writable(endpoint_info):
                    _LOGGER.debug("Adding %s as writable sensor", uri)
                    # this is checked separately because all writable sensors are registered as both a sensor entity and a number entity
                    # add a suffix to the unique id to make sure it is still unique in case the sensor is selected in the writable list and in the sensor list
                    writable_key = unique_key + "_writable"
                    if writable_key not in writable_dict:
                        self._parse_valid_writable_values(endpoint_info, raw_dict)
                        writable_dict[writable_key] = endpoint_info
                    else:
                        _LOGGER.debug(
                            "Skipping duplicate writable sensor %s", writable_key
                        )

                if self._is_float_sensor(endpoint_info):
                    _LOGGER.debug("Adding %s as float sensor", uri)
                    if unique_key not in float_dict:
                        float_dict[unique_key] = endpoint_info
                    else:
                        _LOGGER.debug("Skipping duplicate float sensor %s", unique_key)
                elif self._is_switch(endpoint_info, raw_dict["#text"]):
                    _LOGGER.debug("Adding %s as switch", uri)
                    if unique_key not in switches_dict:
                        self._parse_switch_values(endpoint_info)
                        switches_dict[unique_key] = endpoint_info
                    else:
                        _LOGGER.debug("Skipping duplicate switch %s", unique_key)
                elif self._is_text_sensor(endpoint_info) and value != "":
                    _LOGGER.debug("Adding %s as text sensor", uri)
                    # Ignore enpoints with an empty value
                    # This has to be the last branch for the above fallback to work
                    if unique_key not in text_dict:
                        text_dict[unique_key] = endpoint_info
                    else:
                        _LOGGER.debug("Skipping duplicate text sensor %s", unique_key)
                else:
                    _LOGGER.debug("Not adding endpoint %s: Unknown type", uri)

            except Exception:  # noqa: BLE001
                _LOGGER.debug("Invalid endpoint %s", uri, exc_info=True)

        valid_endpoints = (
            len(float_dict) + len(switches_dict) + len(text_dict) + len(writable_dict)
        )
        _LOGGER.info(
            "Sensor enumeration complete: %d valid sensors from %d unique URIs (%d total URIs, %d duplicate keys)",
            valid_endpoints,
            len(deduplicated_uris),
            total_uris,
            self._http.num_duplicates,
        )
