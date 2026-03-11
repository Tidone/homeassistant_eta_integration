"""Tests for pending node detection and promotion."""

import pytest
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry

from custom_components.eta_webservices.api import EtaAPI
from custom_components.eta_webservices.coordinator import ETAPendingNodeCoordinator
from custom_components.eta_webservices import async_migrate_entry
from custom_components.eta_webservices.const import (
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_PENDING_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
    PENDING_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PENDING_URI = "/40/10021/0/11108/0"
PENDING_VARINFO_PATH = "/user/varinfo/" + PENDING_URI
PENDING_VAR_PATH = "/user/var/" + PENDING_URI

INVALID_VAR_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
    '  <value uri="/user/var/40/10021/0/11108/0" strValue="---" unit=""'
    '   decPlaces="1" scaleFactor="100" advTextOffset="0">0</value>'
    "</eta>"
)

INVALID_VARINFO_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
    "  <varInfo>"
    '    <variable uri="40/10021/0/11108/0" name="Restsauerstoff"'
    '     fullName="Eing\u00e4nge &gt; Restsauerstoff" unit=""'
    '     decPlaces="1" scaleFactor="100" advTextOffset="0" isWritable="0">'
    "      <type>DEFAULT</type>"
    "    </variable>"
    "  </varInfo>"
    "</eta>"
)

VALID_VARINFO_IEEE754_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
    "  <varInfo>"
    '    <variable uri="40/10021/0/11108/0" name="Restsauerstoff"'
    '     fullName="Eing\u00e4nge &gt; Restsauerstoff" unit=""'
    '     decPlaces="4" scaleFactor="1" advTextOffset="0" isWritable="0">'
    "      <type>IEEE-754</type>"
    "    </variable>"
    "  </varInfo>"
    "</eta>"
)

INVALID_PERMISSION_VAR_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
    "  <error>Invalid permission</error>"
    "</eta>"
)

VALID_VAR_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
    '  <value uri="/user/var/40/10021/0/11108/0" strValue="20,6" unit="%"'
    '   decPlaces="1" scaleFactor="100" advTextOffset="0">2064</value>'
    "</eta>"
)


def _make_response(xml_text: str):
    """Return an async mock whose .text() coroutine returns xml_text."""
    resp = AsyncMock()
    resp.text = AsyncMock(return_value=xml_text)
    return resp


def _build_minimal_sensors_dict(uri: str = PENDING_URI) -> dict:
    """Return the simplest possible get_sensors_dict result for one endpoint."""
    return {"_Eingänge_Restsauerstoff": [uri]}


