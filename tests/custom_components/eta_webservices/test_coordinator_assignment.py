"""Tests that verify every entity is fed by exactly one coordinator."""

import pytest
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eta_webservices.coordinator import (
    ETAErrorUpdateCoordinator,
    ETASensorUpdateCoordinator,
    ETAWritableUpdateCoordinator,
)
from custom_components.eta_webservices.entity import EtaErrorEntity
from custom_components.eta_webservices.number import (
    async_setup_entry as number_async_setup_entry,
)
from custom_components.eta_webservices.sensor import (
    async_setup_entry as sensor_async_setup_entry,
)
from custom_components.eta_webservices.switch import (
    async_setup_entry as switch_async_setup_entry,
)
from custom_components.eta_webservices.time import (
    async_setup_entry as time_async_setup_entry,
)
from custom_components.eta_webservices.const import (
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    DOMAIN,
    ERROR_UPDATE_COORDINATOR,
    FLOAT_DICT,
    SENSOR_UPDATE_COORDINATOR,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
)


def _make_api_mock(float_dict, text_dict, writable_dict, switch_dict):
    """Return a mock EtaAPI instance whose methods respond with fixture-derived data.

    get_all_data uses side_effect so it only returns data for the URIs actually
    queried — this correctly returns an empty dict when the query dict is empty
    (e.g. when chosen_writable_sensors is []).
    """
    uri_to_value = {}
    for info in float_dict.values():
        v = info["value"]
        uri_to_value[info["url"]] = float(v) if isinstance(v, (int, float)) else 0.0
    for info in text_dict.values():
        uri_to_value[info["url"]] = str(info["value"])
    for info in writable_dict.values():
        # Time sensors expect an ISO time string; numeric sensors can use 0.
        if info["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT:
            uri_to_value[info["url"]] = "00:00"
        else:
            uri_to_value[info["url"]] = 0

    uri_to_switch = {
        info["url"]: int(info["valid_values"]["off_value"])
        for info in switch_dict.values()
        if isinstance(info.get("valid_values"), dict)
    }

    mock_api = AsyncMock()
    mock_api.get_all_data = AsyncMock(
        side_effect=lambda q: {
            uri: uri_to_value[uri] for uri in q if uri in uri_to_value
        }
    )
    mock_api.get_all_switch_states = AsyncMock(
        side_effect=lambda uris: {uri: uri_to_switch.get(uri, 1802) for uri in uris}
    )
    mock_api.get_errors = AsyncMock(return_value=[])
    return mock_api


def _assert_coordinator_assignments(
    all_entities, sensor_coordinator, writable_coordinator, error_coordinator
):
    """Assert that every entity is fed by exactly one coordinator that has data for it."""
    for entity in all_entities:
        if isinstance(entity, EtaErrorEntity):
            assert entity.coordinator is error_coordinator, (
                f"{type(entity).__name__} {entity.unique_id!r} expected error_coordinator"
            )
            continue

        if entity.coordinator is sensor_coordinator:
            assert entity.uri in sensor_coordinator.data, (
                f"{type(entity).__name__} {entity.unique_id!r} uri={entity.uri!r} missing from sensor_coordinator.data"
            )
        elif entity.coordinator is writable_coordinator:
            assert entity.uri in writable_coordinator.data, (
                f"{type(entity).__name__} {entity.unique_id!r} uri={entity.uri!r} "
                f"missing from writable_coordinator.data"
            )
        else:
            pytest.fail(
                f"{type(entity).__name__} {entity.unique_id!r} has unexpected coordinator: "
                f"{entity.coordinator!r}"
            )


async def _run_test(
    hass: HomeAssistant,
    float_dict,
    text_dict,
    writable_dict,
    switch_dict,
    chosen_float_sensors,
    chosen_text_sensors,
    chosen_writable_sensors,
    chosen_switches,
    entry_id,
):
    """Shared test body: create real coordinators, refresh them, init platforms, assert."""
    mock_api = _make_api_mock(float_dict, text_dict, writable_dict, switch_dict)

    config = {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        FLOAT_DICT: float_dict,
        TEXT_DICT: text_dict,
        WRITABLE_DICT: writable_dict,
        SWITCHES_DICT: switch_dict,
        CHOSEN_FLOAT_SENSORS: chosen_float_sensors,
        CHOSEN_TEXT_SENSORS: chosen_text_sensors,
        CHOSEN_WRITABLE_SENSORS: chosen_writable_sensors,
        CHOSEN_SWITCHES: chosen_switches,
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
    }

    with (
        patch("custom_components.eta_webservices.coordinator.async_get_clientsession"),
        patch(
            "custom_components.eta_webservices.coordinator.EtaAPI",
            return_value=mock_api,
        ),
        patch("custom_components.eta_webservices.entity.async_get_clientsession"),
        patch("custom_components.eta_webservices.number.async_get_current_platform"),
        patch("custom_components.eta_webservices.sensor.async_get_current_platform"),
    ):
        sensor_coordinator = ETASensorUpdateCoordinator(hass, config)
        writable_coordinator = ETAWritableUpdateCoordinator(hass, config)
        error_coordinator = ETAErrorUpdateCoordinator(hass, config)

        # Coordinators must be refreshed before platform init: entity constructors
        # call coordinator.data.get(...), which raises AttributeError if data is None.
        await sensor_coordinator.async_refresh()
        await writable_coordinator.async_refresh()
        await error_coordinator.async_refresh()

        config[SENSOR_UPDATE_COORDINATOR] = sensor_coordinator
        config[WRITABLE_UPDATE_COORDINATOR] = writable_coordinator
        config[ERROR_UPDATE_COORDINATOR] = error_coordinator

        config_entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id)
        hass.data.setdefault(DOMAIN, {})[entry_id] = config

        all_entities = []

        def add_entities(entities, **_):
            all_entities.extend(entities)

        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)

    return all_entities, sensor_coordinator, writable_coordinator, error_coordinator


