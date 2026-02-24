"""Tests for the ETA API module."""

import asyncio
import pytest
from unittest.mock import AsyncMock
from aiohttp import ClientSession, ClientError, ClientResponseError

from custom_components.eta_webservices.api import EtaAPI


@pytest.mark.asyncio
async def test_get_all_sensors_v12(load_fixture):
    """Test get_all_sensors with API v1.2 using real fixture data.

    This test verifies:
    - Public get_all_sensors() method routes to v12 when API version >= 1.2
    - Mock HTTP responses are properly used
    - Endpoints are correctly parsed from varinfo endpoint
    - Sensor values are fetched and added to correct dictionaries
    - All dictionaries are populated with expected entries
    """
    # Load fixtures
    api_endpoint_data = load_fixture("api_endpoint_data.json")
    assignment_target_values = load_fixture("api_assignment_reference_values_v12.json")

    # Setup mock session
    mock_session = AsyncMock(spec=ClientSession)

    # Create API instance with test host
    api = EtaAPI(mock_session, "192.168.0.25", 8080)

    # Mock is_correct_api_version to return True (v1.2+)
    api.is_correct_api_version = AsyncMock(return_value=True)

    # Setup mock responses based on fixture data
    def create_mock_response(url_path: str):
        """Create a mock response for a given URL path."""
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(
                return_value=api_endpoint_data[url_path]
            )
        else:
            # Return error for unknown endpoints
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response

    # Mock the _get_request method to return fixture data
    async def mock_get_request(suffix):
        """Mock _get_request to return fixture data."""
        # Extract the path from the suffix
        # suffix is like "/user/menu", "/user/var//120/10111/0/0/10990", etc.
        response = create_mock_response(suffix)
        return response

    api._http.get_request = mock_get_request

    # Initialize dictionaries
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    # Execute the public method with force_legacy_mode=False
    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)
    
    # Assertions
    # Verify expected entries from target values
    expected_float_entries = assignment_target_values.get("float_dict", {})
    expected_switches_entries = assignment_target_values.get("switches_dict", {})
    expected_text_entries = assignment_target_values.get("text_dict", {})
    expected_writable_entries = assignment_target_values.get("writable_dict", {})

    # Verify length of dictionaries
    assert len(float_dict) == len(expected_float_entries), f"len(float_dict) is not equal to {len(expected_float_entries)}"
    assert len(text_dict) == len(expected_text_entries), f"len(text_dict) is not equal to {len(expected_text_entries)}"
    assert len(writable_dict) == len(expected_writable_entries), f"len(writable_dict) is not equal to {len(expected_writable_entries)}"
    assert len(switches_dict) == len(expected_switches_entries), f"len(switches_dict) is not equal to {len(expected_switches_entries)}"
    
    # Check float_dict entries
    for expected_key, expected_value in expected_float_entries.items():
        assert expected_key in float_dict, (
            f"Expected key '{expected_key}' not found in float_dict"
        )
        actual_entry = float_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}: "
            f"expected {expected_value['url']}, got {actual_entry['url']}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}: "
            f"expected {expected_value['unit']}, got {actual_entry['unit']}"
        )
        assert actual_entry["endpoint_type"] == expected_value["endpoint_type"], (
            f"Endpoint type mismatch for {expected_key}"
        )
        assert actual_entry["friendly_name"] == expected_value["friendly_name"], (
            f"Friendly name mismatch for {expected_key}"
        )
        # Value might differ slightly due to floating point precision, so we check with tolerance
        if isinstance(actual_entry.get("value"), (int, float)):
            assert abs(
                actual_entry.get("value", 0) - expected_value.get("value", 0)
            ) < 0.01, (
                f"Value mismatch for {expected_key}: "
                f"expected {expected_value.get('value')}, got {actual_entry.get('value')}"
            )
    
    # Check writable_dict entries
    for expected_key, expected_value in expected_writable_entries.items():
        assert expected_key in writable_dict, (
            f"Expected key '{expected_key}' not found in writable_dict"
        )
        actual_entry = writable_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        assert actual_entry["value"] == expected_value["value"], (
            f"Data mismatch for {expected_key}"
        )
        
        # Check valid_values structure for writable entries
        if expected_value.get("valid_values") is not None:
            assert actual_entry.get("valid_values") is not None, (
                f"Valid values missing for writable entry {expected_key}"
            )
            expected_vv = expected_value["valid_values"]
            actual_vv = actual_entry["valid_values"]
            
            assert actual_vv.get("scaled_min_value") == expected_vv.get("scaled_min_value"), (
                f"Scaled min value mismatch for {expected_key}"
            )
            assert actual_vv.get("scaled_max_value") == expected_vv.get("scaled_max_value"), (
                f"Scaled max value mismatch for {expected_key}"
            )
            assert actual_vv.get("scale_factor") == expected_vv.get("scale_factor"), (
                f"Scale factor mismatch for {expected_key}"
            )
            assert actual_vv.get("dec_places") == expected_vv.get("dec_places"), (
                f"Dec places mismatch for {expected_key}"
            )
    
    # Check switches_dict entries
    for expected_key, expected_value in expected_switches_entries.items():
        assert expected_key in switches_dict, (
            f"Expected key '{expected_key}' not found in switches_dict"
        )
        actual_entry = switches_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        assert actual_entry["value"] == expected_value["value"], (
            f"Data mismatch for {expected_key}"
        )
        
        # Check switch valid_values (on_value and off_value)
        assert actual_entry.get("valid_values") is not None, (
            f"Valid values missing for switch {expected_key}"
        )
        assert "on_value" in actual_entry["valid_values"], (
            f"on_value missing for switch {expected_key}"
        )
        assert "off_value" in actual_entry["valid_values"], (
            f"off_value missing for switch {expected_key}"
        )
    
    # Check text_dict entries
    for expected_key, expected_value in expected_text_entries.items():
        assert expected_key in text_dict, (
            f"Expected key '{expected_key}' not found in text_dict"
        )
        actual_entry = text_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        assert actual_entry["value"] == expected_value["value"], (
            f"Data mismatch for {expected_key}"
        )


