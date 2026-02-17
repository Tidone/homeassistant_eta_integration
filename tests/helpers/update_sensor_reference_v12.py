#!/usr/bin/env python3
"""Update api_assignment_reference_values_v12.json fixture with discovered sensors.

This script calls _get_all_sensors_v12 with mocked API calls using data from
api_endpoint_data.json fixture, then updates the reference file with discovered sensors.

Update Modes:
  add-new: Only add newly detected sensors, keep existing sensors unchanged
  update:  Add new sensors AND update existing sensors with current values
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock

# Add parent's parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from aiohttp import ClientSession

from custom_components.eta_webservices.api import EtaAPI

_LOGGER = logging.getLogger(__name__)


class MockedETAAPI:
    """Creates EtaAPI instance with mocked _get_request."""

    def __init__(self, fixture_data: dict, host: str, port: int):
        """Initialize mocked API.

        Args:
            fixture_data: Dictionary mapping endpoint paths to XML responses
            host: Mock host address
            port: Mock port number
        """
        # Create mock session (won't be used)
        mock_session = AsyncMock(spec=ClientSession)

        # Create real EtaAPI instance
        self.api = EtaAPI(mock_session, host, port)

        # Replace _get_request with mock version
        self.api._get_request = self._mock_get_request
        self.fixture_data = fixture_data
        self.request_log = []  # Track requests for debugging

    async def _mock_get_request(self, suffix: str):
        """Return fixture data for given endpoint.

        Args:
            suffix: The endpoint path (e.g., "/user/menu")

        Returns:
            Mock response object with text() method
        """
        self.request_log.append(suffix)

        response = AsyncMock()
        if suffix in self.fixture_data:
            response.text = AsyncMock(return_value=self.fixture_data[suffix])
            _LOGGER.debug("Mocked request for %s: found in fixture", suffix)
        else:
            # Return error XML for missing endpoints
            error_xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
            response.text = AsyncMock(return_value=error_xml)
            _LOGGER.debug("Mocked request for %s: not found, returning error", suffix)

        return response


class SensorUpdater:
    """Handles updating sensor reference fixture with different modes."""

    def __init__(self, mode: str):
        """Initialize updater.

        Args:
            mode: "add-new" or "update"
        """
        self.mode = mode
        self.stats = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0}

    def update_reference(self, discovered: dict, existing: dict) -> dict:
        """Update reference data based on mode.

        Args:
            discovered: The 4 dictionaries from _get_all_sensors_v12
            existing: The current reference file content

        Returns:
            Updated reference data
        """
        updated = {}

        for category in ["float_dict", "switches_dict", "text_dict", "writable_dict"]:
            updated[category] = self._update_category(
                category, discovered[category], existing[category]
            )

        return updated

    def _update_category(self, category: str, discovered: dict, existing: dict) -> dict:
        """Update one category based on mode.

        Args:
            category: Category name (float_dict, switches_dict, etc.)
            discovered: Sensors discovered by _get_all_sensors_v12
            existing: Current sensors in reference file

        Returns:
            Updated sensor dictionary for this category
        """
        if self.mode == "add-new":
            # Start with existing, add only new sensors
            result = {**existing}

            for key, sensor in discovered.items():
                if key not in existing:
                    result[key] = sensor
                    self.stats["added"] += 1
                    _LOGGER.debug("Adding new sensor: %s.%s", category, key)
                else:
                    self.stats["unchanged"] += 1

            # Track removed sensors (in existing but not in discovered)
            for key in existing:
                if key not in discovered:
                    self.stats["removed"] += 1
                    _LOGGER.debug("Sensor removed from discovery: %s.%s", category, key)

        elif self.mode == "update":
            # Use discovered as base, which has all current sensors with current values
            result = {**discovered}

            # Track statistics
            for key in discovered:
                if key not in existing:
                    self.stats["added"] += 1
                    _LOGGER.debug("Adding new sensor: %s.%s", category, key)
                elif discovered[key] != existing[key]:
                    self.stats["updated"] += 1
                    _LOGGER.debug("Updating sensor: %s.%s", category, key)
                else:
                    self.stats["unchanged"] += 1

            for key in existing:
                if key not in discovered:
                    self.stats["removed"] += 1
                    _LOGGER.debug("Sensor removed from discovery: %s.%s", category, key)

        return result

    def print_summary(self):
        """Print update summary."""
        print("\n" + "=" * 70)
        print("=== Update Summary ===")
        print(f"Mode: {self.mode}")
        print(f"Added:     {self.stats['added']} new sensors")
        print(f"Updated:   {self.stats['updated']} existing sensors")
        print(f"Unchanged: {self.stats['unchanged']} sensors")
        if self.stats["removed"] > 0:
            print(
                f"Removed:   {self.stats['removed']} sensors (not in discovered set)"
            )
        print("=" * 70)


def load_json(path: Path) -> dict:
    """Load and parse JSON file.

    Args:
        path: Path to JSON file

    Returns:
        Parsed JSON data

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    """Save data as JSON file with proper formatting.

    Args:
        path: Path to save JSON file
        data: Data to save
    """
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")  # Add trailing newline


