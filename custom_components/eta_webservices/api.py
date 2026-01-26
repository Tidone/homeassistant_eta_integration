"""Handle all low-level API calls for ETA Sensors."""

import asyncio
from datetime import datetime
import logging
from typing import TypedDict

from aiohttp import ClientSession
from packaging import version
import xmltodict

from .const import CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT

# Make sure to update _get_all_sensors_v12() if a new custom unit is added

_LOGGER = logging.getLogger(__name__)


class ETAValidSwitchValues(TypedDict):
    """Dict providing the raw values for ETA switch sensors."""

    on_value: int
    off_value: int


class ETAValidWritableValues(TypedDict):
    """Dict providing the necessary metadata for ETA writable sensors."""

    scaled_min_value: float
    scaled_max_value: float
    scale_factor: int
    dec_places: int


class ETAEndpoint(TypedDict):
    """Dict providing metadata for a ETA sensor."""

    url: str
    value: float | str
    valid_values: dict | ETAValidSwitchValues | ETAValidWritableValues | None
    friendly_name: str
    unit: str
    endpoint_type: str


class ETAError(TypedDict):
    """Dict encapsulating all available data of an ETA Error."""

    msg: str
    priority: str
    time: datetime
    text: str
    fub: str
    host: str
    port: int


class EtaAPI:
    """Class which handles all low-level communication with the ETA terminal via the ETA REST API."""

    def __init__(self, session, host, port) -> None:  # noqa: D107
        self._session: ClientSession = session
        self._host = host
        self._port = int(port)
        # 5 concurrent requests seem to be the sweetspot between speed and stability
        # More parallel requests are only very slightly faster (in the order of seconds), with the downside that the ETA user interface becomes very laggy
        self._max_concurrent_requests = 5

        self._float_sensor_units = [
            "%",
            "A",
            "Hz",
            "Ohm",
            "Pa",
            "U/min",
            "V",
            "W",
            "W/m²",
            "bar",
            "kW",
            "kWh",
            "kg",
            "l",
            "l/min",
            "mV",
            "m²",
            "s",
            "°C",
            "%rH",
        ]

        self._writable_sensor_units = [
            "%",
            "°C",
            "kg",
            CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
        ]
        self._default_valid_writable_values = {
            "%": ETAValidWritableValues(
                scaled_min_value=-100,
                scaled_max_value=100,
                scale_factor=1,
                dec_places=0,
            ),
            "°C": ETAValidWritableValues(
                scaled_min_value=-100,
                scaled_max_value=200,
                scale_factor=1,
                dec_places=0,
            ),
            "kg": ETAValidWritableValues(
                scaled_min_value=-100000,
                scaled_max_value=100000,
                scale_factor=1,
                dec_places=0,
            ),
        }

    def _build_uri(self, suffix):
        return "http://" + self._host + ":" + str(self._port) + suffix

    def _evaluate_xml_dict(self, xml_dict, uri_dict, prefix=""):
        if isinstance(xml_dict, list):
            for child in xml_dict:
                self._evaluate_xml_dict(child, uri_dict, prefix)
        elif "object" in xml_dict:
            child = xml_dict["object"]
            new_prefix = f"{prefix}_{xml_dict['@name']}"
            # add parent to uri_dict and evaluate childs then
            uri_dict[f"{prefix}_{xml_dict['@name']}"] = xml_dict["@uri"]
            self._evaluate_xml_dict(child, uri_dict, new_prefix)
        else:
            uri_dict[f"{prefix}_{xml_dict['@name']}"] = xml_dict["@uri"]

    async def _get_request(self, suffix):
        return await self._session.get(self._build_uri(suffix))

    async def _post_request(self, suffix, data):
        return await self._session.post(self._build_uri(suffix), data=data)

    async def does_endpoint_exists(self):
        """Returns true if the ETA API is accessible."""
        resp = await self._get_request("/user/menu")
        return resp.status == 200

    async def get_api_version(self):
        """Get the version of the ETA API as a raw string.

        :return: Version of the ETA API
        :rtype: Version
        """
        data = await self._get_request("/user/api")
        text = await data.text()
        return version.parse(xmltodict.parse(text)["eta"]["api"]["@version"])

    async def is_correct_api_version(self):
        """Returns true if the ETA API version is v1.2 or higher."""
        eta_version = await self.get_api_version()
        required_version = version.parse("1.2")

        return eta_version >= required_version

    def _parse_data(self, data, force_number_handling=False):
        _LOGGER.debug("Parsing data %s", data)
        unit = data["@unit"]
        if unit in self._float_sensor_units or force_number_handling:
            scale_factor = int(data["@scaleFactor"])
            # ignore the decPlaces to avoid removing any additional precision the API values have
            # i.e. the API may send a value of 444 with scaleFactor=10, but set decPlaces=0,
            # which would remove the decimal places and set the value to 44 instead of 44.4
            raw_value = float(data["#text"])
            value = raw_value / scale_factor
        else:
            # use default text string representation for values that cannot be parsed properly
            value = data["@strValue"]
        return value, unit

    async def get_data(self, uri, force_number_handling=False):
        """Request the data from a API URL.

        :param uri: ETA API url suffix, like /120/1/123
        :param force_number_handling: Set to true if the data should be treated as a number even if its unit is not in the list of valid float sensors
        :return: Parsed data as a Tuple[Value, Unit]
        :rtype: Tuple[Any,str]
        """
        data = await self._get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        return self._parse_data(data, force_number_handling)

    async def get_all_data(self):
        """Get all data from all endpoints.

        :return: List of all data
        :rtype: Dict[str, Any]
        """
        all_endpoints = await self._get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)

        # Deduplicate endpoints
        deduplicated_uris = {}
        for key, uri in all_endpoints.items():
            if uri not in deduplicated_uris:
                deduplicated_uris[uri] = key

        _LOGGER.debug("Got %d unique endpoints", len(deduplicated_uris))

        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self._max_concurrent_requests)

        async def fetch_data_limited(uri):
            """Fetch data with concurrency limit."""
            async with semaphore:
                return await self.get_data(uri)

        # Fetch all data concurrently with limit
        data_tasks = [fetch_data_limited(uri) for uri in deduplicated_uris]

        data_results = await asyncio.gather(*data_tasks, return_exceptions=True)

        # Map results back to URIs
        return dict(zip(deduplicated_uris.keys(), data_results, strict=False))

    async def _get_data_plus_raw(self, uri):
        data = await self._get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        value, unit = self._parse_data(data)
        return value, unit, data

    async def get_menu(self):
        """Request the menu from the ETA API, which includes links to all possible sensors."""
        data = await self._get_request("/user/menu")
        text = await data.text()
        return xmltodict.parse(text)

    async def _get_raw_sensor_dict(self):
        data = await self.get_menu()
        return data["eta"]["menu"]["fub"]

    async def _get_sensors_dict(self):
        raw_dict = await self._get_raw_sensor_dict()
        uri_dict = {}
        self._evaluate_xml_dict(raw_dict, uri_dict)
        return uri_dict

    async def get_all_sensors(
        self, force_legacy_mode, float_dict, switches_dict, text_dict, writable_dict
    ):
        """Enumerate all possible sensors on the ETA API.

        :param force_legacy_mode: Set to true to force the use of the old API mode
        :param float_dict: Dictionary which will be filled with all float sensors
        :param switches_dict: Dictionary which will be filled with all switch sensors
        :param text_dict: Dictionary which will be filled with all text sensors
        :param writable_dict: Dictionary which will be filled with all writable sensors
        """
        if not force_legacy_mode and await self.is_correct_api_version():
            _LOGGER.debug("Get all sensors - API v1.2")
            # New version with varinfo endpoint detected
            await self._get_all_sensors_v12(
                float_dict, switches_dict, text_dict, writable_dict
            )
        else:
            _LOGGER.debug("Get all sensors - API v1.1")
            # varinfo not available -> fall back to compatibility mode
            await self._get_all_sensors_v11(
                float_dict, switches_dict, text_dict, writable_dict
            )

    def _get_friendly_name(self, key: str):
        components = key.split("_")[1:]  # The first part ist always empty
        return " > ".join(components)

    def _is_switch_v11(self, endpoint_info: ETAEndpoint, raw_value: str):
        if endpoint_info["unit"] == "" and raw_value in ("1802", "1803"):
            return True
        return False

    def _parse_switch_values_v11(self, endpoint_info: ETAEndpoint):
        endpoint_info["valid_values"] = ETAValidSwitchValues(
            on_value=1803, off_value=1802
        )

    def _is_writable_v11(self, endpoint_info: ETAEndpoint):
        # API v1.1 lacks the necessary function to query detailed info about the endpoint
        # that's why we just check the unit to see if it is in the list of acceptable writable sensor units
        if endpoint_info["unit"] in self._writable_sensor_units:
            return True
        return False

    def _parse_valid_writable_values_v11(
        self, endpoint_info: ETAEndpoint, raw_dict: dict
    ):
        # API v1.1 lacks the necessary function to query detailed info about the endpoint
        # that's why we have to assume sensible valid ranges for the endpoints based on their unit
        endpoint_info["valid_values"] = self._default_valid_writable_values[
            endpoint_info["unit"]
        ]
        endpoint_info["valid_values"]["dec_places"] = int(raw_dict["@decPlaces"])
        endpoint_info["valid_values"]["scale_factor"] = int(raw_dict["@scaleFactor"])

    # runlength w/o optimizations: 78s
    # runlength w/ optimizations (sem=1): 77s
    # runlength w/ optimizations (sem=2): 43s
    # runlength w/ optimizations (sem=3): 25s
    # runlength w/ optimizations (sem=4): 19s
    # runlength w/ optimizations (sem=5): 15s
    # runlength w/ optimizations (sem=10): 7s
    #  len(writable_dict) = 149
    #  len(float_dict) = 244
    #  len(switches_dict) = 29
    #  len(text_dict) = 241

    async def _get_all_sensors_v11(
        self, float_dict, switches_dict, text_dict, writable_dict
    ):
        all_endpoints = await self._get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)

        # Deduplicate endpoints
        # INFO: The key and value fields are flipped between this and all_endpoints
        # to be able to easily check if a uri is already in the dict
        deduplicated_uris = {}
        for key, uri in all_endpoints.items():
            if uri not in deduplicated_uris:
                deduplicated_uris[uri] = key

        _LOGGER.debug("Got %d unique endpoints", len(deduplicated_uris))

        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self._max_concurrent_requests)

        async def fetch_data_limited(uri):
            """Fetch data with concurrency limit."""
            async with semaphore:
                return await self._get_data_plus_raw(uri)

        # Fetch all data concurrently with limit
        data_tasks = [fetch_data_limited(uri) for uri in deduplicated_uris]

        data_results = await asyncio.gather(*data_tasks, return_exceptions=True)

        # Map results back to URIs, filtering out exceptions
        endpoint_data: dict[str, tuple[float | str, str, dict]] = {}
        for uri, result in zip(deduplicated_uris.keys(), data_results, strict=False):
            if isinstance(result, Exception):
                _LOGGER.debug("Failed to get data for %s: %s", uri, str(result))
            else:
                endpoint_data[uri] = result  # pyright: ignore[reportArgumentType]

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
                    + self._host.replace(".", "_")
                    + "_"
                    + key.lower().replace(" ", "_")
                )

                if self._is_writable_v11(endpoint_info):
                    _LOGGER.debug("Adding %s as writable sensor", uri)
                    # this is checked separately because all writable sensors are registered as both a sensor entity and a number entity
                    # add a suffix to the unique id to make sure it is still unique in case the sensor is selected in the writable list and in the sensor list
                    self._parse_valid_writable_values_v11(endpoint_info, raw_dict)
                    writable_dict[unique_key + "_writable"] = endpoint_info

                if self._is_float_sensor(endpoint_info):
                    _LOGGER.debug("Adding %s as float sensor", uri)
                    float_dict[unique_key] = endpoint_info
                elif self._is_switch_v11(endpoint_info, raw_dict["#text"]):
                    _LOGGER.debug("Adding %s as switch", uri)
                    self._parse_switch_values_v11(endpoint_info)
                    switches_dict[unique_key] = endpoint_info
                elif self._is_text_sensor(endpoint_info) and value != "":
                    _LOGGER.debug("Adding %s as text sensor", uri)
                    # Ignore enpoints with an empty value
                    # This has to be the last branch for the above fallback to work
                    text_dict[unique_key] = endpoint_info
                else:
                    _LOGGER.debug("Not adding endpoint %s: Unknown type", uri)

            except Exception:  # noqa: BLE001
                _LOGGER.debug("Invalid endpoint %s", uri, exc_info=True)

    def _parse_switch_values(self, endpoint_info: ETAEndpoint):
        valid_values = ETAValidSwitchValues(on_value=0, off_value=0)
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

    # runlength w/o optimizations: 326s
    # runlength w/ optimizations (sem=1): 330s
    # runlength w/ optimizations (sem=2): 218s
    # runlength w/ optimizations (sem=3): 193s
    # runlength w/ optimizations (sem=4): 187s
    # runlength w/ optimizations (sem=5): 184s
    # runlength w/ optimizations (sem=10): 177s
    #  len(writable_dict) = 74
    #  len(float_dict) = 244
    #  len(switches_dict) = 40
    #  len(text_dict) = 138

    async def _get_all_sensors_v12(
        self, float_dict, switches_dict, text_dict, writable_dict
    ):
        all_endpoints = await self._get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)

        # Deduplicate endpoints
        # INFO: The key and value fields are flipped between this and all_endpoints
        # to be able to easily check if a uri is already in the dict
        deduplicated_uris = {}
        for key, uri in all_endpoints.items():
            if uri not in deduplicated_uris:
                deduplicated_uris[uri] = key

        _LOGGER.debug("Got %d unique endpoints", len(deduplicated_uris))

        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self._max_concurrent_requests)

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

        async def fetch_data_limited(uri):
            async with semaphore:
                return await self.get_data(uri)

        # Fetch all needed data concurrently
        data_results: dict[str, tuple[float | str, str]] = {}
        if needs_data:
            data_tasks = [fetch_data_limited(uri) for uri in needs_data]
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
                    + self._host.replace(".", "_")
                    + "_"
                    + key.lower().replace(" ", "_")
                )

                if uri in data_results:
                    data_result = data_results[uri]

                    value, unit = data_result
                    endpoint_info["value"] = value
                    if (
                        unit != endpoint_info["unit"]
                        and endpoint_info["unit"] != CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
                        # update the unit of the sensor if they are different, but only if we didn't assign a custom unit to the sensor
                    ):
                        _LOGGER.debug(
                            "Correcting unit for sensor from '%s' to '%s'",
                            endpoint_info["unit"],
                            unit,
                        )
                        endpoint_info["unit"] = unit

                if self._is_writable(endpoint_info):
                    _LOGGER.debug("Adding %s as writable sensor", uri)
                    # this is checked separately because all writable sensors are registered as both a sensor entity and a number entity
                    # add a suffix to the unique id to make sure it is still unique in case the sensor is selected in the writable list and in the sensor list
                    writable_dict[unique_key + "_writable"] = endpoint_info

                if self._is_float_sensor(endpoint_info):
                    _LOGGER.debug("Adding %s as float sensor", uri)
                    float_dict[unique_key] = endpoint_info
                elif self._is_switch(endpoint_info):
                    _LOGGER.debug("Adding %s as switch", uri)
                    self._parse_switch_values(endpoint_info)
                    switches_dict[unique_key] = endpoint_info
                elif self._is_text_sensor(endpoint_info):
                    _LOGGER.debug("Adding %s as text sensor", uri)
                    text_dict[unique_key] = endpoint_info
                else:
                    _LOGGER.debug("Not adding endpoint %s: Unknown type", uri)

            except Exception:  # noqa: BLE001
                _LOGGER.debug("Invalid endpoint %s", uri, exc_info=True)

    def _is_writable(self, endpoint_info: ETAEndpoint):
        # TypedDict does not support isinstance(),
        # so we have to manually check if we hace the correct dict type
        # based on the presence of a known key
        return (
            endpoint_info["valid_values"] is not None
            and "scaled_min_value" in endpoint_info["valid_values"]
        )

    def _is_text_sensor(self, endpoint_info: ETAEndpoint):
        return endpoint_info["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT or (
            endpoint_info["unit"] == "" and endpoint_info["endpoint_type"] == "TEXT"
        )

    def _is_float_sensor(self, endpoint_info: ETAEndpoint):
        return endpoint_info["unit"] in self._float_sensor_units

    def _is_switch(self, endpoint_info: ETAEndpoint):
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

    def _parse_unit(self, data):
        unit = data["@unit"]
        if unit == "":
            if (
                "validValues" in data
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
        return unit

    def _parse_varinfo(self, data, fub: str, uri: str):
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
            and unit in self._writable_sensor_units
        ):
            min_value = data["validValues"]["min"]["#text"]
            max_value = data["validValues"]["max"]["#text"]
            scale_factor = int(data["@scaleFactor"])
            dec_places = int(data["@decPlaces"])

            min_value = round(float(min_value) / scale_factor, dec_places)
            max_value = round(float(max_value) / scale_factor, dec_places)
            valid_values = ETAValidWritableValues(
                scaled_min_value=min_value,
                scaled_max_value=max_value,
                scale_factor=scale_factor,
                dec_places=dec_places,
            )

        return ETAEndpoint(
            url=uri,
            valid_values=valid_values,
            friendly_name=f"{fub} > {data['@fullName']}",
            unit=unit,
            endpoint_type=data["type"],
            value=0,
        )

    async def _get_varinfo(self, fub, uri):
        data = await self._get_request("/user/varinfo/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["varInfo"]["variable"]
        return self._parse_varinfo(data, fub, uri)

    def _parse_switch_state(self, data):
        return int(data["#text"])

    async def get_switch_state(self, uri):
        """Get the raw state of a switch sensor.

        :param uri: URL suffix of the switch sensor
        :return: Raw switch value, like 1802
        :rtype: int
        """
        data = await self._get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        return self._parse_switch_state(data)

    async def set_switch_state(self, uri, state):
        """Set the state of a switch sensor.

        :param uri: URL suffix of the switch sensor
        :param state: Raw switch state value, like 1802
        :return: True on success
        :rtype: boolean
        """
        payload = {"value": state}
        uri = "/user/var/" + str(uri)
        data = await self._post_request(uri, payload)
        text = await data.text()
        data = xmltodict.parse(text)["eta"]
        if "success" in data:
            return True

        _LOGGER.error(
            "ETA Integration - could not set state of switch. Got invalid result: %s",
            text,
        )
        return False

    async def write_endpoint(self, uri, value, begin=None, end=None):
        """Writa a raw value to a writable sensor.

        :param uri: URL suffix of the writable sensor
        :param value: Raw value of the sensor
        :param begin: Optional begin time, used for some sensors
        :param end: Optional end time, used for some sensors
        :return: True on success
        :rtype: boolean
        """
        payload = {"value": value}
        if begin is not None:
            payload["begin"] = begin
            payload["end"] = end
        uri = "/user/var/" + str(uri)
        data = await self._post_request(uri, payload)
        text = await data.text()
        data = xmltodict.parse(text)["eta"]
        if "success" in data:
            return True
        if "error" in data:
            _LOGGER.error(
                "ETA Integration - could not set write value to endpoint. Terminal returned: %s",
                data["error"],
            )
            return False

        _LOGGER.error(
            "ETA Integration - could not set write value to endpoint. Got invalid result: %s",
            text,
        )
        return False

    def _parse_errors(self, data):
        errors = []
        if isinstance(data, dict):
            data = [
                data,
            ]

        for fub in data:
            fub_name = fub.get("@name", "")
            fub_errors = fub.get("error", [])
            if isinstance(fub_errors, dict):
                fub_errors = [
                    fub_errors,
                ]
            errors.extend(
                ETAError(
                    msg=error["@msg"],
                    priority=error["@priority"],
                    time=datetime.strptime(error["@time"], "%Y-%m-%d %H:%M:%S")
                    if error.get("@time", "") != ""
                    else datetime.now(),
                    text=error["#text"],
                    fub=fub_name,
                    host=self._host,
                    port=self._port,
                )
                for error in fub_errors
            )

        return errors

    async def get_errors(self):
        """Request a list of active errors from the ETA system.

        :return: List of active errors
        :rtype: List[ETAError]
        """
        data = await self._get_request("/user/errors")
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["errors"]["fub"]
        return self._parse_errors(data)
