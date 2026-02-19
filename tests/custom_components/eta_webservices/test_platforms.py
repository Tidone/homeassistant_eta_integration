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
    async_setup_entry as sensor_async_setup_entry,
)
from custom_components.eta_webservices.time import (
    async_setup_entry as time_async_setup_entry,
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
    DOMAIN,
    ERROR_UPDATE_COORDINATOR,
    FLOAT_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
)


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
    # so MagicMock is safe. .data must be a real dict so that
    # EtaWritableSensorEntity.__init__ can do float(coordinator.data[self.uri]).
    # Use 0 as a safe numeric default: some fixture entries have string values
    # (e.g. 'xxx', '21:00') that can't be float()-ed.
    writable_coordinator = MagicMock()
    writable_coordinator.data = {info["url"]: 0 for info in writable_dict.values()}
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
    ):
        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)

    # Every writable sensor produces exactly one entity across all platforms,
    # plus the 2 always-present error sensors from sensor.py.
    assert len(all_entities) == len(chosen_writable_sensors) + 2


@pytest.mark.asyncio
async def test_all_non_writable_sensors_handled(hass: HomeAssistant, load_fixture):
    """Test that every non-writable entry is handled by exactly one platform.

    This verifies that no non-writable sensor type falls through the cracks:
    - sensor.py handles all float sensors (EtaFloatSensor) and all text sensors
      (EtaTextSensor for regular units, EtaTimeslotSensor for timeslot units),
      plus always adds 2 error sensors.
    - switch.py handles all switches (EtaSwitch).
    - number.py and time.py contribute 0 entities (empty CHOSEN_WRITABLE_SENSORS).

    Total = len(float_dict) + len(text_dict) + len(switches_dict) + 2.
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
    ):
        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)

    # Every non-writable sensor produces exactly one entity across all platforms,
    # plus the 2 always-present error sensors from sensor.py.
    assert len(all_entities) == (
        len(chosen_float_sensors) + len(chosen_text_sensors) + len(chosen_switches) + 2
    )


@pytest.mark.asyncio
async def test_all_writable_and_non_writable_sensors_handled(
    hass: HomeAssistant, load_fixture
):
    """Test that all sensors are handled when both writable and non-writable are selected.

    With every sensor chosen simultaneously the platforms partition the work as:
    - sensor.py: every float sensor → EtaFloatSensor or EtaFloatWritableSensor (1 each);
                 every text sensor  → EtaTextSensor, EtaTimeslotSensor, or
                                      EtaTimeWritableSensor (1 each);
                 writable timeslot sensors → EtaTimeslotSensor (1 each);
                 2 always-present error sensors.
    - number.py: writable sensors with regular / unitless units → EtaWritableNumberSensor.
    - time.py:   writable sensors with minutes_since_midnight   → EtaTime.
    - switch.py: every switch → EtaSwitch.

    Total = len(float_dict) + len(text_dict) + len(writable_dict) + len(switches_dict) + 2.
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

    # EtaFloatWritableSensor and EtaTimeWritableSensor look up their URL in
    # coordinator.data. The float/text sensor URLs always match the writable
    # counterpart URLs (same physical endpoint), so writable_dict URLs suffice.
    writable_coordinator = MagicMock()
    writable_coordinator.data = {info["url"]: 0 for info in writable_dict.values()}
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
    ):
        await number_async_setup_entry(hass, config_entry, add_entities)
        await sensor_async_setup_entry(hass, config_entry, add_entities)
        await time_async_setup_entry(hass, config_entry, add_entities)
        await switch_async_setup_entry(hass, config_entry, add_entities)

    # Every sensor produces exactly one entity across all platforms,
    # plus the 2 always-present error sensors from sensor.py.
    assert len(all_entities) == (
        len(float_dict) + len(text_dict) + len(writable_dict) + len(switch_dict) + 2
    )
