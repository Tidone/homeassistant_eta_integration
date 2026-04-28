"""Tests that verify all sensor types are handled across platforms."""

import pytest
from unittest.mock import MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eta_webservices.number import (
    async_setup_entry as number_async_setup_entry,
)
from custom_components.eta_webservices.sensor import (
    _coerce_numeric_value,
    async_setup_entry as sensor_async_setup_entry,
)
from custom_components.eta_webservices.time import (
    async_setup_entry as time_async_setup_entry,
)
from custom_components.eta_webservices.binary_sensor import (
    async_setup_entry as binary_sensor_async_setup_entry,
)
from custom_components.eta_webservices.switch import (
    async_setup_entry as switch_async_setup_entry,
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


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (12.5, 12.5),
        (7, 7.0),
        ("10.4", 10.4),
        ("10,4", 10.4),
        ("---", None),
        ("Aus", None),
        ("", None),
        (None, None),
    ],
)
def test_coerce_numeric_value_handles_transient_text_values(raw_value, expected):
    """Numeric ETA sensors should tolerate temporary non-numeric placeholder values."""
    assert _coerce_numeric_value(raw_value) == expected


@pytest.mark.asyncio
async def test_all_writable_sensors_handled(hass: HomeAssistant, load_fixture):
    """Test that every entry in WRITABLE_DICT is handled by exactly one platform.

    This verifies that no writable sensor unit type falls through the cracks:
    - number.py handles regular units (°C, %, s, W, …) and 'unitless'
    - time.py handles 'minutes_since_midnight'
    - sensor.py handles 'timeslot' and 'timeslot_plus_temperature'
    - switch.py handles CHOSEN_SWITCHES (not writable sensors)

    sensor.py always adds 2 extra error sensors (EtaNbrErrorsSensor,
    EtaLatestErrorSensor), so the expected total is len(writable_dict) + 2.
    """
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    writable_dict = fixture["writable_dict"]
    float_dict = fixture["float_dict"]
    switch_dict = fixture["switches_dict"]
    text_dict = fixture["text_dict"]
    chosen_writable_sensors = list(writable_dict.keys())

    # Mock coordinators — CoordinatorEntity.__init__ only sets self.coordinator,
    # so MagicMock is safe. .data must be a real dict so that entity constructors
    # can call coordinator.data.get(self.uri). Time sensors expect an ISO time string;
    # all other writable sensors can safely use 0.
    writable_coordinator = MagicMock()
    writable_coordinator.data = {
        info["url"]: "00:00"
        if info["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        else 0
        for info in writable_dict.values()
    }
    sensor_coordinator = MagicMock()
    sensor_coordinator.data = {}
    error_coordinator = MagicMock()
    error_coordinator.data = []

    config = {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        WRITABLE_DICT: writable_dict,
        FLOAT_DICT: float_dict,
        SWITCHES_DICT: switch_dict,
        TEXT_DICT: text_dict,
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: chosen_writable_sensors,
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
        SENSOR_UPDATE_COORDINATOR: sensor_coordinator,
        WRITABLE_UPDATE_COORDINATOR: writable_coordinator,
        ERROR_UPDATE_COORDINATOR: error_coordinator,
    }

    entry_id = "test_entry_id"
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id)
    hass.data.setdefault(DOMAIN, {})[entry_id] = config

    # Capture entities passed to async_add_entities across all platforms
    all_entities = []

    def add_entities(entities, **_):
        all_entities.extend(entities)

    # Only patch async_get_current_platform — called by number and sensor after
    # async_add_entities to register services, which fails without a real HA
    # platform context.
    with (
        patch("custom_components.eta_webservices.number.async_get_current_platform"),
        patch("custom_components.eta_webservices.sensor.async_get_current_platform"),
        patch("custom_components.eta_webservices.entity.async_get_clientsession"),
    ):
        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)
        await binary_sensor_async_setup_entry(hass, config_entry, add_entities)

    # Every writable sensor produces exactly one entity across all platforms,
    # plus 2 error sensors from sensor.py and 1 EtaErrorSensor from binary_sensor.py.
    assert len(all_entities) == len(chosen_writable_sensors) + 3