@pytest.mark.asyncio
async def test_get_all_sensors_v12_handles_exceptions():
    """Test that get_all_sensors (v1.2) handles exceptions gracefully.

    This test verifies:
    - Invalid endpoints that raise exceptions are caught and logged
    - Processing continues even if some endpoints are invalid
    - Valid endpoints are still added to dictionaries
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock is_correct_api_version to return True (v1.2+)
    api.is_correct_api_version = AsyncMock(return_value=True)

    # Mock menu response with valid and invalid endpoints
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10111" name="WW">'
        '<object uri="/120/10111/0/0/12271" name="Valid"/>'
        '<object uri="/120/10111/0/0/99999" name="Invalid"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    # Mock varinfo response for valid endpoint
    valid_varinfo_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<varInfo uri="/user/varinfo/120/10111/0/0/12271">'
        '<variable uri="120/10111/0/0/12271" name="Valid" fullName="Valid" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0" isWritable="0">'
        '<type>DEFAULT</type>'
        '</variable>'
        '</varInfo>'
        '</eta>'
    )
    
    # Mock var response for valid endpoint
    valid_var_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10111/0/0/12271" strValue="50" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">500</value>'
        '</eta>'
    )
    
    # Error response for invalid endpoint
    error_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<error>Invalid endpoint</error>'
        '</eta>'
    )
    
    async def mock_get_request(suffix):
        response = AsyncMock()
        if "/user/menu" in suffix:
            response.text = AsyncMock(return_value=menu_xml)
        elif "/user/varinfo" in suffix and "12271" in suffix:
            response.text = AsyncMock(return_value=valid_varinfo_xml)
        elif "/user/var" in suffix and "12271" in suffix:
            response.text = AsyncMock(return_value=valid_var_xml)
        else:
            # Invalid endpoints return error or cause parsing errors
            response.text = AsyncMock(return_value=error_xml)
        return response

    api._http.get_request = mock_get_request

    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)

    # Valid sensor should be in float_dict
    assert len(float_dict) > 0, "Valid float sensor should be added to float_dict"
    # Invalid endpoint should be skipped, not cause the method to fail
    # The method should complete without raising an exception


@pytest.mark.asyncio
async def test_get_all_sensors_v12_skips_duplicates(load_fixture):
    """Test that get_all_sensors (v1.2) skips duplicate endpoints.

    This test verifies:
    - Same URI appearing multiple times in the menu is only processed once
    - All dictionaries correctly reflect single processing of duplicate URIs
    """
    api_endpoint_data = load_fixture("api_endpoint_data.json")

    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)

    # Mock is_correct_api_version to return True (v1.2+)
    api.is_correct_api_version = AsyncMock(return_value=True)
    
    # Mock menu response with duplicate endpoint
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10111" name="WW">'
        '<object uri="/120/10111/0/0/12271" name="Test1"/>'
        '<object uri="/120/10111/0/0/12271" name="Test2"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    def create_mock_response(url_path: str):
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(return_value=api_endpoint_data[url_path])
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    call_count = {}
    
    async def mock_get_request(suffix):
        call_count[suffix] = call_count.get(suffix, 0) + 1
        if suffix == "/user/menu":
            response = AsyncMock()
            response.text = AsyncMock(return_value=menu_xml)
            return response
        else:
            return create_mock_response(suffix)

    api._http.get_request = mock_get_request

    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)

    # Verify that the duplicate endpoint was only queried once
    varinfo_key = "/user/varinfo//120/10111/0/0/12271"
    var_key = "/user/var//120/10111/0/0/12271"

    # The duplicate should have been skipped, so each endpoint should be called once
    assert call_count.get(varinfo_key, 0) <= 1, (
        f"Duplicate endpoint should be queried at most once, "
        f"but was queried {call_count.get(varinfo_key, 0)} times"
    )


@pytest.mark.asyncio
async def test_get_all_sensors_v11(load_fixture):
    """Test get_all_sensors with API v1.1 using real fixture data.

    This test verifies:
    - Public get_all_sensors() method routes to v11 when API version < 1.2
    - Mock HTTP responses are properly used for v1.1 API
    - Endpoints are correctly parsed from menu endpoint
    - Sensor values are fetched and added to correct dictionaries
    - All dictionaries are populated with expected entries
    - Writable sensors are identified by unit alone (no varinfo available)
    - Switches are identified by empty unit and specific value codes (1802/1803)
    """
    # Load fixtures
    api_endpoint_data = load_fixture("api_endpoint_data.json")
    reference_values_v11 = load_fixture("api_assignment_reference_values_v11.json")

    # Setup mock session
    mock_session = AsyncMock(spec=ClientSession)

    # Create API instance with test host
    api = EtaAPI(mock_session, "192.168.0.25", 8080)

    # Mock is_correct_api_version to return False (v1.1)
    api.is_correct_api_version = AsyncMock(return_value=False)
    
    # Setup mock responses based on fixture data
    def create_mock_response(url_path: str):
        """Create a mock response for a given URL path."""
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(
                return_value=api_endpoint_data[url_path]
            )
        else:
            # Return error for unknown endpoints
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    # Mock the _get_request method to return fixture data
    async def mock_get_request(suffix):
        """Mock _get_request to return fixture data."""
        response = create_mock_response(suffix)
        return response

    api._http.get_request = mock_get_request

    # Initialize dictionaries
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    # Execute the public method with force_legacy_mode=False
    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)
    
    # Assertions
    # Verify expected entries from reference values
    expected_float_entries = reference_values_v11.get("float_dict", {})
    expected_switches_entries = reference_values_v11.get("switches_dict", {})
    expected_text_entries = reference_values_v11.get("text_dict", {})
    expected_writable_entries = reference_values_v11.get("writable_dict", {})

    # Verify length of dictionaries
    assert len(float_dict) == len(expected_float_entries), f"len(float_dict) is not equal to {len(expected_float_entries)}"
    assert len(text_dict) == len(expected_text_entries), f"len(text_dict) is not equal to {len(expected_text_entries)}"
    assert len(writable_dict) == len(expected_writable_entries), f"len(writable_dict) is not equal to {len(expected_writable_entries)}"
    assert len(switches_dict) == len(expected_switches_entries), f"len(switches_dict) is not equal to {len(expected_switches_entries)}"
    
    # Check float_dict entries
    for expected_key, expected_value in expected_float_entries.items():
        assert expected_key in float_dict, (
            f"Expected key '{expected_key}' not found in float_dict"
        )
        actual_entry = float_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}: "
            f"expected {expected_value['url']}, got {actual_entry['url']}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}: "
            f"expected {expected_value['unit']}, got {actual_entry['unit']}"
        )
        assert actual_entry["friendly_name"] == expected_value["friendly_name"], (
            f"Friendly name mismatch for {expected_key}"
        )
        # Value might differ slightly due to floating point precision
        if isinstance(actual_entry.get("value"), (int, float)):
            assert abs(
                actual_entry.get("value", 0) - expected_value.get("value", 0)
            ) < 0.1, (
                f"Value mismatch for {expected_key}: "
                f"expected {expected_value.get('value')}, got {actual_entry.get('value')}"
            )
    
    # Check writable_dict entries
    for expected_key, expected_value in expected_writable_entries.items():
        assert expected_key in writable_dict, (
            f"Expected key '{expected_key}' not found in writable_dict"
        )
        actual_entry = writable_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        
        # Check valid_values structure for writable entries (v11 uses default ranges)
        if expected_value.get("valid_values") is not None:
            assert actual_entry.get("valid_values") is not None, (
                f"Valid values missing for writable entry {expected_key}"
            )
            expected_vv = expected_value["valid_values"]
            actual_vv = actual_entry["valid_values"]
            
            assert actual_vv.get("scaled_min_value") == expected_vv.get("scaled_min_value"), (
                f"Scaled min value mismatch for {expected_key}"
            )
            assert actual_vv.get("scaled_max_value") == expected_vv.get("scaled_max_value"), (
                f"Scaled max value mismatch for {expected_key}"
            )
    
    # Check switches_dict entries (v11 uses specific codes 1802/1803)
    for expected_key, expected_value in expected_switches_entries.items():
        assert expected_key in switches_dict, (
            f"Expected key '{expected_key}' not found in switches_dict"
        )
        actual_entry = switches_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        
        # Check switch valid_values (on_value=1803, off_value=1802)
        assert actual_entry.get("valid_values") is not None, (
            f"Valid values missing for switch {expected_key}"
        )
        assert actual_entry["valid_values"].get("on_value") == 1803, (
            f"on_value should be 1803 for switch {expected_key}, got {actual_entry['valid_values'].get('on_value')}"
        )
        assert actual_entry["valid_values"].get("off_value") == 1802, (
            f"off_value should be 1802 for switch {expected_key}, got {actual_entry['valid_values'].get('off_value')}"
        )
    
    # Check text_dict entries
    for expected_key, expected_value in expected_text_entries.items():
        assert expected_key in text_dict, (
            f"Expected key '{expected_key}' not found in text_dict"
        )
        actual_entry = text_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )


@pytest.mark.asyncio
async def test_get_all_sensors_v11_distinguishes_sensor_types():
    """Test that get_all_sensors (v1.1) correctly identifies sensor types.

    This test verifies:
    - Float sensors are identified by unit in float_sensor_units
    - Switches are identified by empty unit and values 1802/1803
    - Text sensors are added only if they have non-empty values
    - Writable sensors are identified by unit in writable_sensor_units
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock is_correct_api_version to return False (v1.1)
    api.is_correct_api_version = AsyncMock(return_value=False)
    
    # Menu with different sensor types
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10101" name="HK">'
        '<object uri="/120/10101/0/0/12197" name="FloatSensor"/>'
        '<object uri="/120/10101/0/0/12080" name="SwitchSensor"/>'
        '<object uri="/120/10101/0/0/12132" name="WritableSensor"/>'
        '<object uri="/120/10101/0/0/12476" name="TextSensor"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    # Float sensor (°C)
    float_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12197" strValue="20" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
        '</eta>'
    )
    
    # Switch sensor (empty unit, codes 1802/1803)
    switch_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12080" strValue="Ein" '
        'unit="" decPlaces="0" scaleFactor="1" advTextOffset="0">1803</value>'
        '</eta>'
    )
    
    # Writable sensor (°C, writable unit)
    writable_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12132" strValue="30" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">300</value>'
        '</eta>'
    )
    
    # Text sensor (empty unit, empty value)
    text_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12476" strValue="" '
        'unit="" decPlaces="0" scaleFactor="1" advTextOffset="0">0</value>'
        '</eta>'
    )
    
    async def mock_get_request(suffix):
        response = AsyncMock()
        if "/user/menu" in suffix:
            response.text = AsyncMock(return_value=menu_xml)
        elif "12197" in suffix:
            response.text = AsyncMock(return_value=float_var)
        elif "12080" in suffix:
            response.text = AsyncMock(return_value=switch_var)
        elif "12132" in suffix:
            response.text = AsyncMock(return_value=writable_var)
        elif "12476" in suffix:
            response.text = AsyncMock(return_value=text_var)
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response

    api._http.get_request = mock_get_request

    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)

    # Verify sensor type identification
    assert len(float_dict) > 0, "Float sensor should be added"
    assert len(switches_dict) > 0, "Switch should be added"
    assert len(writable_dict) > 0, "Writable sensor should be added"
    # Text sensor with empty value should not be added
    assert len(text_dict) == 0, "Empty text sensor should not be added"


