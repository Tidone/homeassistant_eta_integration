from datetime import datetime
import logging
from typing import TypedDict

from aiohttp import ClientSession
from packaging import version
import xmltodict

from .const import CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT

_LOGGER = logging.getLogger(__name__)


class ETAValidSwitchValues(TypedDict):
    on_value: int
    off_value: int


class ETAValidWritableValues(TypedDict):
    scaled_min_value: float
    scaled_max_value: float
    scale_factor: int
    dec_places: int


class ETAEndpoint(TypedDict):
    url: str
    value: float | str
    valid_values: dict | ETAValidSwitchValues | ETAValidWritableValues | None
    friendly_name: str
    unit: str
    endpoint_type: str


class ETAError(TypedDict):
    msg: str
    priority: str
    time: datetime
    text: str
    fub: str
    host: str
    port: int


class EtaAPI:
    def __init__(self, session, host, port) -> None:
        self._session: ClientSession = session
        self._host = host
        self._port = int(port)

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
            CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
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

    def build_uri(self, suffix):
        return "http://" + self._host + ":" + str(self._port) + suffix

    def _evaluate_xml_dict(self, xml_dict, uri_dict, prefix=""):
        if type(xml_dict) == list:
            for child in xml_dict:
                self._evaluate_xml_dict(child, uri_dict, prefix)
        else:
            if "object" in xml_dict:
                child = xml_dict["object"]
                new_prefix = f"{prefix}_{xml_dict['@name']}"
                # add parent to uri_dict and evaluate childs then
                uri_dict[f"{prefix}_{xml_dict['@name']}"] = xml_dict["@uri"]
                self._evaluate_xml_dict(child, uri_dict, new_prefix)
            else:
                uri_dict[f"{prefix}_{xml_dict['@name']}"] = xml_dict["@uri"]

    async def _get_request(self, suffix):
        data = await self._session.get(self.build_uri(suffix))
        return data

    async def post_request(self, suffix, data):
        data = await self._session.post(self.build_uri(suffix), data=data)
        return data

    async def does_endpoint_exists(self):
        resp = await self._get_request("/user/menu")
        return resp.status == 200

    async def get_api_version(self):
        data = await self._get_request("/user/api")
        text = await data.text()
        return version.parse(xmltodict.parse(text)["eta"]["api"]["@version"])

    async def is_correct_api_version(self):
        eta_version = await self.get_api_version()
        required_version = version.parse("1.2")

        return eta_version >= required_version

    def _parse_data(self, data, force_number_handling=False):
        _LOGGER.debug("Parsing data %s", data)
        unit = data["@unit"]
        if unit in self._float_sensor_units or force_number_handling:
            scale_factor = int(data["@scaleFactor"])
            decimal_places = int(data["@decPlaces"])
            raw_value = float(data["#text"])
            value = raw_value / scale_factor
            value = round(value, decimal_places)
        else:
            # use default text string representation for values that cannot be parsed properly
            value = data["@strValue"]
        return value, unit

    async def get_data(self, uri, force_number_handling=False):
        data = await self._get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        return self._parse_data(data, force_number_handling)

    async def _get_data_plus_raw(self, uri):
        data = await self._get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        value, unit = self._parse_data(data)
        return value, unit, data

    async def get_menu(self):
        data = await self._get_request("/user/menu")
        text = await data.text()
        return xmltodict.parse(text)

    async def _get_raw_sensor_dict(self):
        data = await self.get_menu()
        raw_dict = data["eta"]["menu"]["fub"]
        return raw_dict

    async def _get_sensors_dict(self):
        raw_dict = await self._get_raw_sensor_dict()
        uri_dict = {}
        self._evaluate_xml_dict(raw_dict, uri_dict)
        return uri_dict

    async def get_all_sensors(
        self, force_legacy_mode, float_dict, switches_dict, text_dict, writable_dict
    ):
        if not force_legacy_mode and await self.is_correct_api_version():
            _LOGGER.debug("Get all sensors - API v1.2")
            # New version with varinfo endpoint detected
            return await self._get_all_sensors_v12(
                float_dict, switches_dict, text_dict, writable_dict
            )
        else:
            _LOGGER.debug("Get all sensors - API v1.1")
            # varinfo not available -> fall back to compatibility mode
            return await self._get_all_sensors_v11(
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

    async def _get_all_sensors_v11(
        self, float_dict, switches_dict, text_dict, writable_dict
    ):
        all_endpoints = await self._get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)
        queried_endpoints = []
        for key in all_endpoints:
            try:
                if all_endpoints[key] in queried_endpoints:
                    _LOGGER.debug("Skipping duplicate endpoint %s", all_endpoints[key])
                    # ignore duplicate endpoints
                    continue

                _LOGGER.debug("Querying endpoint %s", all_endpoints[key])

                queried_endpoints.append(all_endpoints[key])

                value, unit, raw_dict = await self._get_data_plus_raw(
                    all_endpoints[key]
                )

                endpoint_info = ETAEndpoint(
                    url=all_endpoints[key],
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
                    _LOGGER.debug("Adding as writable sensor")
                    # this is checked separately because all writable sensors are registered as both a sensor entity and a number entity
                    # add a suffix to the unique id to make sure it is still unique in case the sensor is selected in the writable list and in the sensor list
                    self._parse_valid_writable_values_v11(endpoint_info, raw_dict)
                    writable_dict[unique_key + "_writable"] = endpoint_info

                if self._is_float_sensor(endpoint_info):
                    _LOGGER.debug("Adding as float sensor")
                    float_dict[unique_key] = endpoint_info
                elif self._is_switch_v11(endpoint_info, raw_dict["#text"]):
                    _LOGGER.debug("Adding as switch")
                    self._parse_switch_values_v11(endpoint_info)
                    switches_dict[unique_key] = endpoint_info
                elif self._is_text_sensor(endpoint_info) and value != "":
                    _LOGGER.debug("Adding as text sensor")
                    # Ignore enpoints with an empty value
                    # This has to be the last branch for the above fallback to work
                    text_dict[unique_key] = endpoint_info
                else:
                    _LOGGER.debug("Not adding endpoint: Unknown type")

            except Exception:
                _LOGGER.debug("Invalid endpoint", exc_info=True)

    def _parse_switch_values(self, endpoint_info: ETAEndpoint):
        valid_values = ETAValidSwitchValues(on_value=0, off_value=0)
        for key in endpoint_info["valid_values"]:
            if key in ("Ein", "On", "Ja", "Yes"):
                valid_values["on_value"] = endpoint_info["valid_values"][key]
            elif key in ("Aus", "Off", "Nein", "No"):
                valid_values["off_value"] = endpoint_info["valid_values"][key]
        endpoint_info["valid_values"] = valid_values

    async def _get_all_sensors_v12(
        self, float_dict, switches_dict, text_dict, writable_dict
    ):
        all_endpoints = await self._get_sensors_dict()
        _LOGGER.debug("Got list of all endpoints: %s", all_endpoints)
        queried_endpoints = []
        for key in all_endpoints:
            try:
                if all_endpoints[key] in queried_endpoints:
                    _LOGGER.debug("Skipping duplicate endpoint %s", all_endpoints[key])
                    # ignore duplicate endpoints
                    continue

                _LOGGER.debug("Querying endpoint %s", all_endpoints[key])

                queried_endpoints.append(all_endpoints[key])

                fub = key.split("_")[1]
                endpoint_info = await self._get_varinfo(fub, all_endpoints[key])

                unique_key = (
                    "eta_"
                    + self._host.replace(".", "_")
                    + "_"
                    + key.lower().replace(" ", "_")
                )

                if (
                    self._is_float_sensor(endpoint_info)
                    or self._is_switch(endpoint_info)
                    or self._is_text_sensor(endpoint_info)
                ):
                    value, _ = await self.get_data(all_endpoints[key])
                    endpoint_info["value"] = value

                if self._is_writable(endpoint_info):
                    _LOGGER.debug("Adding as writable sensor")
                    # this is checked separately because all writable sensors are registered as both a sensor entity and a number entity
                    # add a suffix to the unique id to make sure it is still unique in case the sensor is selected in the writable list and in the sensor list
                    writable_dict[unique_key + "_writable"] = endpoint_info

                if self._is_float_sensor(endpoint_info):
                    _LOGGER.debug("Adding as float sensor")
                    float_dict[unique_key] = endpoint_info
                elif self._is_switch(endpoint_info):
                    _LOGGER.debug("Adding as switch")
                    self._parse_switch_values(endpoint_info)
                    switches_dict[unique_key] = endpoint_info
                elif self._is_text_sensor(endpoint_info):
                    _LOGGER.debug("Adding as text sensor")
                    text_dict[unique_key] = endpoint_info
                else:
                    _LOGGER.debug("Not adding endpoint: Unknown type")

            except Exception:
                _LOGGER.debug("Invalid endpoint", exc_info=True)

    def _is_writable(self, endpoint_info: ETAEndpoint):
        # TypedDict does not support isinstance(),
        # so we have to manually check if we hace the correct dict type
        # based on the presence of a known key
        return (
            endpoint_info["valid_values"] is not None
            and "scaled_min_value" in endpoint_info["valid_values"]
        )

    def _is_text_sensor(self, endpoint_info: ETAEndpoint):
        return endpoint_info["unit"] == "" and endpoint_info["endpoint_type"] == "TEXT"

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

    def _parse_varinfo(self, data):
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
            valid_values=valid_values,
            friendly_name=data["@fullName"],
            unit=unit,
            endpoint_type=data["type"],
        )

    async def _get_varinfo(self, fub, uri):
        data = await self._get_request("/user/varinfo/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["varInfo"]["variable"]
        endpoint_info = self._parse_varinfo(data)
        endpoint_info["url"] = uri
        endpoint_info["friendly_name"] = f"{fub} > {endpoint_info['friendly_name']}"
        return endpoint_info

    def _parse_switch_state(self, data):
        return int(data["#text"])

    async def get_switch_state(self, uri):
        data = await self._get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        return self._parse_switch_state(data)

    async def set_switch_state(self, uri, state):
        payload = {"value": state}
        uri = "/user/var/" + str(uri)
        data = await self.post_request(uri, payload)
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
        payload = {"value": value}
        if begin is not None:
            payload["begin"] = begin
            payload["end"] = end
        uri = "/user/var/" + str(uri)
        data = await self.post_request(uri, payload)
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
        data = await self._get_request("/user/errors")
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["errors"]["fub"]
        return self._parse_errors(data)