@pytest.mark.asyncio
async def test_all_non_writable_sensors_handled(hass: HomeAssistant, load_fixture):
    """Test that every non-writable entry is handled by exactly one platform.

    This verifies that no non-writable sensor type falls through the cracks:
    - sensor.py handles all float sensors (EtaFloatSensor) and all text sensors
      (EtaTextSensor for regular units, EtaTimeslotSensor for timeslot units),
      plus always adds 2 error sensors.
    - switch.py handles writable switches (EtaSwitch, is_writable=True).
    - binary_sensor.py handles non-writable switches (EtaBinarySensor, is_writable=False)
      plus always adds 1 EtaErrorSensor.
    - number.py and time.py contribute 0 entities (empty CHOSEN_WRITABLE_SENSORS).

    Total = len(float_dict) + len(text_dict) + len(switches_dict) + 3.
    """
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    float_dict = fixture["float_dict"]
    switch_dict = fixture["switches_dict"]
    text_dict = fixture["text_dict"]
    writable_dict = fixture["writable_dict"]
    chosen_float_sensors = list(float_dict.keys())
    chosen_switches = list(switch_dict.keys())
    chosen_text_sensors = list(text_dict.keys())

    writable_coordinator = MagicMock()
    writable_coordinator.data = {}
    sensor_coordinator = MagicMock()
    sensor_coordinator.data = {}
    error_coordinator = MagicMock()
    error_coordinator.data = []

    config = {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        WRITABLE_DICT: writable_dict,
        FLOAT_DICT: float_dict,
        SWITCHES_DICT: switch_dict,
        TEXT_DICT: text_dict,
        CHOSEN_FLOAT_SENSORS: chosen_float_sensors,
        CHOSEN_SWITCHES: chosen_switches,
        CHOSEN_TEXT_SENSORS: chosen_text_sensors,
        CHOSEN_WRITABLE_SENSORS: [],
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
        SENSOR_UPDATE_COORDINATOR: sensor_coordinator,
        WRITABLE_UPDATE_COORDINATOR: writable_coordinator,
        ERROR_UPDATE_COORDINATOR: error_coordinator,
    }

    entry_id = "test_entry_id_non_writable"
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id)
    hass.data.setdefault(DOMAIN, {})[entry_id] = config

    all_entities = []

    def add_entities(entities, **_):
        all_entities.extend(entities)

    with (
        patch("custom_components.eta_webservices.number.async_get_current_platform"),
        patch("custom_components.eta_webservices.sensor.async_get_current_platform"),
        patch("custom_components.eta_webservices.entity.async_get_clientsession"),
    ):
        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)
        await binary_sensor_async_setup_entry(hass, config_entry, add_entities)

    # Every non-writable sensor produces exactly one entity across all platforms,
    # plus 2 error sensors from sensor.py and 1 EtaErrorSensor from binary_sensor.py.
    assert len(all_entities) == (
        len(chosen_float_sensors) + len(chosen_text_sensors) + len(chosen_switches) + 3
    )


