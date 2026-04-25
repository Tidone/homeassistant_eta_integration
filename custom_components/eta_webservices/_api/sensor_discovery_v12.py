"""API v1.2 specific sensor discovery implementation."""

import asyncio
from datetime import datetime
import logging
import re

import xmltodict

from ..const import (  # noqa: TID252
    CUSTOM_UNIT_DATETIME,
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
            and endpoint_info["is_writable"]
        )

    def _is_valid_time(self, time: str) -> bool:
        """Check if a string is a valid time in the format "HH:MM"."""
        if time == "":
            return False

        regex = "^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
        p = re.compile(regex)
        m = re.search(p, time)

        return m is not None

    def _is_valid_datetime(self, input: str) -> bool:
        """Check if a string is a valid datetime in the format "DD.MM.YYYY HH:MM:SS"."""
        try:
            datetime.strptime(input, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            return False
        else:
            return True

    def _is_valid_timeslot_time(self, time: str) -> bool:
        """Check if a string is a valid time in the format "HH:MM"."""
        if time == "":
            return False

        regex = "^(([01]?[0-9]|2[0-3]):[0-5][0-9])|24:00$"
        p = re.compile(regex)
        m = re.search(p, time)

        return m is not None

    def _is_number(self, input: str) -> bool:
        """Check if a string can be parsed as a number."""
        try:
            float(input.replace(",", "."))
        except ValueError:
            return False
        else:
            return True

    def _parse_timeslot_value(self, value: str) -> tuple[str, str, str | None]:
        """Parse a timeslot value string.

        Args:
            value: String in format "HH:MM - HH:MM" or "HH:MM - HH:MM <number>"

        Returns:
            Tuple of (start_time, end_time, optional_value)
            where optional_value is None if not present
        """
        # Split by " - " to separate start time from the rest
        parts = value.split("-")
        if len(parts) != 2:
            return "", "", None  # Invalid format

        start_time = parts[0].strip()

        # Split the second part by space to get end time and optional value
        end_parts = parts[1].strip().split()
        end_time = end_parts[0]

        # Check if there's a third value
        optional_value = end_parts[1] if len(end_parts) > 1 else None

        return start_time, end_time, optional_value

    def _try_parse_timeslot(self, value: str) -> str | None:
        """Check if a string is a valid timeslot in the format "HH:MM - HH:MM" or "HH:MM - HH:MM <number>"."""
        start_time, end_time, optional_value = self._parse_timeslot_value(value)

        # Validate start and end times
        if not self._is_valid_timeslot_time(
            start_time
        ) or not self._is_valid_timeslot_time(end_time):
            return None

        # If there's an optional value, check if it's numeric
        if optional_value is not None and not str(optional_value).isnumeric():
            return None

        return (
            CUSTOM_UNIT_TIMESLOT
            if optional_value is None
            else CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE
        )

    def _parse_unit(
        self, varinfo_data, var_data_entry: tuple[float | str, str, dict]
    ) -> str:
        """Parse and detect custom units (v1.2 specific)."""
        var_value, var_unit, var_raw = var_data_entry
        unit = var_unit

        if (
            varinfo_data["type"] in ["DEFAULT", "IEEE-754"]
            and unit == ""
            and self._is_number(str(var_value))
        ):
            # some sensors have an empty unit and a type of DEFAULT (or IEEE-754) in the varinfo endpoint, but show a numeric value in the var endpoint
            # those sensors are most likely unitless float sensors, so we set the unit to unitless and let the normal float sensor detection handle the rest
            unit = CUSTOM_UNIT_UNITLESS

        elif unit == "" and self._is_valid_time(var_raw.get("@strValue", "")):
            _LOGGER.debug("Found time endpoint based on value format")
            unit = CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT

        elif (
            varinfo_data["type"] == "TIMESLOT"
            and unit in ["", "°C"]
            and (parsed_unit := self._try_parse_timeslot(var_raw.get("@strValue", "")))
            is not None
        ):
            if parsed_unit == CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE:
                _LOGGER.debug("Found timeslot endpoint with temperature")
            else:
                _LOGGER.debug("Found timeslot endpoint")
            unit = parsed_unit
        elif (
            unit == ""
            and varinfo_data["type"] == "DEFAULT"
            and self._is_valid_datetime(var_raw.get("@strValue", ""))
        ):
            _LOGGER.debug("Found datetime endpoint based on value format")
            unit = CUSTOM_UNIT_DATETIME

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

    def _parse_varinfo(
        self,
        data,
        fub: str,
        uri: str,
        var_data_entry: tuple[float | str, str, dict],
    ):
        """Parse varinfo XML response."""
        _LOGGER.debug("Parsing varinfo %s", data)
        valid_values = None
        unit = self._parse_unit(data, var_data_entry)

        # The validValues node can be in multiple formats:
        # 1) A list of discrete valid values, e.g. for a switch:
        # <validValues>
        #   <value strValue="Ein">1</value>
        #   <value strValue="Aus">0</value>
        # </validValues>
        # 2) A min, def, and max value, e.g. for a writable number:
        # <validValues>
        #   <min strValue="0" unit="°C">0</min>
        #   <def strValue="0" unit="°C">0</def>
        #   <max strValue="100" unit="°C">100</max>
        # </validValues>
        # 3) A min , def, and max value, but further divided into begin and end timeslots with an optional value, e.g. for a writable timeslot sensors:
        # <validValues>
        #   <min strValue="00:00 - 00:00 0" unit="°C">
        #     <begin>0</begin>
        #     <end>0</end>
        #     <value>0</value>
        #   </min>
        #   <def strValue="00:00 - 24:00 55" unit="°C">
        #     <begin>0</begin>
        #     <end>96</end>
        #     <value>550</value>
        #   </def>
        #   <max strValue="24:00 - 24:00 90" unit="°C">
        #     <begin>96</begin>
        #     <end>96</end>
        #     <value>900</value>
        #   </max>
        # </validValues>
        # or
        # <validValues>
        #   <min strValue="00:00 - 00:00" unit="">
        #     <begin>0</begin>
        #     <end>0</end>
        #   </min>
        #   <def strValue="00:00 - 24:00" unit="">
        #     <begin>0</begin>
        #     <end>96</end>
        #   </def>
        #   <max strValue="24:00 - 24:00" unit="">
        #     <begin>96</begin>
        #     <end>96</end>
        #   </max>
        # </validValues>
        if data.get("validValues") is not None and "value" in data["validValues"]:
            # Parse discrete valid values into a dict, e.g. {"Ein": 1, "Aus": 0}
            values = data["validValues"]["value"]
            valid_values = dict(
                zip(
                    [k["@strValue"] for k in values],
                    [int(v["#text"]) for v in values],
                    strict=False,
                )
            )
        elif (
            data.get("validValues") is not None
            and "min" in data["validValues"]
            and "#text" in data["validValues"]["min"]
            # check if the unit is in the list of writable sensor units or if the type is DEFAULT with an empty unit, which is an indicator of a unitless writable sensor
            # this check may be inaccurate, but we can reject invalid writable sensors later when we have determined the final unit (which is done in _is_writable)
            and (
                unit in WRITABLE_SENSOR_UNITS
                or ("type" in data and data["type"] == "DEFAULT" and unit == "")
            )
            # we handle this unit separately below
            and unit != CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        ):
            # Parse the min and max values for writable sensors
            min_value = data["validValues"]["min"]["#text"]
            max_value = data["validValues"]["max"]["#text"]
            valid_values = self._createETAValidWritableValues(
                raw_min_value=min_value,
                raw_max_value=max_value,
                scale_factor=int(data["@scaleFactor"]),
                dec_places=int(data["@decPlaces"]),
            )
        if (
            unit == CUSTOM_UNIT_TIMESLOT
            and data.get("validValues") is not None
            and "min" in data["validValues"]
            and "max" in data["validValues"]
            and "begin" in data["validValues"]["min"]
            and "end" in data["validValues"]["max"]
        ):
            if (min_value := int(data["validValues"]["min"]["begin"])) == 0 and (
                max_value := int(data["validValues"]["max"]["end"])
            ) == 24 * 60 / 15:
                # store the min and max value of the timeslots for this unit
                valid_values = ETAValidWritableValues(
                    scaled_min_value=0,
                    scaled_max_value=96,
                    scale_factor=1,
                    dec_places=0,
                )

            else:
                _LOGGER.warning(
                    "Invalid timeslot validValues for %s: expected begin=0 and end=96, got begin=%s and end=%s",
                    uri,
                    data["validValues"]["min"]["begin"],
                    data["validValues"]["max"]["end"],
                )
        elif (
            unit == CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE
            and data.get("validValues") is not None
            and "min" in data["validValues"]
            and "max" in data["validValues"]
            and "value" in data["validValues"]["min"]
            and "begin" in data["validValues"]["min"]
            and "end" in data["validValues"]["max"]
        ):
            if (
                int(data["validValues"]["min"]["begin"]) == 0
                and int(data["validValues"]["max"]["end"]) == 24 * 60 / 15
            ):
                # store the min and max value of the temperature for this unit
                # the min and max timeslot values for the timeslots don't have to be stored because they are always the same for this unit (0 and 96 respectively)
                min_value = data["validValues"]["min"]["value"]
                max_value = data["validValues"]["max"]["value"]
                valid_values = self._createETAValidWritableValues(
                    raw_min_value=min_value,
                    raw_max_value=max_value,
                    scale_factor=int(data["@scaleFactor"]),
                    dec_places=int(data["@decPlaces"]),
                )
            else:
                _LOGGER.warning(
                    "Invalid timeslot validValues for %s: expected begin=0 and end=96, got begin=%s and end=%s",
                    uri,
                    data["validValues"]["min"]["begin"],
                    data["validValues"]["max"]["end"],
                )
        elif (
            unit == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
            and data.get("validValues") is not None
            and "min" in data["validValues"]
            and "#text" in data["validValues"]["min"]
        ):
            if (min_value := int(data["validValues"]["min"]["#text"])) == 0 and (
                max_value := int(data["validValues"]["max"]["#text"])
            ) == 24 * 60 - 1:
                valid_values = self._createETAValidWritableValues(
                    raw_min_value=min_value,
                    raw_max_value=max_value,
                    scale_factor=int(data["@scaleFactor"]),
                    dec_places=int(data["@decPlaces"]),
                )
            else:
                _LOGGER.warning(
                    "Invalid validValues for %s: expected min=0 and max=1439, got min=%s and max=%s",
                    uri,
                    data["validValues"]["min"]["#text"],
                    data["validValues"]["max"]["#text"],
                )

        var_value, _, raw_var_data = var_data_entry
        if unit in CUSTOM_UNITS:
            value = raw_var_data["@strValue"]
        else:
            value = var_value
        if unit == CUSTOM_UNIT_UNITLESS:
            value = float(str(value).replace(",", "."))

        return ETAEndpoint(
            valid_values=valid_values,
            friendly_name=f"{fub} > {data['@fullName']}",
            unit=unit,
            endpoint_type=data["type"],
            url=uri,
            value=value,
            is_writable=data.get("@isWritable") == "1",
            is_invalid=raw_var_data.get("@strValue") == "xxx",
        )

    async def _fetch_varinfo_raw(self, fub: str, uri: str) -> dict:
        """Fetch raw varinfo variable dict from API. Raises on network error or error node."""
        data = await self._http.get_request("/user/varinfo/" + str(uri))
        text = await data.text()
        parsed = xmltodict.parse(text)["eta"]
        if "error" in parsed:
            raise ValueError(f"varinfo returned error for {uri}: {parsed['error']}")
        return parsed["varInfo"]["variable"]

    async def _sanitize_duplicate_nodes(
        self,
        all_endpoints: dict[str, list[str]],
        endpoint_infos: dict[str, ETAEndpoint],
        deduplicated_uris: dict[str, str],
        var_data: dict[str, tuple[str | float, str, dict]],
    ) -> int:
        """Sanitize duplicate nodes by removing URIs that return invalid data.

        For nodes with multiple URIs, this function tests each URI using the
        pre-fetched var data. If exactly one URI returns valid data and all others
        returned 'xxx', were missing from var_data, or raised exceptions, the
        invalid URIs are removed from endpoint_infos.

        Args:
            all_endpoints: Maps sensor keys to lists of URIs
            endpoint_infos: Maps URIs to their endpoint metadata (modified in-place)
            deduplicated_uris: Maps URIs to their sensor keys (modified in-place)
            var_data: Pre-fetched var endpoint results, maps URI to (value, unit)

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

        # Phase 2: Map pre-fetched var data to duplicate URIs
        all_uris_to_test = [uri for _, uris in nodes_to_check for uri in uris]
        _LOGGER.debug(
            "Evaluating %d URIs for validation using pre-fetched var data",
            len(all_uris_to_test),
        )

        # URIs missing from var_data had a failed fetch — treat them like exceptions
        uri_to_result = {uri: var_data.get(uri) for uri in all_uris_to_test}

        # Phase 3: Evaluate each node and remove invalid URIs
        uris_to_remove = []
        for key, uris in nodes_to_check:
            valid_uris = []
            invalid_uris = []

            for uri in uris:
                result = uri_to_result[uri]

                # None means the URI was absent from var_data (fetch failed)
                if result is None or isinstance(result, BaseException):
                    _LOGGER.debug(
                        "URI %s has no valid var data (fetch failed or missing)", uri
                    )
                    invalid_uris.append(uri)
                else:
                    # Result is a tuple (value, unit, raw_dict)
                    _, _, raw_dict = result
                    if raw_dict["@strValue"] in ("xxx", "---"):
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
                # rename the keys of the valid URIs to make sure they are unique
                # by adding a suffix like the URI to the key in deduplicated_uris
                for uri in valid_uris:
                    deduplicated_uris[uri] = f"{key}__dedup_{uri.replace('/', '_')}"

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
        self, float_dict, switches_dict, text_dict, writable_dict, pending_dict
    ):
        """Enumerate all sensors using v1.2 methods."""
        self._emit_progress("Loading endpoint list", 0.05)
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
        self._emit_progress(f"Loaded {len(deduplicated_uris)} unique endpoints", 0.1)

        async def fetch_varinfo_limited(uri, key):
            try:
                return uri, await self._fetch_varinfo_raw(key.split("_")[1], uri)
            except Exception as err:  # noqa: BLE001
                return uri, err

        # Phase 2: Fetch raw varinfo for all URIs
        # This takes WAY longer than the calls to get_data() below
        # Runtime for this section: 170s
        # Runtime for the get_data() section below: 7s
        varinfo_tasks = [
            asyncio.create_task(fetch_varinfo_limited(uri, key))
            for uri, key in deduplicated_uris.items()
        ]

        raw_varinfo: dict[str, dict] = {}
        total_varinfo_tasks = len(varinfo_tasks)
        varinfo_progress_step = (
            max(1, total_varinfo_tasks // 20) if total_varinfo_tasks else 1
        )

        for completed_varinfo_tasks, task in enumerate(
            asyncio.as_completed(varinfo_tasks), start=1
        ):
            uri, result = await task
            if isinstance(result, Exception):
                _LOGGER.debug("Failed to get varinfo for %s: %s", uri, str(result))
            else:
                raw_varinfo[uri] = result
            if (
                completed_varinfo_tasks == total_varinfo_tasks
                or completed_varinfo_tasks % varinfo_progress_step == 0
            ):
                progress = 0.1 + (
                    0.45 * completed_varinfo_tasks / max(total_varinfo_tasks, 1)
                )
                self._emit_progress(
                    f"Reading endpoint metadata {completed_varinfo_tasks}/{total_varinfo_tasks}",
                    progress,
                )

        async def fetch_data_limited(uri):
            try:
                return uri, await self._http.get_data_plus_raw(uri)
            except Exception as err:  # noqa: BLE001
                return uri, err

        # Phase 3: Fetch var data for all valid varinfo nodes
        data_tasks = [
            asyncio.create_task(fetch_data_limited(uri)) for uri in raw_varinfo
        ]

        var_data: dict[str, tuple[float | str, str, dict]] = {}
        total_data_tasks = len(data_tasks)
        data_progress_step = max(1, total_data_tasks // 20) if total_data_tasks else 1
        self._emit_progress("Reading endpoint values", 0.55)

        for completed_data_tasks, task in enumerate(
            asyncio.as_completed(data_tasks), start=1
        ):
            uri, result = await task
            if isinstance(result, Exception):
                _LOGGER.debug("Failed to get data for %s: %s", uri, str(result))
            else:
                var_data[uri] = result
            if (
                completed_data_tasks == total_data_tasks
                or completed_data_tasks % data_progress_step == 0
            ):
                progress = 0.55 + (
                    0.3 * completed_data_tasks / max(total_data_tasks, 1)
                )
                self._emit_progress(
                    f"Reading endpoint values {completed_data_tasks}/{total_data_tasks}",
                    progress,
                )

        # For nodes where data fetch failed (e.g. permission error), inject a fallback
        # so they still reach Phase 4 and can be classified as pending.
        for uri, raw in raw_varinfo.items():
            if uri not in var_data:
                var_data[uri] = ("---", raw.get("@unit", ""), {"@strValue": "---"})

        # Phase 4: Parse raw varinfo into ETAEndpoint objects and apply var data
        self._emit_progress("Parsing endpoint metadata", 0.85)
        endpoint_infos: dict[str, ETAEndpoint] = {}
        for uri, raw in raw_varinfo.items():
            key = deduplicated_uris[uri]
            fub = key.split("_")[1]
            try:
                endpoint_infos[uri] = self._parse_varinfo(
                    raw, fub, uri, var_data_entry=var_data[uri]
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Failed to parse varinfo for %s", uri, exc_info=True)

        # Phase 5: Sanitize duplicate nodes using the pre-fetched var data
        self._emit_progress("Resolving duplicate endpoints", 0.88)
        removed_count = await self._sanitize_duplicate_nodes(
            all_endpoints, endpoint_infos, deduplicated_uris, var_data
        )
        if removed_count > 0:
            _LOGGER.info("Removed %d invalid URIs from duplicate nodes", removed_count)

        self._emit_progress("Classifying discovered entities", 0.95)
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
                elif (
                    endpoint_info["unit"] == ""
                    and (
                        endpoint_info["endpoint_type"] == "DEFAULT"
                        or endpoint_info["endpoint_type"] == "IEEE-754"
                    )
                    # ignore sensors with an empty value or "xxx" — both indicate invalid sensors
                    and endpoint_info["value"] != ""
                    and endpoint_info["value"] != "xxx"
                ):
                    _LOGGER.debug(
                        "Found pending endpoint %s, adding to pending_dict", uri
                    )
                    pending_dict[unique_key] = endpoint_info
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
        self._emit_progress(
            f"Done: {valid_endpoints} entities discovered",
            1.0,
        )
