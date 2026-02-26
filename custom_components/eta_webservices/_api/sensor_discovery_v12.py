"""API v1.2 specific sensor discovery implementation."""

import asyncio
import logging

import xmltodict

from ..const import (  # noqa: TID252
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
    CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
    CUSTOM_UNIT_UNITLESS,
    CUSTOM_UNITS,
)
from .sensor_discovery_base import SensorDiscoveryBase
from .types import WRITABLE_SENSOR_UNITS, ETAEndpoint, ETAValidWritableValues

_LOGGER = logging.getLogger(__name__)


class SensorDiscoveryV12(SensorDiscoveryBase):
    """ETA API v1.2 specific sensor discovery implementation."""

    def _is_switch(
        self, endpoint_info: ETAEndpoint, raw_value: str | None = None
    ) -> bool:
        """Check if endpoint is a switch (v1.2 method)."""
        valid_values = endpoint_info["valid_values"]
        if valid_values is None:
            return False
        if len(valid_values) != 2:
            return False
        if not all(
            k in ("Ein", "Aus", "On", "Off", "Ja", "Nein", "Yes", "No")
            for k in valid_values
        ):
            return False
        return True

    def _parse_switch_values(self, endpoint_info: ETAEndpoint):
        """Parse switch values (v1.2 method from validValues)."""
        valid_values = {"on_value": 0, "off_value": 0}
        if (
            endpoint_info["valid_values"] is None
            or type(endpoint_info["valid_values"]) is not dict
        ):
            return
        for key in endpoint_info["valid_values"]:
            if key in ("Ein", "On", "Ja", "Yes"):
                valid_values["on_value"] = endpoint_info["valid_values"][key]
            elif key in ("Aus", "Off", "Nein", "No"):
                valid_values["off_value"] = endpoint_info["valid_values"][key]
        endpoint_info["valid_values"] = valid_values

    def _is_writable(self, endpoint_info: ETAEndpoint) -> bool:
        """Check if endpoint is writable (v1.2 method)."""
        # TypedDict does not support isinstance(),
        # so we have to manually check if we hace the correct dict type
        # based on the presence of a known key
        return (
            endpoint_info["unit"] in WRITABLE_SENSOR_UNITS
            and endpoint_info["valid_values"] is not None
            and "scaled_min_value" in endpoint_info["valid_values"]
        )

    def _parse_unit(self, data):
        """Parse and detect custom units (v1.2 specific)."""
        unit = data["@unit"]
        if (
            unit == ""
            and "validValues" in data
            and data["validValues"] is not None
            and "min" in data["validValues"]
            and "max" in data["validValues"]
            and "#text" in data["validValues"]["min"]
            and int(data["@scaleFactor"]) == 1
            and int(data["@decPlaces"]) == 0
        ):
            _LOGGER.debug("Found time endpoint")
            min_value = int(data["validValues"]["min"]["#text"])
            max_value = int(data["validValues"]["max"]["#text"])
            if min_value == 0 and max_value == 24 * 60 - 1:
                # time endpoints have a min value of 0 and max value of 1439
                # it may be better to parse the strValue and check if it is in the format "00:00"
                unit = CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        elif (
            unit in ["", "°C"]
            and "validValues" in data
            and data["validValues"] is not None
            and "min" in data["validValues"]
            and "max" in data["validValues"]
            and "begin" in data["validValues"]["min"]
            and "end" in data["validValues"]["min"]
        ):
            min_value = int(data["validValues"]["min"]["begin"])
            max_value = int(data["validValues"]["max"]["end"])
            if min_value == 0 and max_value == 24 * 60 / 15:
                # time endpoints have a min value of 0 and max value of 96
                # it may be better to parse the strValue and check if it is in the format "00:00 - 00:00"
                if "value" in data["validValues"]["min"]:
                    _LOGGER.debug("Found timeslot endpoint with temperature")
                    unit = CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE
                else:
                    _LOGGER.debug("Found timeslot endpoint")
                    unit = CUSTOM_UNIT_TIMESLOT
        return unit

    def _createETAValidWritableValues(
        self,
        raw_min_value: float,
        raw_max_value: float,
        scale_factor: int,
        dec_places: int,
    ):
        """Create ETAValidWritableValues from raw data."""
        min_value = round(float(raw_min_value) / scale_factor, dec_places)
        max_value = round(float(raw_max_value) / scale_factor, dec_places)
        return ETAValidWritableValues(
            scaled_min_value=min_value,
            scaled_max_value=max_value,
            scale_factor=scale_factor,
            dec_places=dec_places,
        )

    def _parse_varinfo(self, data, fub: str, uri: str):
        """Parse varinfo XML response."""
        _LOGGER.debug("Parsing varinfo %s", data)
        valid_values = None
        unit = self._parse_unit(data)
        if (
            "validValues" in data
            and data["validValues"] is not None
            and "value" in data["validValues"]
        ):
            values = data["validValues"]["value"]
            valid_values = dict(
                zip(
                    [k["@strValue"] for k in values],
                    [int(v["#text"]) for v in values],
                    strict=False,
                )
            )
        elif (
            "validValues" in data
            and data["validValues"] is not None
            and "min" in data["validValues"]
            and "#text" in data["validValues"]["min"]
            # check if the unit is in the list of writable sensor units or if the type is DEFAULT with an empty unit, which is an indicator of a unitless writable sensor
            # this check may be inaccurate, but we can reject invalid writable sensors later when we have determined the final unit (thi is done in _is_writable)
            and (
                unit in WRITABLE_SENSOR_UNITS
                or ("type" in data and data["type"] == "DEFAULT" and unit == "")
            )
        ):
            min_value = data["validValues"]["min"]["#text"]
            max_value = data["validValues"]["max"]["#text"]
            valid_values = self._createETAValidWritableValues(
                raw_min_value=min_value,
                raw_max_value=max_value,
                scale_factor=int(data["@scaleFactor"]),
                dec_places=int(data["@decPlaces"]),
            )
        if unit == CUSTOM_UNIT_TIMESLOT:
            # store the min and max value of the timeslots for this unit
            valid_values = ETAValidWritableValues(
                scaled_min_value=0,
                scaled_max_value=96,
                scale_factor=1,
                dec_places=0,
            )
        elif unit == CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE:
            # store the min and max value of the temperature for this unit
            # the min and max values for the timeslots can be assumed to be 0 and 96 respectively,
            # otherwise we wouldn't have assigned this unit in the first place
            min_value = data["validValues"]["min"]["value"]
            max_value = data["validValues"]["max"]["value"]
            valid_values = self._createETAValidWritableValues(
                raw_min_value=min_value,
                raw_max_value=max_value,
                scale_factor=int(data["@scaleFactor"]),
                dec_places=int(data["@decPlaces"]),
            )

        return ETAEndpoint(
            valid_values=valid_values,
            friendly_name=f"{fub} > {data['@fullName']}",
            unit=unit,
            endpoint_type=data["type"],
            url=uri,
            value=0,
        )

    async def _get_varinfo(self, fub, uri):
        """Fetch varinfo from API."""
        data = await self._http.get_request("/user/varinfo/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["varInfo"]["variable"]
        return self._parse_varinfo(data, fub, uri)

    async def _sanitize_duplicate_nodes(
        self,
        all_endpoints: dict[str, list[str]],
        endpoint_infos: dict[str, ETAEndpoint],
    ) -> int:
        """Sanitize duplicate nodes by removing URIs that return invalid data.

        For nodes with multiple URIs, this function tests each URI by fetching
        its data. If exactly one URI returns valid data and all others return
        'xxx' or raise exceptions, the invalid URIs are removed from endpoint_infos.

        Args:
            all_endpoints: Maps sensor keys to lists of URIs
            endpoint_infos: Maps URIs to their endpoint metadata (modified in-place)

        Returns:
            Number of URIs removed
        """
        # Phase 1: Identify nodes to process
        nodes_to_check: list[tuple[str, list[str]]] = []
        for key, uris in all_endpoints.items():
            # Skip single-URI nodes
            if len(uris) <= 1:
                continue

            # Find URIs that exist in endpoint_infos
            uris_in_infos = [uri for uri in uris if uri in endpoint_infos]

            # Skip if fewer than 2 URIs are in endpoint_infos
            if len(uris_in_infos) < 2:
                continue

            nodes_to_check.append((key, uris_in_infos))

        # Early return if no nodes to check
        if not nodes_to_check:
            return 0

        _LOGGER.debug(
            "Sanitizing duplicate nodes: found %d nodes with 2+ URIs in endpoint_infos",
            len(nodes_to_check),
        )

        # Phase 2: Gather data from all duplicate URIs
        all_uris_to_test = [uri for _, uris in nodes_to_check for uri in uris]
        _LOGGER.debug(
            "Gathering data from %d URIs for validation", len(all_uris_to_test)
        )

        semaphore = asyncio.Semaphore(self._http.max_concurrent_requests)

        async def fetch_data_limited(uri):
            async with semaphore:
                return await self._http.get_data(uri, force_string_handling=True)

        data_tasks = [fetch_data_limited(uri) for uri in all_uris_to_test]
        data_results_list = await asyncio.gather(*data_tasks, return_exceptions=True)

        # Map results back to URIs
        uri_to_result = dict(zip(all_uris_to_test, data_results_list, strict=False))

        # Phase 3: Evaluate each node and remove invalid URIs
        uris_to_remove = []
        for key, uris in nodes_to_check:
            valid_uris = []
            invalid_uris = []

            for uri in uris:
                result = uri_to_result[uri]

                # Check if result is an exception
                if isinstance(result, BaseException):
                    _LOGGER.debug(
                        "URI %s raised exception during data fetch: %s",
                        uri,
                        str(result),
                    )
                    invalid_uris.append(uri)
                elif not isinstance(result, Exception):
                    # Result is a tuple (value, unit)
                    value, _ = result
                    if value == "xxx":
                        invalid_uris.append(uri)
                    else:
                        valid_uris.append(uri)

            # Apply removal logic
            if len(valid_uris) == 1 and len(invalid_uris) > 0:
                # If exactly one valid URI and at least one invalid URI, remove the invalid ones
                uris_to_remove.extend(invalid_uris)
                _LOGGER.debug(
                    "Node %s: keeping URI %s, removing %d invalid URIs: %s",
                    key,
                    valid_uris[0],
                    len(invalid_uris),
                    invalid_uris,
                )
            elif len(valid_uris) == 0:
                # If no valid URIs, keep them all (can't determine which one is correct)
                _LOGGER.debug(
                    "Node %s: all %d URIs invalid, keeping all", key, len(invalid_uris)
                )
            elif len(valid_uris) > 1:
                # If multiple valid URIs, keep them all (data inconsistency can't be resolved)
                _LOGGER.debug(
                    "Node %s: multiple valid URIs (%d), keeping all",
                    key,
                    len(valid_uris),
                )

        # Remove invalid URIs from endpoint_infos.
        # A URI can appear in multiple duplicate-node groups, so deduplicate before deletion.
        removed_count = 0
        for uri in set(uris_to_remove):
            if uri in endpoint_infos:
                del endpoint_infos[uri]
                removed_count += 1

        return removed_count

    # runlength w/o optimizations: 326s
    # runlength w/ optimizations (sem=1): 330s
    # runlength w/ optimizations (sem=2): 218s
    # runlength w/ optimizations (sem=3): 193s
    # runlength w/ optimizations (sem=4): 187s
    # runlength w/ optimizations (sem=5): 184s
    # runlength w/ optimizations (sem=10): 177s

    async def get_all_sensors(  # noqa: C901
        self, float_dict, switches_dict, text_dict, writable_dict
    ):
        """Enumerate all sensors using v1.2 methods."""
        self._http.num_duplicates = 0  # Reset counter for this enumeration
        all_endpoints = await self._http.get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)

        # Flatten the multi-URI structure and track duplicates
        # INFO: The key and value fields are flipped to check if a uri is already in the dict
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

        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self._http.max_concurrent_requests)

        async def fetch_varinfo_limited(uri, key):
            async with semaphore:
                return await self._get_varinfo(key.split("_")[1], uri)

        # Fetch all varinfo with concurrency limit
        varinfo_tasks = [
            fetch_varinfo_limited(uri, key) for uri, key in deduplicated_uris.items()
        ]

        # This takes WAY longer than the calls to get_data() below
        # Runtime for this section: 170s
        # Runtime for the get_data() section below: 7s
        varinfo_results = await asyncio.gather(*varinfo_tasks, return_exceptions=True)

        # Map results back to URIs, filtering out exceptions
        endpoint_infos: dict[str, ETAEndpoint] = {}
        for uri, result in zip(deduplicated_uris.keys(), varinfo_results, strict=False):
            if isinstance(result, Exception):
                _LOGGER.debug("Failed to get varinfo for %s: %s", uri, str(result))
            else:
                endpoint_infos[uri] = result  # pyright: ignore[reportArgumentType]

        # Sanitize duplicate nodes by testing which URIs return valid data
        removed_count = await self._sanitize_duplicate_nodes(
            all_endpoints, endpoint_infos
        )
        if removed_count > 0:
            _LOGGER.info("Removed %d invalid URIs from duplicate nodes", removed_count)

        # Determine which endpoints need secondary data fetch
        needs_data = []
        for uri, endpoint_info in endpoint_infos.items():
            if (
                self._is_float_sensor(endpoint_info)
                or self._is_switch(endpoint_info)
                or self._is_text_sensor(endpoint_info)
                or (
                    # the ETA API is not very consistent and some sensors show different units in their `varinfo` and `var` endpoints
                    # all of those sensors have an empty unit in `varinfo` and have `DEFAULT` as their type
                    # i.e. the Volllaststunden sensor shows up with an empty unit in `varinfo`, but with seconds in `var`
                    endpoint_info["unit"] == ""
                    and endpoint_info["endpoint_type"] == "DEFAULT"
                )
            ):
                needs_data.append(uri)

        async def fetch_data_limited(uri, force_string_handling):
            async with semaphore:
                return await self._http.get_data(
                    uri, force_string_handling=force_string_handling
                )

        # Fetch all needed data concurrently
        data_results: dict[str, tuple[float | str, str]] = {}
        if needs_data:
            data_tasks = [
                fetch_data_limited(
                    uri,
                    # all custom units should be treated as text sensors
                    force_string_handling=endpoint_infos[uri]["unit"] in CUSTOM_UNITS,
                )
                for uri in needs_data
            ]
            # runtime: 7 seconds for ~500 endpoints
            data_values = await asyncio.gather(*data_tasks, return_exceptions=True)

            # Filter out exceptions from data results
            for uri, result in zip(needs_data, data_values, strict=False):
                if isinstance(result, Exception):
                    _LOGGER.debug("Failed to get data for %s: %s", uri, str(result))
                else:
                    data_results[uri] = result  # pyright: ignore[reportArgumentType]

        for uri, key in deduplicated_uris.items():
            if uri not in endpoint_infos:
                continue

            endpoint_info = endpoint_infos[uri]

            try:
                unique_key = (
                    "eta_"
                    + self._http.host.replace(".", "_")
                    + "_"
                    + key.lower().replace(" ", "_")
                )

                if uri in data_results:
                    data_result = data_results[uri]

                    value, unit = data_result
                    endpoint_info["value"] = value
                    if (
                        unit != endpoint_info["unit"]
                        and endpoint_info["unit"] not in CUSTOM_UNITS
                        # update the unit of the sensor if they are different, but only if we didn't assign a custom unit to the sensor
                    ):
                        _LOGGER.debug(
                            "Correcting unit for sensor %s from '%s' to '%s'",
                            unique_key,
                            endpoint_info["unit"],
                            unit,
                        )
                        endpoint_info["unit"] = unit
                    if (
                        endpoint_info["endpoint_type"] == "DEFAULT"
                        and endpoint_info["unit"] == ""
                        and str(value).isnumeric()
                    ):
                        # some sensors have an empty unit and a type of DEFAULT in the varinfo endpoint, but show a numeric value in the var endpoint
                        # those sensors are most likely unitless float sensors, so we set the unit to unitless and let the normal float sensor detection handle the rest
                        _LOGGER.debug(
                            "Updating unit for sensor %s to UNITLESS based on its value and type",
                            unique_key,
                        )
                        endpoint_info["unit"] = CUSTOM_UNIT_UNITLESS
                        endpoint_info["value"] = float(value)

                if self._is_writable(endpoint_info):
                    _LOGGER.debug("Adding %s as writable sensor", uri)
                    # this is checked separately because all writable sensors are registered as both a sensor entity and a number entity
                    # add a suffix to the unique id to make sure it is still unique in case the sensor is selected in the writable list and in the sensor list
                    writable_key = unique_key + "_writable"
                    if writable_key in writable_dict:
                        _LOGGER.debug(
                            "Skipping duplicate writable sensor %s (URI: %s, existing URI: %s)",
                            writable_key,
                            uri,
                            writable_dict[writable_key]["url"],
                        )
                    else:
                        writable_dict[writable_key] = endpoint_info

                if self._is_float_sensor(endpoint_info):
                    _LOGGER.debug("Adding %s as float sensor", uri)
                    if unique_key in float_dict:
                        _LOGGER.debug(
                            "Skipping duplicate float sensor %s (URI: %s, existing URI: %s)",
                            unique_key,
                            uri,
                            float_dict[unique_key]["url"],
                        )
                    else:
                        float_dict[unique_key] = endpoint_info
                elif self._is_switch(endpoint_info):
                    _LOGGER.debug("Adding %s as switch", uri)
                    if unique_key in switches_dict:
                        _LOGGER.debug(
                            "Skipping duplicate switch %s (URI: %s, existing URI: %s)",
                            unique_key,
                            uri,
                            switches_dict[unique_key]["url"],
                        )
                    else:
                        self._parse_switch_values(endpoint_info)
                        switches_dict[unique_key] = endpoint_info
                elif self._is_text_sensor(endpoint_info):
                    _LOGGER.debug("Adding %s as text sensor", uri)
                    if unique_key in text_dict:
                        _LOGGER.debug(
                            "Skipping duplicate text sensor %s (URI: %s, existing URI: %s)",
                            unique_key,
                            uri,
                            text_dict[unique_key]["url"],
                        )
                    else:
                        text_dict[unique_key] = endpoint_info
                else:
                    _LOGGER.debug("Not adding endpoint %s: Unknown type", uri)

            except Exception:  # noqa: BLE001
                _LOGGER.debug("Invalid endpoint %s", uri, exc_info=True)

        # Log final statistics
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