@pytest.mark.asyncio
async def test_coordinator_assignment_all_sensors(hass: HomeAssistant, load_fixture):
    """All four chosen lists fully populated: every entity uses the correct coordinator.

    The sensor_coordinator serves float, text, timeslot, and switch entities (unless the
    float sensor is also writable, in which case it uses the writable_coordinator).
    The writable_coordinator serves writable number, time, and writable float entities.
    Error entities always use the error_coordinator.
    """
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    float_dict = fixture["float_dict"]
    text_dict = fixture["text_dict"]
    writable_dict = fixture["writable_dict"]
    switch_dict = fixture["switches_dict"]

    (
        all_entities,
        sensor_coordinator,
        writable_coordinator,
        error_coordinator,
    ) = await _run_test(
        hass,
        float_dict,
        text_dict,
        writable_dict,
        switch_dict,
        chosen_float_sensors=list(float_dict),
        chosen_text_sensors=list(text_dict),
        chosen_writable_sensors=list(writable_dict),
        chosen_switches=list(switch_dict),
        entry_id="test_all_sensors",
    )

    # Sanity-check entity count (mirrors test_all_writable_and_non_writable_sensors_handled)
    assert len(all_entities) == (
        len(float_dict) + len(text_dict) + len(writable_dict) + len(switch_dict) + 2
    )

    _assert_coordinator_assignments(
        all_entities, sensor_coordinator, writable_coordinator, error_coordinator
    )


@pytest.mark.asyncio
async def test_coordinator_assignment_no_writable_sensors(
    hass: HomeAssistant, load_fixture
):
    """chosen_writable_sensors is empty: all regular entities use sensor_coordinator only.

    No EtaWritableNumberSensor or EtaTime should be created.
    Every non-error entity must be in sensor_coordinator.data.
    """
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    float_dict = fixture["float_dict"]
    text_dict = fixture["text_dict"]
    writable_dict = fixture["writable_dict"]
    switch_dict = fixture["switches_dict"]

    (
        all_entities,
        sensor_coordinator,
        writable_coordinator,
        error_coordinator,
    ) = await _run_test(
        hass,
        float_dict,
        text_dict,
        writable_dict,
        switch_dict,
        chosen_float_sensors=list(float_dict),
        chosen_text_sensors=list(text_dict),
        chosen_writable_sensors=[],
        chosen_switches=list(switch_dict),
        entry_id="test_no_writable",
    )

    assert len(all_entities) == len(float_dict) + len(text_dict) + len(switch_dict) + 2

    _assert_coordinator_assignments(
        all_entities, sensor_coordinator, writable_coordinator, error_coordinator
    )


@pytest.mark.asyncio
async def test_coordinator_assignment_only_writable_sensors(
    hass: HomeAssistant, load_fixture
):
    """Only chosen_writable_sensors is populated; all other chosen lists are empty.

    Only EtaWritableNumberSensor, EtaTime, EtaTimeslotSensor (writable variant), and
    the two always-present error sensors should be created. No float or text sensors.
    """
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    float_dict = fixture["float_dict"]
    text_dict = fixture["text_dict"]
    writable_dict = fixture["writable_dict"]
    switch_dict = fixture["switches_dict"]

    (
        all_entities,
        sensor_coordinator,
        writable_coordinator,
        error_coordinator,
    ) = await _run_test(
        hass,
        float_dict,
        text_dict,
        writable_dict,
        switch_dict,
        chosen_float_sensors=[],
        chosen_text_sensors=[],
        chosen_writable_sensors=list(writable_dict),
        chosen_switches=[],
        entry_id="test_only_writable",
    )

    assert len(all_entities) == len(writable_dict) + 2

    _assert_coordinator_assignments(
        all_entities, sensor_coordinator, writable_coordinator, error_coordinator
    )
