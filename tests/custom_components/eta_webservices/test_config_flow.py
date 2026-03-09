"""Unit tests for config_flow helper logic."""

from custom_components.eta_webservices.config_flow import (
    _is_invalid_host_input,
    _sanitize_selected_entity_ids,
)


def test_sanitize_selected_entity_ids_removes_cross_category_duplicates():
    """IDs selected in multiple regular sensor groups must be deduplicated."""
    selected_float_sensors = ["a", "b", "a"]
    selected_switches = ["b", "c", "c"]
    selected_text_sensors = ["a", "c", "d", "d"]
    selected_writable_sensors = ["w1", "w1"]
    selected_pending_sensors = ["a", "d", "e", "e"]

    (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
        sanitized_pending_sensors,
    ) = _sanitize_selected_entity_ids(
        selected_float_sensors,
        selected_switches,
        selected_text_sensors,
        selected_writable_sensors,
        selected_pending_sensors,
    )

    assert sanitized_float_sensors == ["a", "b"]
    assert sanitized_switches == ["c"]
    assert sanitized_text_sensors == ["d"]
    assert sanitized_writable_sensors == ["w1"]
    assert sanitized_pending_sensors == ["e"]


def test_sanitize_selected_entity_ids_keeps_non_overlapping_selections():
    """Selections without overlaps should remain unchanged."""
    selected_float_sensors = ["float_1"]
    selected_switches = ["switch_1"]
    selected_text_sensors = ["text_1"]
    selected_writable_sensors = ["writable_1", "writable_2"]
    selected_pending_sensors = ["pending_1"]

    (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
        sanitized_pending_sensors,
    ) = _sanitize_selected_entity_ids(
        selected_float_sensors,
        selected_switches,
        selected_text_sensors,
        selected_writable_sensors,
        selected_pending_sensors,
    )

    assert sanitized_float_sensors == selected_float_sensors
    assert sanitized_switches == selected_switches
    assert sanitized_text_sensors == selected_text_sensors
    assert sanitized_writable_sensors == selected_writable_sensors
    assert sanitized_pending_sensors == selected_pending_sensors


def test_is_invalid_host_input_rejects_malformed_hosts():
    """Malformed host inputs must be rejected before discovery starts."""
    assert _is_invalid_host_input(":")
    assert _is_invalid_host_input("%")
    assert _is_invalid_host_input("host name")
    assert _is_invalid_host_input("foo_bar.local")
    assert _is_invalid_host_input("-eta.local")
    assert _is_invalid_host_input("eta-.local")
    assert _is_invalid_host_input("http://172.24.120.210")
    assert _is_invalid_host_input("172.24.120.210/path")
    assert _is_invalid_host_input("[172.24.120.210]")
    assert _is_invalid_host_input("[::")


def test_is_invalid_host_input_accepts_valid_hosts():
    """Normal hostname/IP inputs should be accepted."""
    assert not _is_invalid_host_input("172.24.120.210")
    assert not _is_invalid_host_input("eta.local")
    assert not _is_invalid_host_input("[2001:db8::1]")