@pytest.mark.asyncio
async def test_all_writable_and_non_writable_sensors_handled(
    hass: HomeAssistant, load_fixture
):
    """Test that all sensors are handled when both writable and non-writable are selected.

    With every sensor chosen simultaneously the platforms partition the work as:
    - sensor.py: every float sensor → EtaFloatSensor or EtaFloatWritableSensor (1 each);
                 non-timeslot text sensors → EtaTextSensor (uses writable_coordinator if also writable);
                 timeslot text sensors WITHOUT a writable counterpart → EtaTimeslotSensor;
                 writable timeslot sensors → EtaTimeslotSensor (1 each, subsumes the
                   text-side timeslot sensor when both are selected);
                 2 always-present error sensors.
    - number.py: writable sensors with regular / unitless units → EtaWritableNumberSensor.
    - time.py:   writable sensors with minutes_since_midnight   → EtaTime.
    - switch.py: writable switches (is_writable=True) → EtaSwitch.
    - binary_sensor.py: non-writable switches (is_writable=False) → EtaBinarySensor,
      plus always adds 1 EtaErrorSensor.

    Total = len(float_dict) + len(text_dict) + len(writable_dict) + len(switches_dict) + 3
    (both the read-only and writable timeslot entities are created; the read-only one is
    disabled via the entity registry migration when a writable counterpart exists).
    """
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    float_dict = fixture["float_dict"]
    switch_dict = fixture["switches_dict"]
    text_dict = fixture["text_dict"]
    writable_dict = fixture["writable_dict"]
    chosen_float_sensors = list(float_dict.keys())
    chosen_switches = list(switch_dict.keys())
    chosen_text_sensors = list(text_dict.keys())
    chosen_writable_sensors = list(writable_dict.keys())

    # Entity constructors look up their URL in coordinator.data. The float/text sensor
    # URLs always match the writable counterpart URLs (same physical endpoint), so
    # writable_dict URLs suffice. Time sensors expect an ISO time string; others use 0.
    writable_coordinator = MagicMock()
    writable_coordinator.data = {
        info["url"]: "00:00"
        if info["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        else 0
        for info in writable_dict.values()
    }
    sensor_coordinator = MagicMock()
    sensor_coordinator.data = {}
    error_coordinator = MagicMock()
    error_coordinator.data = []

    config = {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        WRITABLE_DICT: writable_dict,
        FLOAT_DICT: float_dict,
        SWITCHES_DICT: switch_dict,
        TEXT_DICT: text_dict,
        CHOSEN_FLOAT_SENSORS: chosen_float_sensors,
        CHOSEN_SWITCHES: chosen_switches,
        CHOSEN_TEXT_SENSORS: chosen_text_sensors,
        CHOSEN_WRITABLE_SENSORS: chosen_writable_sensors,
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
        SENSOR_UPDATE_COORDINATOR: sensor_coordinator,
        WRITABLE_UPDATE_COORDINATOR: writable_coordinator,
        ERROR_UPDATE_COORDINATOR: error_coordinator,
    }

    entry_id = "test_entry_id_combined"
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id)
    hass.data.setdefault(DOMAIN, {})[entry_id] = config

    all_entities = []

    def add_entities(entities, **_):
        all_entities.extend(entities)

    with (
        patch("custom_components.eta_webservices.number.async_get_current_platform"),
        patch("custom_components.eta_webservices.sensor.async_get_current_platform"),
        patch("custom_components.eta_webservices.entity.async_get_clientsession"),
    ):
        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)
        await binary_sensor_async_setup_entry(hass, config_entry, add_entities)

    assert len(all_entities) == (
        len(float_dict) + len(text_dict) + len(writable_dict) + len(switch_dict) + 3
    )


@pytest.mark.asyncio
async def test_sensor_platform_skips_duplicate_unique_ids(
    hass: HomeAssistant, load_fixture
):
    """Duplicate unique IDs across sensor categories should not be added twice."""
    fixture = load_fixture("api_assignment_reference_values_v12.json")
    float_dict = fixture["float_dict"]
    switch_dict = fixture["switches_dict"]
    writable_dict = fixture["writable_dict"]

    duplicate_key = next(iter(float_dict.keys()))
    duplicate_endpoint = float_dict[duplicate_key].copy()
    text_dict = {duplicate_key: duplicate_endpoint}

    writable_coordinator = MagicMock()
    writable_coordinator.data = {}
    sensor_coordinator = MagicMock()
    sensor_coordinator.data = {}
    error_coordinator = MagicMock()
    error_coordinator.data = []

    config = {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        WRITABLE_DICT: writable_dict,
        FLOAT_DICT: float_dict,
        SWITCHES_DICT: switch_dict,
        TEXT_DICT: text_dict,
        CHOSEN_FLOAT_SENSORS: [duplicate_key],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [duplicate_key],
        CHOSEN_WRITABLE_SENSORS: [],
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
        SENSOR_UPDATE_COORDINATOR: sensor_coordinator,
        WRITABLE_UPDATE_COORDINATOR: writable_coordinator,
        ERROR_UPDATE_COORDINATOR: error_coordinator,
    }

    entry_id = "test_entry_id_duplicate_unique_id"
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id)
    hass.data.setdefault(DOMAIN, {})[entry_id] = config

    all_entities = []

    def add_entities(entities, **_):
        all_entities.extend(entities)

    with (
        patch("custom_components.eta_webservices.sensor.async_get_current_platform"),
        patch("custom_components.eta_webservices.entity.async_get_clientsession"),
    ):
        await sensor_async_setup_entry(hass, config_entry, add_entities)

    unique_ids = [entity.unique_id for entity in all_entities if entity.unique_id]
    assert len(unique_ids) == len(set(unique_ids))
    # 1 deduplicated regular sensor + 2 always-present error sensors
    assert len(all_entities) == 3