@pytest.mark.asyncio
async def test_get_all_sensors_v11_skips_duplicates():
    """Test that get_all_sensors (v1.1) skips duplicate endpoints.

    This test verifies:
    - Same URI appearing multiple times is only processed once
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock is_correct_api_version to return False (v1.1)
    api.is_correct_api_version = AsyncMock(return_value=False)

    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10101" name="HK">'
        '<object uri="/120/10101/0/0/12197" name="Sensor1"/>'
        '<object uri="/120/10101/0/0/12197" name="Sensor2"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )

    sensor_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12197" strValue="20" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
        '</eta>'
    )

    call_count = {}

    async def mock_get_request(suffix):
        call_count[suffix] = call_count.get(suffix, 0) + 1
        response = AsyncMock()
        if "/user/menu" in suffix:
            response.text = AsyncMock(return_value=menu_xml)
        elif "12197" in suffix:
            response.text = AsyncMock(return_value=sensor_var)
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response

    api._http.get_request = mock_get_request

    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)

    # Verify duplicate was only queried once
    var_key = "/user/var//120/10101/0/0/12197"
    assert call_count.get(var_key, 0) <= 1, (
        f"Duplicate endpoint should be queried at most once, "
        f"but was queried {call_count.get(var_key, 0)} times"
    )


@pytest.mark.asyncio
async def test_get_all_sensors_force_legacy_mode(load_fixture):
    """Test that force_legacy_mode forces use of v1.1 even with v1.2 API.

    This test verifies:
    - force_legacy_mode=True bypasses version check
    - Uses v1.1 implementation even when API version is 1.2+
    - is_correct_api_version is NOT called when force_legacy_mode=True
    """
    # Load fixtures
    api_endpoint_data = load_fixture("api_endpoint_data.json")
    reference_values_v11 = load_fixture("api_assignment_reference_values_v11.json")

    # Setup mock session
    mock_session = AsyncMock(spec=ClientSession)

    # Create API instance with test host
    api = EtaAPI(mock_session, "192.168.0.25", 8080)

    # Mock is_correct_api_version to return True (v1.2+)
    # But it should NOT be called when force_legacy_mode=True
    version_check_called = []
    async def mock_is_correct_version():
        version_check_called.append(True)
        return True

    api.is_correct_api_version = mock_is_correct_version

    # Setup mock responses based on fixture data
    def create_mock_response(url_path: str):
        """Create a mock response for a given URL path."""
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(
                return_value=api_endpoint_data[url_path]
            )
        else:
            # Return error for unknown endpoints
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response

    # Mock the _get_request method to return fixture data
    async def mock_get_request(suffix):
        """Mock _get_request to return fixture data."""
        response = create_mock_response(suffix)
        return response

    api._http.get_request = mock_get_request

    # Initialize dictionaries
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    # Execute with force_legacy_mode=True
    await api.get_all_sensors(True, float_dict, switches_dict, text_dict, writable_dict)

    # Verify version check was NOT called (short-circuit evaluation)
    assert len(version_check_called) == 0, "is_correct_api_version should not be called when force_legacy_mode=True"

    # Verify that v1.1 behavior is used (switches use 1802/1803)
    # Check for v1.1 specific behavior - switches should exist
    assert len(switches_dict) > 0, "Should have switches (v1.1 behavior)"

    # Verify at least some expected v1.1 entries exist
    expected_switches = reference_values_v11.get("switches_dict", {})
    if expected_switches:
        # Check one switch has the v1.1 characteristics (on_value=1803, off_value=1802)
        for switch_key, switch_value in switches_dict.items():
            if "valid_values" in switch_value:
                assert switch_value["valid_values"].get("on_value") == 1803, \
                    "Should use v1.1 switch values (1803=on)"
                assert switch_value["valid_values"].get("off_value") == 1802, \
                    "Should use v1.1 switch values (1802=off)"
                break  # Just check one to verify v1.1 behavior


@pytest.mark.asyncio
async def test_get_all_sensors_v12_respects_concurrent_request_limit():
    """Test that get_all_sensors (v1.2) respects the max concurrent requests limit.

    This test verifies:
    - Maximum of api._http.max_concurrent_requests concurrent requests are active at any time during sensor discovery
    - All sensors are eventually processed
    - Concurrency limit is properly enforced throughout the entire flow
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)

    # Mock is_correct_api_version to return True (v1.2+)
    api.is_correct_api_version = AsyncMock(return_value=True)

    current_concurrent = 0
    max_concurrent = 0
    completed_count = 0

    # Create a menu with multiple sensors
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10111" name="Test">'
    )
    # Add api._http.max_concurrent_requests*2 sensor endpoints
    for i in range(api._http.max_concurrent_requests*2):
        menu_xml += f'<object uri="/120/10111/0/0/1000{i}" name="Sensor{i}"/>'
    menu_xml += '</fub></menu></eta>'

    async def mock_get_request(suffix):
        nonlocal current_concurrent, max_concurrent, completed_count

        # Track concurrency for all requests
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)

        # Simulate work
        # This sleep is necessary to give control back to the event loop and allow other requests to start, which is essential for testing concurrency limits
        await asyncio.sleep(0.02)

        current_concurrent -= 1
        completed_count += 1

        response = AsyncMock()

        if suffix == "/user/menu":
            response.text = AsyncMock(return_value=menu_xml)
        elif "/user/varinfo" in suffix:
            # Return varinfo for each sensor
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
                '<varInfo><variable uri="test" name="Test" fullName="Test" '
                'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0" isWritable="0">'
                '<type>DEFAULT</type></variable></varInfo></eta>'
            )
        elif "/user/var" in suffix:
            # Return value for each sensor
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
                '<value uri="test" strValue="20" '
                'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
                '</eta>'
            )
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )

        return response

    api._http.get_request = mock_get_request

    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)

    # Verify concurrent limit was respected
    assert max_concurrent <= api._http.max_concurrent_requests, (
        f"Maximum concurrent requests should be <= {api._http.max_concurrent_requests}, but was {max_concurrent}"
    )
    assert max_concurrent > 1, "Should have some concurrency"
    # Menu + api._http.max_concurrent_requests*2 varinfo + api._http.max_concurrent_requests*2 var requests = 21 total
    assert completed_count >= api._http.max_concurrent_requests*2*2, "Should have completed at least api._http.max_concurrent_requests*2*2 requests"
    assert len(float_dict) > 0, "Should have discovered and fetched sensors"