def create_backup(path: Path) -> Path:
    """Create timestamped backup of file.

    Args:
        path: Path to file to backup

    Returns:
        Path to backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".json.backup.{timestamp}")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


async def run_update(args) -> int:
    """Main fixture update execution.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Load fixtures
        print("Loading fixtures...")
        endpoint_data = load_json(args.endpoint_data)
        reference_values = load_json(args.reference_values)
        print(
            f"  Loaded {len(endpoint_data)} endpoint responses from {args.endpoint_data}"
        )
        print(f"  Loaded reference data from {args.reference_values}")

        # Create mocked API
        print(f"\nCreating mocked API (host={args.host}, port={args.port})...")
        mocked = MockedETAAPI(endpoint_data, args.host, args.port)

        # Initialize empty dictionaries
        float_dict = {}
        switches_dict = {}
        text_dict = {}
        writable_dict = {}

        # Call _get_all_sensors_v12
        print("Running _get_all_sensors_v12 to discover sensors...")
        await mocked.api._get_all_sensors_v12(
            float_dict, switches_dict, text_dict, writable_dict
        )

        # Print discovered sensor counts
        total_discovered = (
            len(float_dict) + len(switches_dict) + len(text_dict) + len(writable_dict)
        )
        print(f"\nDiscovered sensors:")
        print(f"  Float:    {len(float_dict)}")
        print(f"  Switches: {len(switches_dict)}")
        print(f"  Text:     {len(text_dict)}")
        print(f"  Writable: {len(writable_dict)}")
        print(f"  TOTAL:    {total_discovered}")

        _LOGGER.debug("Made %d mock requests", len(mocked.request_log))

        # Update reference based on mode
        print(f"\nUpdating reference fixture (mode: {args.mode})...")
        updater = SensorUpdater(args.mode)

        discovered = {
            "float_dict": float_dict,
            "switches_dict": switches_dict,
            "text_dict": text_dict,
            "writable_dict": writable_dict,
        }

        updated_reference = updater.update_reference(discovered, reference_values)

        # Print summary
        updater.print_summary()

        # Confirm update unless --yes flag is set
        if not args.yes:
            if updater.stats["added"] == 0 and updater.stats["updated"] == 0:
                print("\nNo changes to write.")
                return 0

            response = input(f"\nWrite changes to {args.reference_values}? [y/N]: ")
            if response.lower() not in ["y", "yes"]:
                print("Update cancelled.")
                return 0

        # Create backup and save updated reference
        if updater.stats["added"] > 0 or updater.stats["updated"] > 0:
            backup_path = create_backup(args.reference_values)
            print(f"\n✓ Created backup: {backup_path}")

            save_json(args.reference_values, updated_reference)
            print(f"✓ Updated: {args.reference_values}")
        else:
            print("\nNo changes to write.")

        return 0

    except FileNotFoundError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"\nERROR: Invalid JSON in fixture file: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


def parse_args():
    """Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Update api_assignment_reference_values_v12.json fixture with discovered sensors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Update Modes:
  add-new  - Only add newly detected sensors, keep existing sensors unchanged
  update   - Add new sensors AND update existing sensors with current values

Examples:
  # Add only new sensors discovered from fixture data
  %(prog)s --mode add-new

  # Update all sensors with current values from fixture data
  %(prog)s --mode update --yes

  # Use custom fixture paths
  %(prog)s --mode add-new --endpoint-data custom.json --reference-values custom_ref.json
    """,
    )

    parser.add_argument(
        "--mode",
        choices=["add-new", "update"],
        required=True,
        help="Update mode: 'add-new' (add only new sensors) or 'update' (add new + update existing)",
    )

    parser.add_argument(
        "--endpoint-data",
        type=Path,
        default=Path("../fixtures/api_endpoint_data.json"),
        help="Path to api_endpoint_data.json (default: ../fixtures/api_endpoint_data.json)",
    )

    parser.add_argument(
        "--reference-values",
        type=Path,
        default=Path("../fixtures/api_assignment_reference_values_v12.json"),
        help="Path to api_assignment_reference_values_v12.json",
    )

    parser.add_argument(
        "--host",
        default="192.168.0.25",
        help="Mock host address (default: 192.168.0.25)",
    )

    parser.add_argument(
        "--port", type=int, default=8080, help="Mock port (default: 8080)"
    )

    parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt"
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output with debug logging",
    )

    return parser.parse_args()


def main():
    """Entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Display configuration
    print("=" * 70)
    print("ETA Sensor Reference Fixture Update")
    print("=" * 70)
    print(f"Mode: {args.mode}")
    print(f"Endpoint data: {args.endpoint_data}")
    print(f"Reference values: {args.reference_values}")
    print(f"Mock host: {args.host}:{args.port}")
    print("=" * 70)

    # Run update
    return asyncio.run(run_update(args))


if __name__ == "__main__":
    sys.exit(main())