# ---------------------------------------------------------------------------
# Detection tests (sensor_discovery_v12 via EtaAPI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_node_goes_to_pending_dict(load_fixture):
    """A node that returns unit='' and strValue='---' must land in pending_dict.

    It must NOT appear in float_dict, switches_dict, text_dict, or writable_dict.
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)
    api.is_correct_api_version = AsyncMock(return_value=True)

    # Mock get_sensors_dict to return a single pending endpoint.
    api._http.get_sensors_dict = AsyncMock(
        return_value=_build_minimal_sensors_dict(PENDING_URI)
    )

    # Mock get_request: varinfo returns the invalid XML; var is never called in
    # the varinfo-phase so we only need to handle the varinfo path.
    async def mock_get_request(suffix: str):
        if suffix == PENDING_VARINFO_PATH:
            return _make_response(INVALID_VARINFO_XML)
        return _make_response(
            '<?xml version="1.0" encoding="utf-8"?><eta version="1.0"/>'
        )

    api._http.get_request = mock_get_request

    # Mock get_data: the var endpoint returns ("---", "") — still invalid.
    api._http.get_data = AsyncMock(return_value=("---", ""))

    float_dict: dict = {}
    switches_dict: dict = {}
    text_dict: dict = {}
    writable_dict: dict = {}
    pending_dict: dict = {}

    await api.get_all_sensors(
        False, float_dict, switches_dict, text_dict, writable_dict, pending_dict
    )

    # The node must be in pending_dict.
    assert len(pending_dict) == 1, f"Expected 1 pending node, got {len(pending_dict)}"

    pending_key = next(iter(pending_dict))
    assert "restsauerstoff" in pending_key.lower(), (
        f"Pending key should contain sensor name, got: {pending_key}"
    )
    pending_entry = pending_dict[pending_key]
    assert pending_entry["url"] == PENDING_URI
    assert pending_entry["unit"] == ""
    assert pending_entry["endpoint_type"] == "DEFAULT"

    # The node must NOT appear in any other dict.
    assert float_dict == {}, f"float_dict should be empty, got: {list(float_dict)}"
    assert switches_dict == {}, f"switches_dict should be empty"
    assert text_dict == {}, f"text_dict should be empty"
    assert writable_dict == {}, f"writable_dict should be empty"


@pytest.mark.asyncio
async def test_valid_node_does_not_go_to_pending_dict():
    """A node with a real unit must land in float_dict, NOT in pending_dict."""
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)
    api.is_correct_api_version = AsyncMock(return_value=True)

    valid_varinfo_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        "  <varInfo>"
        '    <variable uri="40/10021/0/11108/0" name="Restsauerstoff"'
        '     fullName="Eing\u00e4nge &gt; Restsauerstoff" unit="%"'
        '     decPlaces="1" scaleFactor="100" advTextOffset="0" isWritable="0">'
        "      <type>DEFAULT</type>"
        "    </variable>"
        "  </varInfo>"
        "</eta>"
    )

    api._http.get_sensors_dict = AsyncMock(
        return_value=_build_minimal_sensors_dict(PENDING_URI)
    )

    async def mock_get_request(suffix: str):
        if suffix == PENDING_VARINFO_PATH:
            return _make_response(valid_varinfo_xml)
        return _make_response(
            '<?xml version="1.0" encoding="utf-8"?><eta version="1.0"/>'
        )

    api._http.get_request = mock_get_request
    # get_data is called because unit="%" → float sensor
    api._http.get_data = AsyncMock(return_value=(20.64, "%"))

    float_dict: dict = {}
    switches_dict: dict = {}
    text_dict: dict = {}
    writable_dict: dict = {}
    pending_dict: dict = {}

    await api.get_all_sensors(
        False, float_dict, switches_dict, text_dict, writable_dict, pending_dict
    )

    assert len(float_dict) == 1, f"Expected 1 float sensor, got {len(float_dict)}"
    assert pending_dict == {}, "Valid node must not appear in pending_dict"


# ---------------------------------------------------------------------------
# Promotion tests (ETAPendingNodeCoordinator)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Lightweight MagicMock standing in for HomeAssistant; avoids real event-loop machinery."""
    return MagicMock()


@pytest.fixture
def mock_client_session():
    """Patch async_get_clientsession so coordinator.__init__ never creates a real session."""
    with patch(
        "custom_components.eta_webservices.coordinator.async_get_clientsession",
        return_value=MagicMock(spec=ClientSession),
    ):
        yield