@pytest.mark.asyncio
async def test_get_all_sensors_v11_respects_concurrent_request_limit():
    """Test that get_all_sensors (v1.1) respects the max concurrent requests limit.

    This test verifies:
    - Maximum of api._http.max_concurrent_requests concurrent requests are active at any time during sensor discovery
    - All sensors are eventually processed
    - Concurrency limit is properly enforced throughout the entire flow
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)

    # Mock is_correct_api_version to return False (v1.1)
    api.is_correct_api_version = AsyncMock(return_value=False)

    current_concurrent = 0
    max_concurrent = 0
    completed_count = 0

    # Create a menu with multiple sensors
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10101" name="Test">'
    )
    # Add api._http.max_concurrent_requests*2 sensor endpoints
    for i in range(api._http.max_concurrent_requests*2):
        menu_xml += f'<object uri="/120/10101/0/0/1000{i}" name="Sensor{i}"/>'
    menu_xml += '</fub></menu></eta>'

    async def mock_get_request(suffix):
        nonlocal current_concurrent, max_concurrent, completed_count

        # Track concurrency for all requests
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)

        # Simulate work
        # This sleep is necessary to give control back to the event loop and allow other requests to start, which is essential for testing concurrency limits
        await asyncio.sleep(0.02)

        current_concurrent -= 1
        completed_count += 1

        response = AsyncMock()

        if suffix == "/user/menu":
            response.text = AsyncMock(return_value=menu_xml)
        elif "/user/var" in suffix:
            # Return value for each sensor (v1.1 doesn't use varinfo)
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
                '<value uri="test" strValue="20" '
                'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
                '</eta>'
            )
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )

        return response

    api._http.get_request = mock_get_request

    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}

    await api.get_all_sensors(False, float_dict, switches_dict, text_dict, writable_dict)

    # Verify concurrent limit was respected
    assert max_concurrent <= api._http.max_concurrent_requests, (
        f"Maximum concurrent requests should be <= {api._http.max_concurrent_requests}, but was {max_concurrent}"
    )
    assert max_concurrent > 1, "Should have some concurrency"
    # Menu + api._http.max_concurrent_requests*2 var requests = api._http.max_concurrent_requests*2+1 total
    assert completed_count >= api._http.max_concurrent_requests*2, "Should have completed at least api._http.max_concurrent_requests*2 requests"
    assert len(float_dict) > 0, "Should have discovered and fetched all sensors"


@pytest.mark.asyncio
async def test_is_correct_api_version_returns_true_for_v12():
    """Test that is_correct_api_version returns True for API version 1.2.

    This test verifies:
    - API version 1.2 is correctly identified as the minimum required version
    - Returns True when version equals 1.2
    - Correct endpoint /user/api is called
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock API response with version 1.2
    api_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<api version="1.2"/>'
        '</eta>'
    )

    called_endpoints = []

    async def mock_get_request(suffix):
        called_endpoints.append(suffix)
        response = AsyncMock()
        response.text = AsyncMock(return_value=api_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.is_correct_api_version()

    assert result is True, "API version 1.2 should return True"
    assert "/user/api" in called_endpoints, "Should call /user/api endpoint"


@pytest.mark.asyncio
async def test_is_correct_api_version_returns_true_for_higher_version():
    """Test that is_correct_api_version returns True for API versions higher than 1.2.

    This test verifies:
    - API versions greater than 1.2 are correctly identified
    - Returns True for version 1.3
    - Correct endpoint /user/api is called
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock API response with version 1.3
    api_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<api version="1.3"/>'
        '</eta>'
    )

    called_endpoints = []

    async def mock_get_request(suffix):
        called_endpoints.append(suffix)
        response = AsyncMock()
        response.text = AsyncMock(return_value=api_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.is_correct_api_version()

    assert result is True, "API version 1.3 should return True"
    assert "/user/api" in called_endpoints, "Should call /user/api endpoint"


@pytest.mark.asyncio
async def test_is_correct_api_version_returns_false_for_v11():
    """Test that is_correct_api_version returns False for API version 1.1.

    This test verifies:
    - API versions lower than 1.2 are correctly identified
    - Returns False for version 1.1
    - Correct endpoint /user/api is called
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock API response with version 1.1
    api_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<api version="1.1"/>'
        '</eta>'
    )

    called_endpoints = []

    async def mock_get_request(suffix):
        called_endpoints.append(suffix)
        response = AsyncMock()
        response.text = AsyncMock(return_value=api_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.is_correct_api_version()

    assert result is False, "API version 1.1 should return False"
    assert "/user/api" in called_endpoints, "Should call /user/api endpoint"


@pytest.mark.asyncio
async def test_is_correct_api_version_returns_false_for_v10():
    """Test that is_correct_api_version returns False for API version 1.0.

    This test verifies:
    - Old API versions (1.0) are correctly identified as not meeting requirements
    - Returns False for version 1.0
    - Correct endpoint /user/api is called
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock API response with version 1.0
    api_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<api version="1.0"/>'
        '</eta>'
    )

    called_endpoints = []

    async def mock_get_request(suffix):
        called_endpoints.append(suffix)
        response = AsyncMock()
        response.text = AsyncMock(return_value=api_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.is_correct_api_version()

    assert result is False, "API version 1.0 should return False"
    assert "/user/api" in called_endpoints, "Should call /user/api endpoint"


@pytest.mark.asyncio
async def test_is_correct_api_version_returns_true_for_v20():
    """Test that is_correct_api_version returns True for future API versions.

    This test verifies:
    - Future API versions (e.g., 2.0) are correctly identified as compatible
    - Returns True for version 2.0
    - Correct endpoint /user/api is called
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock API response with version 2.0
    api_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<api version="2.0"/>'
        '</eta>'
    )

    called_endpoints = []

    async def mock_get_request(suffix):
        called_endpoints.append(suffix)
        response = AsyncMock()
        response.text = AsyncMock(return_value=api_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.is_correct_api_version()

    assert result is True, "API version 2.0 should return True"
    assert "/user/api" in called_endpoints, "Should call /user/api endpoint"


@pytest.mark.asyncio
async def test_does_endpoint_exists_returns_true_on_success():
    """Test that does_endpoint_exists returns True when the endpoint is accessible.

    This test verifies:
    - Returns True when get_menu() succeeds
    - No exceptions are raised
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock successful get_menu response
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu></menu>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=menu_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.does_endpoint_exists()

    assert result is True, "Should return True when endpoint is accessible"


@pytest.mark.asyncio
async def test_does_endpoint_exists_returns_false_on_timeout():
    """Test that does_endpoint_exists returns False when the request times out.

    This test verifies:
    - Returns False when asyncio.TimeoutError is raised
    - Exception is caught and handled gracefully
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock get_menu to raise TimeoutError
    async def mock_get_request(suffix):
        raise asyncio.TimeoutError("Connection timeout")

    api._http.get_request = mock_get_request

    result = await api.does_endpoint_exists()

    assert result is False, "Should return False when request times out"


@pytest.mark.asyncio
async def test_does_endpoint_exists_returns_false_on_client_error():
    """Test that does_endpoint_exists returns False on client errors.

    This test verifies:
    - Returns False when ClientError is raised (connection issues, etc.)
    - Exception is caught and handled gracefully
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock get_menu to raise ClientError
    async def mock_get_request(suffix):
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    result = await api.does_endpoint_exists()

    assert result is False, "Should return False when ClientError is raised"


@pytest.mark.asyncio
async def test_does_endpoint_exists_returns_false_on_http_error():
    """Test that does_endpoint_exists returns False on HTTP errors.

    This test verifies:
    - Returns False when ClientResponseError is raised (404, 500, etc.)
    - Exception is caught and handled gracefully
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock get_menu to raise ClientResponseError
    async def mock_get_request(suffix):
        raise ClientResponseError(
            request_info=AsyncMock(),
            history=(),
            status=404,
            message="Not Found"
        )

    api._http.get_request = mock_get_request

    result = await api.does_endpoint_exists()

    assert result is False, "Should return False when HTTP error occurs"


@pytest.mark.asyncio
async def test_does_endpoint_exists_returns_false_on_generic_exception():
    """Test that does_endpoint_exists returns False on any generic exception.

    This test verifies:
    - Returns False when any Exception is raised
    - Exception is caught and handled gracefully
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock get_menu to raise a generic exception
    async def mock_get_request(suffix):
        raise ValueError("Unexpected error")

    api._http.get_request = mock_get_request

    result = await api.does_endpoint_exists()

    assert result is False, "Should return False when generic exception is raised"


@pytest.mark.asyncio
async def test_does_endpoint_exists_returns_false_on_connection_refused():
    """Test that does_endpoint_exists returns False when connection is refused.

    This test verifies:
    - Returns False when ConnectionRefusedError is raised
    - Exception is caught and handled gracefully
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Mock get_menu to raise ConnectionRefusedError
    async def mock_get_request(suffix):
        raise ConnectionRefusedError("Connection refused")

    api._http.get_request = mock_get_request

    result = await api.does_endpoint_exists()

    assert result is False, "Should return False when connection is refused"


@pytest.mark.asyncio
async def test_get_api_version_parses_correctly():
    """Test that get_api_version correctly parses the API version from response.

    This test verifies:
    - Version is extracted from the correct XML path
    - Version is returned as a packaging.version.Version object
    - Can be compared with other versions
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    api_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<api version="1.2"/>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=api_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.get_api_version()

    # Check it returns a Version object
    from packaging.version import Version
    assert isinstance(result, Version), "Should return a Version object"
    assert str(result) == "1.2", "Should parse version as 1.2"


@pytest.mark.asyncio
async def test_get_api_version_handles_exceptions():
    """Test that get_api_version handles exceptions from _get_request.

    This test verifies:
    - Exceptions from _get_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_get_request(suffix):
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    with pytest.raises(ClientError):
        await api.get_api_version()


@pytest.mark.asyncio
async def test_get_data_returns_parsed_data(load_fixture):
    """Test that get_data returns correctly parsed sensor data.

    This test verifies:
    - Data is fetched from the correct endpoint
    - Response is parsed correctly
    - Returns tuple of (value, unit)
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    api_endpoint_data = load_fixture("api_endpoint_data.json")
    test_uri = "/120/10101/0/0/12197"
    expected_xml = api_endpoint_data[f"/user/var/{test_uri}"]

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=expected_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.get_data(test_uri)

    # Should return a tuple with value and unit
    assert isinstance(result, tuple), "Should return a tuple"
    assert len(result) == 2, "Should return (value, unit)"
    value, unit = result
    assert unit == "°C", "Should extract unit correctly"
    assert isinstance(value, (int, float)), "Value should be numeric"


@pytest.mark.asyncio
async def test_get_data_handles_exceptions():
    """Test that get_data handles exceptions from _get_request.

    This test verifies:
    - Exceptions from _get_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_get_request(suffix):
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    with pytest.raises(ClientError):
        await api.get_data("/120/10101/0/0/12197")


@pytest.mark.asyncio
async def test_get_data_with_force_number_handling():
    """Test that get_data correctly handles force_number_handling parameter.

    This test verifies:
    - force_number_handling=True forces numeric parsing even for non-float units
    - Value is correctly scaled
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # Sensor with a custom unit that's not in float_sensor_units
    custom_unit_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12345" strValue="100" '
        'unit="CustomUnit" decPlaces="0" scaleFactor="10" advTextOffset="0">1000</value>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=custom_unit_xml)
        return response

    api._http.get_request = mock_get_request

    # Without force_number_handling, should return string
    value_str, unit_str = await api.get_data("/120/10101/0/0/12345")
    assert value_str == "100", "Should return string value when unit not in float list"
    assert unit_str == "CustomUnit"

    # With force_number_handling, should return scaled number
    value_num, unit_num = await api.get_data("/120/10101/0/0/12345", force_number_handling=True)
    assert value_num == 100.0, "Should return scaled numeric value with force_number_handling"
    assert unit_num == "CustomUnit"


@pytest.mark.asyncio
async def test_get_data_with_force_string_handling():
    """Test that get_data correctly handles force_string_handling parameter.

    This test verifies:
    - force_string_handling=True returns string even for float units
    - Uses strValue instead of scaled numeric value
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    float_unit_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12197" strValue="20.5" '
        'unit="°C" decPlaces="1" scaleFactor="10" advTextOffset="0">205</value>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=float_unit_xml)
        return response

    api._http.get_request = mock_get_request

    # Without force_string_handling, should return scaled number
    value_num, unit_num = await api.get_data("/120/10101/0/0/12197")
    assert value_num == 20.5, "Should return scaled numeric value for float unit"
    assert unit_num == "°C"

    # With force_string_handling, should return string
    value_str, unit_str = await api.get_data("/120/10101/0/0/12197", force_string_handling=True)
    assert value_str == "20.5", "Should return string value with force_string_handling"
    assert unit_str == "°C"


@pytest.mark.asyncio
async def test_get_all_data_fetches_multiple_sensors(load_fixture):
    """Test that get_all_data fetches data from multiple sensors in parallel.

    This test verifies:
    - Multiple sensors are queried in parallel
    - Results are returned as a dictionary
    - Each sensor's data is correctly mapped to its URI
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    api_endpoint_data = load_fixture("api_endpoint_data.json")

    async def mock_get_request(suffix):
        response = AsyncMock()
        if suffix in api_endpoint_data:
            response.text = AsyncMock(return_value=api_endpoint_data[suffix])
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response

    api._http.get_request = mock_get_request

    # Test with multiple sensors
    sensor_list = {
        "/120/10101/0/0/12197": {},
        "/120/10101/0/0/12080": {},
    }

    result = await api.get_all_data(sensor_list)

    # Should return a dictionary
    assert isinstance(result, dict), "Should return a dictionary"
    assert len(result) > 0, "Should have results"
    # Check that URIs are in the results
    for uri in sensor_list.keys():
        if uri in result:
            assert isinstance(result[uri], (float, int, str)), f"Result for {uri} should be a value"


@pytest.mark.asyncio
async def test_get_all_data_handles_exceptions_gracefully():
    """Test that get_all_data handles exceptions for individual sensors.

    This test verifies:
    - Exceptions for individual sensors don't stop the entire fetch
    - Failed sensors are excluded from results
    - Successful sensors are still returned
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    call_count = 0

    async def mock_get_request(suffix):
        nonlocal call_count
        call_count += 1
        response = AsyncMock()
        if "12197" in suffix:
            # First sensor succeeds
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0">'
                '<value uri="/user/var/120/10101/0/0/12197" strValue="20" '
                'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
                '</eta>'
            )
        else:
            # Second sensor fails
            raise ClientError("Connection failed")
        return response

    api._http.get_request = mock_get_request

    sensor_list = {
        "/120/10101/0/0/12197": {},
        "/120/10101/0/0/99999": {},
    }

    result = await api.get_all_data(sensor_list)

    # Should have called both endpoints
    assert call_count == 2, "Should attempt to fetch from all sensors"
    # Should have result for successful sensor
    assert "/120/10101/0/0/12197" in result, "Should have result for successful sensor"
    # Should not have result for failed sensor
    assert "/120/10101/0/0/99999" not in result, "Should not have result for failed sensor"


