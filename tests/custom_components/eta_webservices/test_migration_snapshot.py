"""Tests for the migration snapshot."""

from types import MappingProxyType
from unittest.mock import AsyncMock, Mock, patch

from custom_components.eta_webservices import migration_snapshot


async def test_snapshot_stores_entry_devices_and_entities():
    """Snapshot stores entry devices and entities."""
    device = Mock(
        id="device",
        identifiers={("eta_webservices", "eta_1_2_3_4_8080")},
        name_by_user="Boiler",
        area_id="cellar",
        disabled_by=None,
        labels={"heating"},
    )
    device.name = "ETA"
    entity = Mock(
        entity_id="sensor.eta",
        unique_id="unique",
        device_id="device",
        icon=None,
        area_id=None,
        disabled_by=None,
        hidden_by=None,
        labels=set(),
        options=MappingProxyType(
            {"sensor": MappingProxyType({"suggested_display_precision": 1})}
        ),
        original_name="Eta",
        original_device_class=None,
        unit_of_measurement="kg",
        entity_category=None,
    )
    entity.name = "Custom"
    entry = Mock(
        entry_id="entry",
        version=8,
        minor_version=1,
        title="ETA",
        data={"host": "1.2.3.4", "update_interval": 60},
        options={"update_interval": 30},
    )
    store = Mock(
        async_load=AsyncMock(return_value={"other": {}}), async_save=AsyncMock()
    )

    with (
        patch.object(migration_snapshot, "Store", return_value=store),
        patch.object(migration_snapshot.dr, "async_get"),
        patch.object(migration_snapshot.er, "async_get"),
        patch.object(
            migration_snapshot.dr,
            "async_entries_for_config_entry",
            return_value=[device],
        ),
        patch.object(
            migration_snapshot.er,
            "async_entries_for_config_entry",
            return_value=[entity],
        ),
    ):
        await migration_snapshot.async_save_snapshot(Mock(), entry)

    saved = store.async_save.await_args.args[0]
    assert "other" in saved
    snapshot = saved["entry"]
    assert snapshot["version"] == 8
    assert snapshot["data"]["update_interval"] == 30
    assert snapshot["devices"][0]["identifiers"] == [
        ["eta_webservices", "eta_1_2_3_4_8080"]
    ]
    assert snapshot["devices"][0]["name"] == "ETA"
    assert snapshot["entities"][0]["entity_id"] == "sensor.eta"
    assert snapshot["entities"][0]["name"] == "Custom"
    assert (
        snapshot["entities"][0]["device_identifiers"]
        == (snapshot["devices"][0]["identifiers"])
    )
    assert snapshot["entities"][0]["options"] == {
        "sensor": {"suggested_display_precision": 1}
    }