@pytest.mark.asyncio
async def test_coordinator_promotes_valid_pending_node(mock_hass, mock_client_session):
    """_async_update_data must promote a pending node when get_all_data returns numeric."""
    pending_key = "eta_192_168_0_25__eingänge_restsauerstoff"
    pending_endpoint = {
        "url": PENDING_URI,
        "unit": "",
        "endpoint_type": "DEFAULT",
        "friendly_name": "Eingänge > Restsauerstoff",
        "value": "---",
        "valid_values": None,
    }

    pending_dict = {pending_key: pending_endpoint}

    config = {
        "host": "192.168.0.25",
        "port": 8080,
        PENDING_DICT: pending_dict,
        FLOAT_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_PENDING_SENSORS: [],
    }

    entry = MagicMock(spec=ConfigEntry)
    entry.data = {
        FLOAT_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        PENDING_DICT: deepcopy(pending_dict),
        CHOSEN_PENDING_SENSORS: [],
    }
    entry.options = {}
    entry.pref_disable_polling = False

    coordinator = ETAPendingNodeCoordinator(mock_hass, config, entry)

    # Mock the ETA client created inside the coordinator.
    mock_eta_client = MagicMock()
    mock_eta_client.get_all_data = AsyncMock(return_value={PENDING_URI: 20.64})
    mock_eta_client.get_data = AsyncMock(return_value=(20.64, "%"))
    coordinator._create_eta_client = MagicMock(return_value=mock_eta_client)

    result = await coordinator._async_update_data()

    assert result is True, "_async_update_data should return True after promotion"

    # Promoted node must be removed from pending_dict.
    assert pending_key not in coordinator.pending_dict, (
        "Promoted key must be removed from pending_dict"
    )

    # async_update_entry must have been called with the promoted data.
    mock_hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = mock_hass.config_entries.async_update_entry.call_args
    new_options = (
        call_kwargs[1]["options"] if "options" in call_kwargs[1] else call_kwargs[0][1]
    )

    assert pending_key in new_options.get(FLOAT_DICT, {}), (
        "Promoted node must appear in FLOAT_DICT of updated options"
    )
    assert new_options[FLOAT_DICT][pending_key]["unit"] == "%"
    assert new_options[FLOAT_DICT][pending_key]["value"] == 20.64
    assert pending_key not in new_options.get(PENDING_DICT, {pending_key: None}), (
        "Promoted node must not remain in PENDING_DICT of updated options"
    )


@pytest.mark.asyncio
async def test_coordinator_promotes_preselected_pending_node_to_chosen_float(
    mock_hass, mock_client_session
):
    """A pre-selected pending node must also be added to CHOSEN_FLOAT_SENSORS on promotion."""
    pending_key = "eta_192_168_0_25__eingänge_restsauerstoff"
    pending_endpoint = {
        "url": PENDING_URI,
        "unit": "",
        "endpoint_type": "DEFAULT",
        "friendly_name": "Eingänge > Restsauerstoff",
        "value": "---",
        "valid_values": None,
    }

    pending_dict = {pending_key: pending_endpoint}

    config = {
        "host": "192.168.0.25",
        "port": 8080,
        PENDING_DICT: pending_dict,
        FLOAT_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_PENDING_SENSORS: [pending_key],  # pre-selected
    }

    entry = MagicMock(spec=ConfigEntry)
    entry.data = {
        FLOAT_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        PENDING_DICT: deepcopy(pending_dict),
        CHOSEN_PENDING_SENSORS: [pending_key],
    }
    entry.options = {}
    entry.pref_disable_polling = False

    coordinator = ETAPendingNodeCoordinator(mock_hass, config, entry)

    mock_eta_client = MagicMock()
    mock_eta_client.get_all_data = AsyncMock(return_value={PENDING_URI: 20.64})
    mock_eta_client.get_data = AsyncMock(return_value=(20.64, "%"))
    coordinator._create_eta_client = MagicMock(return_value=mock_eta_client)

    await coordinator._async_update_data()

    call_kwargs = mock_hass.config_entries.async_update_entry.call_args
    new_options = (
        call_kwargs[1]["options"] if "options" in call_kwargs[1] else call_kwargs[0][1]
    )

    assert pending_key in new_options.get(CHOSEN_FLOAT_SENSORS, []), (
        "Pre-selected pending sensor must be moved to CHOSEN_FLOAT_SENSORS after promotion"
    )
    assert pending_key not in new_options.get(CHOSEN_PENDING_SENSORS, [pending_key]), (
        "Pre-selected pending sensor must be removed from CHOSEN_PENDING_SENSORS after promotion"
    )