@pytest.mark.asyncio
async def test_get_all_data_with_empty_sensor_list():
    """Test that get_all_data handles empty sensor list.

    This test verifies:
    - Returns empty dict when no sensors provided
    - No requests are made
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    call_count = 0

    async def mock_get_request(suffix):
        nonlocal call_count
        call_count += 1
        response = AsyncMock()
        response.text = AsyncMock(return_value='<eta></eta>')
        return response

    api._http.get_request = mock_get_request

    result = await api.get_all_data({})

    assert result == {}, "Should return empty dict for empty sensor list"
    assert call_count == 0, "Should not make any requests"


@pytest.mark.asyncio
async def test_get_all_data_when_all_sensors_fail():
    """Test that get_all_data handles all sensors failing.

    This test verifies:
    - Returns empty dict when all sensors raise exceptions
    - All sensors are attempted
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    call_count = 0

    async def mock_get_request(suffix):
        nonlocal call_count
        call_count += 1
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    sensor_list = {
        "/120/10101/0/0/12197": {},
        "/120/10101/0/0/12198": {},
        "/120/10101/0/0/12199": {},
    }

    result = await api.get_all_data(sensor_list)

    assert result == {}, "Should return empty dict when all sensors fail"
    assert call_count == 3, "Should attempt all sensors"


