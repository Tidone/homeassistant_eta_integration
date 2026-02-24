"""HTTP client for ETA API communication."""

import asyncio
from datetime import datetime
import logging
from typing import Any

from aiohttp import ClientSession
import xmltodict

from .types import FLOAT_SENSOR_UNITS, ETAError

_LOGGER = logging.getLogger(__name__)


class APIClient:
    """Handles low-level HTTP and XML operations for ETA API."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        max_concurrent_requests: int = 5,
        request_semaphore=None,
    ) -> None:
        """Initialize HTTP client.

        :param session: aiohttp ClientSession for HTTP requests
        :param host: Hostname or IP address of the ETA device
        :param port: Port number of the ETA API
        """
        self._session = session
        self._host = host
        self._port = int(port)
        self._max_concurrent_requests = max(1, int(max_concurrent_requests))
        self._request_semaphore = request_semaphore or asyncio.Semaphore(
            self._max_concurrent_requests
        )
        self._num_duplicates = 0

    def _build_uri(self, suffix: str) -> str:
        """Build full URI from suffix."""
        return f"http://{self._host}:{self._port}{suffix}"

    async def get_request(self, suffix: str):
        """Execute GET request."""
        async with self._request_semaphore:
            return await self._session.get(self._build_uri(suffix))

    async def post_request(self, suffix: str, data: dict):
        """Execute POST request."""
        async with self._request_semaphore:
            return await self._session.post(self._build_uri(suffix), data=data)

    def _evaluate_xml_dict(self, xml_dict, uri_dict: dict, prefix: str = ""):
        """Recursively evaluate XML dictionary and extract URIs."""
        if isinstance(xml_dict, list):
            for child in xml_dict:
                self._evaluate_xml_dict(child, uri_dict, prefix)
        elif "object" in xml_dict:
            child = xml_dict["object"]
            new_prefix = f"{prefix}_{xml_dict['@name']}"
            # Store multiple URIs per key
            if new_prefix not in uri_dict:
                uri_dict[new_prefix] = []
            else:
                self._num_duplicates += 1
            # add parent to uri_dict and then evaluate the children
            uri_dict[new_prefix].append(xml_dict["@uri"])
            self._evaluate_xml_dict(child, uri_dict, new_prefix)
        else:
            key = f"{prefix}_{xml_dict['@name']}"
            if key not in uri_dict:
                uri_dict[key] = []
            else:
                self._num_duplicates += 1
            uri_dict[key].append(xml_dict["@uri"])

    async def get_menu(self):
        """Request the menu from the ETA API."""
        data = await self.get_request("/user/menu")
        text = await data.text()
        return xmltodict.parse(text)

    async def _get_raw_sensor_dict(self):
        """Get raw sensor dictionary from menu."""
        data = await self.get_menu()
        return data["eta"]["menu"]["fub"]

    async def get_sensors_dict(self):
        """Get flattened sensor dictionary with URIs."""
        raw_dict = await self._get_raw_sensor_dict()
        uri_dict = {}
        self._evaluate_xml_dict(raw_dict, uri_dict)
        return uri_dict

    def parse_data(
        self,
        data: dict,
        force_number_handling: bool = False,
        force_string_handling: bool = False,
    ) -> tuple[float | str, str]:
        """Parse data from ETA API response.

        :param data: XML data dict
        :param force_number_handling: Force numeric parsing
        :param force_string_handling: Force string parsing
        :param float_sensor_units: List of units that should be parsed as floats
        :return: Tuple of (value, unit)
        """
        _LOGGER.debug("Parsing data %s", data)
        unit = data["@unit"]
        if not force_string_handling and (
            unit in FLOAT_SENSOR_UNITS or force_number_handling
        ):
            scale_factor = int(data["@scaleFactor"])
            # ignore the decPlaces to avoid removing any additional precision the API values may have
            # i.e. the API may send a value of 444 with scaleFactor=10, but set decPlaces=0,
            # which would remove the decimal places and set the value to 44 instead of 44.4
            raw_value = float(data["#text"])
            value = raw_value / scale_factor
        else:
            value = data["@strValue"]
        return value, unit

    async def get_data_plus_raw(self, uri: str) -> tuple[Any, str, dict]:
        """Get data with raw XML dict.

        :param uri: URI suffix
        :param float_sensor_units: List of units for float parsing
        :return: Tuple of (value, unit, raw_dict)
        """
        data = await self.get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        value, unit = self.parse_data(data)
        return value, unit, data

    async def get_data(
        self, uri, force_number_handling=False, force_string_handling=False
    ) -> tuple[float | str, str]:
        """Request the data from a API URL.

        :param uri: ETA API url suffix, like /120/1/123
        :param force_number_handling: Set to true if the data should be treated as a number even if its unit is not in the list of valid float sensors
        :param force_string_handling: Set to true if the data should be treated as a string regardless of its unit
        :return: Parsed data as a Tuple[Value, Unit]
        :rtype: Tuple[Any,str]
        """
        data = await self.get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        return self.parse_data(
            data,
            force_number_handling=force_number_handling,
            force_string_handling=force_string_handling,
        )

    async def get_all_data(self, sensor_list: dict[str, dict[str, bool]]):
        """Get all data from all endpoints.

        :param sensor_list: Dict[url, Dict[str, bool]] of sensors to query the data for
        :return: List of all data
        :rtype: Dict[str, Any]
        """
        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self.max_concurrent_requests)

        async def fetch_data_limited(
            uri: str, force_number_handling: bool, force_string_handling: bool
        ):
            """Fetch data with concurrency limit."""
            async with semaphore:
                result, _ = await self.get_data(
                    uri,
                    force_number_handling=force_number_handling,
                    force_string_handling=force_string_handling,
                )
                return result

        tasks = [
            fetch_data_limited(
                uri,
                force_number_handling=force_handlings.get(
                    "force_number_handling", False
                ),
                force_string_handling=force_handlings.get(
                    "force_string_handling", False
                ),
            )
            for uri, force_handlings in sensor_list.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data_dict: dict[str, float | str] = {}
        for uri, result in zip(sensor_list.keys(), results, strict=False):
            if isinstance(result, BaseException):
                _LOGGER.debug("Failed to get data for %s: %s", uri, str(result))
            else:
                data_dict[uri] = result

        return data_dict

    def parse_errors(self, data) -> list[ETAError]:
        """Parse error data from ETA API.

        :param data: Error data from API
        :param host: Hostname for error dict
        :param port: Port for error dict
        :return: List of ETAError dicts
        """
        errors: list[ETAError] = []
        if isinstance(data, dict):
            data = [data]

        for fub in data:
            fub_name = fub.get("@name", "")
            fub_errors = fub.get("error", [])
            if isinstance(fub_errors, dict):
                fub_errors = [fub_errors]
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

    @property
    def max_concurrent_requests(self) -> int:
        """Get max concurrent requests."""
        return self._max_concurrent_requests

    @property
    def host(self) -> str:
        """Get host."""
        return self._host

    @property
    def num_duplicates(self) -> int:
        """Get number of duplicates found."""
        return self._num_duplicates

    @num_duplicates.setter
    def num_duplicates(self, value: int):
        """Set number of duplicates."""
        self._num_duplicates = value