@pytest.mark.asyncio
async def test_coordinator_no_promotion_when_still_invalid(
    mock_hass, mock_client_session
):
    """_async_update_data must return False if no pending node has become valid."""
    pending_key = "eta_192_168_0_25__eingänge_restsauerstoff"
    pending_endpoint = {
        "url": PENDING_URI,
        "unit": "",
        "endpoint_type": "DEFAULT",
        "friendly_name": "Eingänge > Restsauerstoff",
        "value": "---",
        "valid_values": None,
    }

    pending_dict = {pending_key: pending_endpoint}
    config = {
        "host": "192.168.0.25",
        "port": 8080,
        PENDING_DICT: pending_dict,
    }

    entry = MagicMock(spec=ConfigEntry)
    entry.data = {PENDING_DICT: deepcopy(pending_dict)}
    entry.options = {}
    entry.pref_disable_polling = False

    coordinator = ETAPendingNodeCoordinator(mock_hass, config, entry)

    mock_eta_client = MagicMock()
    # Still "---" — not a numeric value
    mock_eta_client.get_all_data = AsyncMock(return_value={PENDING_URI: "---"})
    coordinator._create_eta_client = MagicMock(return_value=mock_eta_client)

    result = await coordinator._async_update_data()

    assert result is False, (
        "_async_update_data should return False when no nodes promoted"
    )
    mock_hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_returns_false_with_empty_pending_dict(
    mock_hass, mock_client_session
):
    """_async_update_data must short-circuit and return False if pending_dict is empty."""
    config = {"host": "192.168.0.25", "port": 8080, PENDING_DICT: {}}

    entry = MagicMock(spec=ConfigEntry)
    entry.data = {PENDING_DICT: {}}
    entry.options = {}
    entry.pref_disable_polling = False

    coordinator = ETAPendingNodeCoordinator(mock_hass, config, entry)
    coordinator._create_eta_client = MagicMock()  # must not be called

    result = await coordinator._async_update_data()

    assert result is False
    coordinator._create_eta_client.assert_not_called()


@pytest.mark.asyncio
async def test_pending_node_with_invalid_permission_error():
    """A node with IEEE-754 / empty unit whose var endpoint returns an 'Invalid
    permission' error must still land in pending_dict.
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)
    api.is_correct_api_version = AsyncMock(return_value=True)

    api._http.get_sensors_dict = AsyncMock(
        return_value=_build_minimal_sensors_dict(PENDING_URI)
    )

    async def mock_get_request(suffix: str):
        if suffix == PENDING_VARINFO_PATH:
            return _make_response(VALID_VARINFO_IEEE754_XML)
        return _make_response(
            '<?xml version="1.0" encoding="utf-8"?><eta version="1.0"/>'
        )

    api._http.get_request = mock_get_request

    # Simulate what happens when xmltodict.parse(error_xml)["eta"]["value"]
    # raises KeyError because the response contains <error> instead of <value>.
    api._http.get_data = AsyncMock(side_effect=KeyError("value"))

    float_dict: dict = {}
    switches_dict: dict = {}
    text_dict: dict = {}
    writable_dict: dict = {}
    pending_dict: dict = {}

    await api.get_all_sensors(
        False, float_dict, switches_dict, text_dict, writable_dict, pending_dict
    )

    # The node must end up in pending_dict despite the get_data failure.
    assert len(pending_dict) == 1, (
        f"Expected 1 pending node (IEEE-754 + Invalid permission), got {len(pending_dict)}"
    )
    pending_key = next(iter(pending_dict))
    assert "restsauerstoff" in pending_key.lower(), (
        f"Pending key should contain sensor name, got: {pending_key}"
    )
    pending_entry = pending_dict[pending_key]
    assert pending_entry["url"] == PENDING_URI
    assert pending_entry["unit"] == ""
    assert pending_entry["endpoint_type"] == "IEEE-754"

    # Must not appear in any other dict.
    assert float_dict == {}, f"float_dict should be empty, got: {list(float_dict)}"
    assert switches_dict == {}, "switches_dict should be empty"
    assert text_dict == {}, "text_dict should be empty"
    assert writable_dict == {}, "writable_dict should be empty"