@pytest.mark.asyncio
async def test_get_all_data_respects_concurrent_request_limit():
    """Test that get_all_data respects the max concurrent requests limit.

    This test verifies:
    - Maximum of api._http.max_concurrent_requests concurrent requests are active at any time
    - All api._http.max_concurrent_requests*2 sensors are eventually processed
    - Concurrency limit is properly enforced
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    current_concurrent = 0
    max_concurrent = 0
    completed_count = 0

    async def mock_get_request(suffix):
        nonlocal current_concurrent, max_concurrent, completed_count

        # Increment concurrent counter
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)

        # Simulate some work with a small delay
        # This sleep is necessary to give control back to the event loop and allow other requests to start, which is essential for testing concurrency limits
        await asyncio.sleep(0.02)

        # Decrement concurrent counter
        current_concurrent -= 1
        completed_count += 1

        # Return mock response
        response = AsyncMock()
        response.text = AsyncMock(
            return_value='<?xml version="1.0" encoding="utf-8"?>'
            '<eta version="1.0">'
            '<value uri="/user/var/120/10101/0/0/12197" strValue="20" '
            'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
            '</eta>'
        )
        return response

    api._http.get_request = mock_get_request

    # Create api._http.max_concurrent_requests*2 sensors to ensure we exceed the limit of api._http.max_concurrent_requests
    sensor_list = {
        f"/120/10101/0/0/1219{i}": {}
        for i in range(api._http.max_concurrent_requests*2)
    }

    result = await api.get_all_data(sensor_list)

    # Verify concurrent limit was respected
    assert max_concurrent <= api._http.max_concurrent_requests, (
        f"Maximum concurrent requests should be <= {api._http.max_concurrent_requests}, but was {max_concurrent}"
    )
    assert max_concurrent > 1, "Should have some concurrency"
    assert completed_count == len(sensor_list), "Should have completed all requests"
    assert len(result) == len(sensor_list), "Should have results for all sensors"


@pytest.mark.asyncio
async def test_get_all_data_passes_force_number_handling():
    """Test that get_all_data passes force_number_handling per sensor.

    This test verifies:
    - Sensors with force_number_handling=True return a numeric value even for custom units
    - Sensors without force_number_handling return a string for custom units
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    custom_unit_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12345" strValue="100" '
        'unit="CustomUnit" decPlaces="0" scaleFactor="10" advTextOffset="0">1000</value>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=custom_unit_xml)
        return response

    api._http.get_request = mock_get_request

    sensor_list = {
        "/120/10101/0/0/12345": {"force_number_handling": True},
        "/120/10101/0/0/12346": {},
    }

    result = await api.get_all_data(sensor_list)

    assert result["/120/10101/0/0/12345"] == 100.0, (
        "force_number_handling=True should return scaled numeric value"
    )
    assert result["/120/10101/0/0/12346"] == "100", (
        "Default should return string value for custom unit"
    )


@pytest.mark.asyncio
async def test_get_all_data_passes_force_string_handling():
    """Test that get_all_data passes force_string_handling per sensor.

    This test verifies:
    - Sensors with force_string_handling=True return a string even for float units
    - Sensors without force_string_handling return a numeric value for float units
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    float_unit_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12197" strValue="20.5" '
        'unit="°C" decPlaces="1" scaleFactor="10" advTextOffset="0">205</value>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=float_unit_xml)
        return response

    api._http.get_request = mock_get_request

    sensor_list = {
        "/120/10101/0/0/12197": {"force_string_handling": True},
        "/120/10101/0/0/12198": {},
    }

    result = await api.get_all_data(sensor_list)

    assert result["/120/10101/0/0/12197"] == "20.5", (
        "force_string_handling=True should return string value"
    )
    assert result["/120/10101/0/0/12198"] == 20.5, (
        "Default should return scaled numeric value for float unit"
    )


@pytest.mark.asyncio
async def test_get_menu_returns_menu_data(load_fixture):
    """Test that get_menu returns the menu structure.

    This test verifies:
    - Menu data is fetched
    - Returns the parsed menu structure
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    api_endpoint_data = load_fixture("api_endpoint_data.json")
    menu_xml = api_endpoint_data["/user/menu"]

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=menu_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.get_menu()

    # Should return parsed menu data
    assert result is not None, "Should return menu data"
    assert isinstance(result, dict), "Should return a dictionary"


@pytest.mark.asyncio
async def test_get_menu_handles_exceptions():
    """Test that get_menu handles exceptions from _get_request.

    This test verifies:
    - Exceptions from _get_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_get_request(suffix):
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    with pytest.raises(ClientError):
        await api.get_menu()


@pytest.mark.asyncio
async def test_get_errors_returns_empty_list_when_no_errors():
    """Test that get_errors returns empty list when fub elements have no errors.

    This test verifies:
    - Fub elements without error children are handled correctly
    - Returns empty list when all fubs are empty
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # XML with fub elements but no error children
    errors_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<errors uri="/user/errors">'
        '<fub uri="/112/10021" name="Kessel"/>'
        '<fub uri="/112/10101" name="HK1"/>'
        '</errors>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=errors_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.get_errors()

    assert result == [], "Should return empty list when fubs have no errors"


@pytest.mark.asyncio
async def test_get_errors_returns_list_of_errors():
    """Test that get_errors returns a list of error objects.

    This test verifies:
    - Error data is parsed correctly from fub elements
    - Returns list of ETAError objects
    - Correctly handles the fub/error structure
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    # XML with errors - matching the actual API structure
    errors_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<errors uri="/user/errors">'
        '<fub uri="/112/10021" name="Kessel">'
        '<error msg="Flue gas sensor Interrupted" priority="Error" '
        'time="2011-06-29 12:47:50">Sensor or Cable broken or badly connected</error>'
        '<error msg="Water pressure too low 0,00 bar" priority="Error" '
        'time="2011-06-29 12:48:12">Top up heating water!</error>'
        '</fub>'
        '<fub uri="/112/10101" name="HK1"/>'
        '</errors>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=errors_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.get_errors()

    assert isinstance(result, list), "Should return a list"
    assert len(result) > 0, "Should have at least one error"
    assert len(result) == 2, "Should have two errors"


@pytest.mark.asyncio
async def test_get_errors_handles_exceptions():
    """Test that get_errors handles exceptions from _get_request.

    This test verifies:
    - Exceptions from _get_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_get_request(suffix):
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    with pytest.raises(ClientError):
        await api.get_errors()


@pytest.mark.asyncio
async def test_get_switch_state_returns_integer():
    """Test that get_switch_state returns the switch state as an integer.

    This test verifies:
    - Switch state is fetched from correct endpoint
    - Returns integer value (like 1802 or 1803)
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    switch_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12080" strValue="Ein" '
        'unit="" decPlaces="0" scaleFactor="1" advTextOffset="0">1803</value>'
        '</eta>'
    )

    async def mock_get_request(suffix):
        response = AsyncMock()
        response.text = AsyncMock(return_value=switch_xml)
        return response

    api._http.get_request = mock_get_request

    result = await api.get_switch_state("/120/10101/0/0/12080")

    assert isinstance(result, int), "Should return an integer"
    assert result == 1803, "Should return the switch state value"


@pytest.mark.asyncio
async def test_get_switch_state_handles_exceptions():
    """Test that get_switch_state handles exceptions from _get_request.

    This test verifies:
    - Exceptions from _get_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_get_request(suffix):
        raise ClientError("Connection failed")

    api._http.get_request = mock_get_request

    with pytest.raises(ClientError):
        await api.get_switch_state("/120/10101/0/0/12080")


@pytest.mark.asyncio
async def test_set_switch_state_sends_correct_data():
    """Test that set_switch_state sends the correct data to the endpoint.

    This test verifies:
    - POST request is made to correct endpoint
    - Correct state value is sent
    - Returns True on success
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    posted_data = {}
    posted_uri = None

    async def mock_post_request(suffix, data):
        nonlocal posted_uri, posted_data
        posted_uri = suffix
        posted_data = data
        response = AsyncMock()
        response.text = AsyncMock(return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><success/></eta>')
        return response

    api._http.post_request = mock_post_request

    result = await api.set_switch_state("/120/10101/0/0/12080", 1803)

    assert result is True, "Should return True on success"
    assert posted_uri == "/user/var//120/10101/0/0/12080", "Should post to correct URI"
    assert posted_data == {"value": 1803}, "Should send correct data"


@pytest.mark.asyncio
async def test_write_endpoint_with_value_only():
    """Test that write_endpoint sends only value when specified.

    This test verifies:
    - POST request is made with value parameter
    - Other parameters are not included when not specified
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    posted_data = {}
    posted_uri = None

    async def mock_post_request(suffix, data):
        nonlocal posted_uri, posted_data
        posted_uri = suffix
        posted_data = data
        response = AsyncMock()
        response.text = AsyncMock(return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><success/></eta>')
        return response

    api._http.post_request = mock_post_request

    result = await api.write_endpoint("/120/10101/0/0/12132", value=300)

    assert result is True, "Should return True on success"
    assert posted_uri == "/user/var//120/10101/0/0/12132", "Should post to correct URI"
    assert posted_data == {"value": 300}, "Should send only value"
    assert "begin" not in posted_data, "Should not include begin parameter"
    assert "end" not in posted_data, "Should not include end parameter"


@pytest.mark.asyncio
async def test_write_endpoint_with_all_parameters():
    """Test that write_endpoint sends all parameters when specified.

    This test verifies:
    - POST request includes value, begin, and end when provided
    - All parameters are correctly formatted
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    posted_data = {}
    posted_uri = None

    async def mock_post_request(suffix, data):
        nonlocal posted_uri, posted_data
        posted_uri = suffix
        posted_data = data
        response = AsyncMock()
        response.text = AsyncMock(return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><success/></eta>')
        return response

    api._http.post_request = mock_post_request

    result = await api.write_endpoint(
        "/120/10101/0/0/12132", value=300, begin="08:00", end="18:00"
    )

    assert result is True, "Should return True on success"
    assert posted_uri == "/user/var//120/10101/0/0/12132", "Should post to correct URI"
    assert posted_data == {
        "value": 300,
        "begin": "08:00",
        "end": "18:00"
    }, "Should send all parameters"


@pytest.mark.asyncio
async def test_write_endpoint_with_begin_and_end_only():
    """Test that write_endpoint can send begin/end without value.

    This test verifies:
    - POST request can be made with only begin and end parameters
    - Value parameter is not required
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    posted_data = {}
    posted_uri = None

    async def mock_post_request(suffix, data):
        nonlocal posted_uri, posted_data
        posted_uri = suffix
        posted_data = data
        response = AsyncMock()
        response.text = AsyncMock(return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><success/></eta>')
        return response

    api._http.post_request = mock_post_request

    result = await api.write_endpoint(
        "/120/10101/0/0/12132", begin="08:00", end="18:00"
    )

    assert result is True, "Should return True on success"
    assert posted_data == {"begin": "08:00", "end": "18:00"}, "Should send begin and end only"
    assert "value" not in posted_data, "Should not include value parameter"


@pytest.mark.asyncio
async def test_set_switch_state_returns_false_on_failure():
    """Test that set_switch_state returns False when API returns non-success response.

    This test verifies:
    - Returns False when response doesn't contain success element
    - Handles failure gracefully without raising exception
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_post_request(suffix, data):
        response = AsyncMock()
        response.text = AsyncMock(
            return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><value>1802</value></eta>'
        )
        return response

    api._http.post_request = mock_post_request

    result = await api.set_switch_state("/120/10101/0/0/12080", 1803)

    assert result is False, "Should return False when response doesn't contain success"


@pytest.mark.asyncio
async def test_set_switch_state_handles_exceptions():
    """Test that set_switch_state handles exceptions from _post_request.

    This test verifies:
    - Exceptions from _post_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_post_request(suffix, data):
        raise ClientError("Connection failed")

    api._http.post_request = mock_post_request

    # Should raise the exception
    with pytest.raises(ClientError):
        await api.set_switch_state("/120/10101/0/0/12080", 1803)


@pytest.mark.asyncio
async def test_set_switch_state_with_off_state():
    """Test that set_switch_state works with off state (1802).

    This test verifies:
    - Can set switch to off state
    - Correctly sends value 1802
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    posted_data = {}

    async def mock_post_request(suffix, data):
        nonlocal posted_data
        posted_data = data
        response = AsyncMock()
        response.text = AsyncMock(
            return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><success uri="/user/var/120/10101/0/0/12080"/></eta>'
        )
        return response

    api._http.post_request = mock_post_request

    result = await api.set_switch_state("/120/10101/0/0/12080", 1802)

    assert result is True, "Should return True on success"
    assert posted_data == {"value": 1802}, "Should send off state value (1802)"


@pytest.mark.asyncio
async def test_write_endpoint_returns_false_on_error_response():
    """Test that write_endpoint returns False when API returns error.

    This test verifies:
    - Returns False when response contains error element
    - Error is logged appropriately
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_post_request(suffix, data):
        response = AsyncMock()
        response.text = AsyncMock(
            return_value='<?xml version="1.0" encoding="utf-8"?>'
            '<eta version="1.0"><error>Invalid value</error></eta>'
        )
        return response

    api._http.post_request = mock_post_request

    result = await api.write_endpoint("/120/10101/0/0/12132", value=9999)

    assert result is False, "Should return False when API returns error"


@pytest.mark.asyncio
async def test_write_endpoint_returns_false_on_invalid_response():
    """Test that write_endpoint returns False when response has neither success nor error.

    This test verifies:
    - Returns False when response is invalid/unexpected
    - Handles unexpected responses gracefully
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_post_request(suffix, data):
        response = AsyncMock()
        response.text = AsyncMock(
            return_value='<?xml version="1.0" encoding="utf-8"?>'
            '<eta version="1.0"><unknown>response</unknown></eta>'
        )
        return response

    api._http.post_request = mock_post_request

    result = await api.write_endpoint("/120/10101/0/0/12132", value=300)

    assert result is False, "Should return False when response is invalid"


@pytest.mark.asyncio
async def test_write_endpoint_handles_exceptions():
    """Test that write_endpoint handles exceptions from _post_request.

    This test verifies:
    - Exceptions from _post_request propagate to caller
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    async def mock_post_request(suffix, data):
        raise ClientError("Connection failed")

    api._http.post_request = mock_post_request

    # Should raise the exception
    with pytest.raises(ClientError):
        await api.write_endpoint("/120/10101/0/0/12132", value=300)


@pytest.mark.asyncio
async def test_write_endpoint_with_empty_payload():
    """Test that write_endpoint handles empty payload (all params None).

    This test verifies:
    - Can be called with all parameters as None
    - Sends empty payload to API
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)

    posted_data = {}

    async def mock_post_request(suffix, data):
        nonlocal posted_data
        posted_data = data
        response = AsyncMock()
        response.text = AsyncMock(
            return_value='<?xml version="1.0" encoding="utf-8"?><eta version="1.0"><success uri="/user/var/120/10101/0/0/12132"/></eta>'
        )
        return response

    api._http.post_request = mock_post_request

    result = await api.write_endpoint("/120/10101/0/0/12132")

    assert result is True, "Should return True on success"
    assert posted_data == {}, "Should send empty payload when no parameters provided"


@pytest.mark.asyncio
async def test_get_all_switch_states_handles_exceptions():
    """Test that get_all_switch_states maps results and keeps exceptions per endpoint."""
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080, max_concurrent_requests=2)

    async def mock_get_switch_state(uri):
        if uri.endswith("/ok"):
            return 1803
        raise RuntimeError("switch read failed")

    api.get_switch_state = mock_get_switch_state

    results = await api.get_all_switch_states(["/120/1/ok", "/120/1/fail"])

    assert results["/120/1/ok"] == 1803
    assert isinstance(results["/120/1/fail"], RuntimeError)
