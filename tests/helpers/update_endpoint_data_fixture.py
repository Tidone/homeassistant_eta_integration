#!/usr/bin/env python3

"""Update test fixture with fresh data from ETA API.

This script connects to a real ETA device, fetches menu data and all endpoint
responses, and updates the test fixture file (api_endpoint_data.json) with
fresh data. This ensures tests use realistic, current API responses.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from time import time

import aiohttp
import xmltodict

# Add parent's parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from custom_components.eta_webservices.api import EtaAPI


class FixtureUpdater:
    """Manages updating api_endpoint_data.json with fresh ETA API data."""

    def __init__(
        self,
        host: str,
        port: int,
        fixture_path: Path,
        mode: str,
        timeout: int,
        max_concurrent: int,
    ):
        """Initialize the fixture updater.

        Args:
            host: ETA device hostname or IP address
            port: ETA device port number
            fixture_path: Path to fixture file
            mode: Update mode (update, refresh, add-only)
            timeout: Request timeout in seconds
            max_concurrent: Maximum concurrent requests
        """
        self.host = host
        self.port = port
        self.fixture_path = fixture_path
        self.mode = mode
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.api: Optional[EtaAPI] = None
        self.session: Optional[aiohttp.ClientSession] = None

        # Statistics tracking
        self.stats = {
            "uris_found": 0,
            "duplicates": 0,
            "varinfo_success": 0,
            "varinfo_failed": 0,
            "var_success": 0,
            "var_failed": 0,
            "added": 0,
            "updated": 0,
            "unchanged": 0,
        }
        self.failed_endpoints: List[Tuple[str, str]] = []
        self.start_time: float = 0

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        self.api = EtaAPI(self.session, self.host, self.port)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    async def fetch_menu(self) -> str:
        """Fetch /user/menu and return raw XML string.

        Returns:
            Raw XML response from /user/menu endpoint

        Raises:
            RuntimeError: If menu fetch fails
        """
        logging.info("Fetching menu...")
        try:
            response = await self.api._get_request("/user/menu")
            if response.status != 200:
                raise RuntimeError(
                    f"Menu fetch failed with status {response.status}"
                )
            menu_xml = await response.text()
            logging.debug(f"Menu XML length: {len(menu_xml)} bytes")
            return menu_xml
        except Exception as e:
            logging.error(f"Failed to fetch menu: {e}")
            raise RuntimeError(f"Menu fetch failed: {e}") from e

    def extract_uris_from_menu(self, menu_xml: str) -> Dict[str, str]:
        """Parse menu XML and extract all unique URIs.

        Uses same logic as EtaAPI._evaluate_xml_dict() to ensure consistency.

        Args:
            menu_xml: Raw XML from /user/menu endpoint

        Returns:
            Dict mapping URI -> FUB name
            Example: {"/120/10111/0/0/10990": "WW", ...}
        """
        logging.info("Parsing menu to extract URIs...")

        # Parse XML
        menu_data = xmltodict.parse(menu_xml)

        # Extract FUB(s) - can be single fub or list of fubs
        menu_root = menu_data.get("eta", {}).get("menu", {})
        fubs = menu_root.get("fub", [])

        # Ensure fubs is a list
        if not isinstance(fubs, list):
            fubs = [fubs]

        # Extract URIs from each FUB
        uri_to_fub: Dict[str, str] = {}
        uri_dict: Dict[str, List[str]] = {}

        for fub in fubs:
            fub_name = fub.get("@name", "Unknown")
            fub_uri = fub.get("@uri", "")

            # Process the FUB itself
            if fub_uri:
                if fub_uri not in uri_to_fub:
                    uri_to_fub[fub_uri] = fub_name
                else:
                    self.stats["duplicates"] += 1
                    logging.debug(f"Duplicate URI: {fub_uri} (FUB: {fub_name})")

            # Recursively process objects within the FUB
            if "object" in fub:
                self._extract_uris_recursive(
                    fub["object"], fub_name, uri_to_fub, uri_dict, prefix=""
                )

        self.stats["uris_found"] = len(uri_to_fub)
        logging.info(
            f"✓ Menu retrieved: {self.stats['uris_found']} unique URIs found "
            f"({self.stats['duplicates']} duplicates skipped)"
        )

        return uri_to_fub

    def _extract_uris_recursive(
        self,
        xml_dict,
        fub_name: str,
        uri_to_fub: Dict[str, str],
        uri_dict: Dict[str, List[str]],
        prefix: str,
    ):
        """Recursively extract URIs from XML dict structure.

        This mirrors the logic from EtaAPI._evaluate_xml_dict() to ensure
        consistency with the production code.

        Args:
            xml_dict: XML dictionary or list to process
            fub_name: Name of the FUB this belongs to
            uri_to_fub: Dict to populate with URI -> FUB mappings
            uri_dict: Dict tracking key -> URI list (for duplicate detection)
            prefix: Current key prefix for building hierarchical keys
        """
        if isinstance(xml_dict, list):
            for child in xml_dict:
                self._extract_uris_recursive(
                    child, fub_name, uri_to_fub, uri_dict, prefix
                )
        elif isinstance(xml_dict, dict):
            uri = xml_dict.get("@uri", "")
            name = xml_dict.get("@name", "")

            # Build key like EtaAPI does
            key = f"{prefix}_{name}" if prefix else name

            # Store URI if present
            if uri:
                # Track in uri_dict for duplicate detection
                if key not in uri_dict:
                    uri_dict[key] = []
                else:
                    self.stats["duplicates"] += 1
                    logging.debug(f"Duplicate URI: {uri} (key: {key})")

                uri_dict[key].append(uri)

                # Store first occurrence in uri_to_fub
                if uri not in uri_to_fub:
                    uri_to_fub[uri] = fub_name

            # Recurse into nested objects
            if "object" in xml_dict:
                self._extract_uris_recursive(
                    xml_dict["object"],
                    fub_name,
                    uri_to_fub,
                    uri_dict,
                    key,
                )

    async def fetch_endpoint_data(
        self, uri: str, fub: str, semaphore: asyncio.Semaphore
    ) -> Dict[str, str]:
        """Fetch both varinfo and var data for a URI.

        Args:
            uri: ETA URI like "/120/10111/0/0/10990"
            fub: FUB name like "WW"
            semaphore: Semaphore for rate limiting

        Returns:
            Dict with fixture entries:
            {
                "/user/varinfo//120/10111/0/0/10990": "<xml>...</xml>",
                "/user/var//120/10111/0/0/10990": "<xml>...</xml>"
            }
        """
        async with semaphore:
            result = {}

            # Fetch varinfo
            varinfo_key = f"/user/varinfo/{uri}"
            try:
                response = await self.api._get_request(varinfo_key)
                xml = await response.text()
                result[varinfo_key] = xml
                self.stats["varinfo_success"] += 1
                logging.debug(f"✓ Fetched varinfo: {uri}")
            except Exception as e:
                logging.warning(f"Failed to fetch varinfo for {uri}: {e}")
                self.stats["varinfo_failed"] += 1
                self.failed_endpoints.append((varinfo_key, str(e)))

            # Fetch var
            var_key = f"/user/var/{uri}"
            try:
                response = await self.api._get_request(var_key)
                xml = await response.text()
                result[var_key] = xml
                self.stats["var_success"] += 1
                logging.debug(f"✓ Fetched var: {uri}")
            except Exception as e:
                logging.warning(f"Failed to fetch var for {uri}: {e}")
                self.stats["var_failed"] += 1
                self.failed_endpoints.append((var_key, str(e)))

            return result

    async def fetch_all_endpoints(
        self, uri_to_fub: Dict[str, str]
    ) -> Dict[str, str]:
        """Fetch all endpoint data with rate limiting.

        Args:
            uri_to_fub: Dict mapping URI -> FUB name

        Returns:
            Dict with all fixture entries
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        total = len(uri_to_fub)

        logging.info(
            f"Fetching endpoint data for {total} URIs "
            f"({self.max_concurrent} concurrent)..."
        )

        # Create tasks for all URIs
        tasks = [
            self.fetch_endpoint_data(uri, fub, semaphore)
            for uri, fub in uri_to_fub.items()
        ]

        # Execute with progress tracking
        results = []
        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            result = await task
            results.append(result)

            # Log progress every 50 endpoints
            if i % 50 == 0 or i == total:
                percent = (i * 100) // total
                elapsed = time() - self.start_time
                rate = i / elapsed if elapsed > 0 else 0
                eta_seconds = (total - i) / rate if rate > 0 else 0
                eta_minutes = int(eta_seconds // 60)
                eta_seconds = int(eta_seconds % 60)

                logging.info(
                    f"Progress: {i}/{total} ({percent}%) - "
                    f"ETA: {eta_minutes}m {eta_seconds}s"
                )

        # Merge all results
        merged = {}
        for result in results:
            merged.update(result)

        return merged

    def merge_fixture_data(
        self, existing: Dict[str, str], new: Dict[str, str]
    ) -> Dict[str, str]:
        """Merge new data with existing fixture based on mode.

        Args:
            existing: Existing fixture data
            new: New data from API

        Returns:
            Merged fixture data
        """
        if self.mode == "refresh":
            # Replace all data
            self.stats["added"] = len(new)
            return new

        elif self.mode == "add-only":
            # Only add new entries
            result = existing.copy()
            for key, value in new.items():
                if key not in existing:
                    result[key] = value
                    self.stats["added"] += 1
                else:
                    self.stats["unchanged"] += 1
            return result

        else:  # mode == "update"
            # Update existing + add new
            result = existing.copy()
            for key, value in new.items():
                if key not in existing:
                    self.stats["added"] += 1
                elif existing[key] != value:
                    self.stats["updated"] += 1
                else:
                    self.stats["unchanged"] += 1
                result[key] = value
            return result

    def save_fixture(self, data: Dict[str, str], backup: bool = True):
        """Save fixture with automatic backup.

        Args:
            data: Fixture data to save
            backup: Whether to create a backup of existing file

        Raises:
            RuntimeError: If save fails
        """
        # Create backup if requested and file exists
        if backup and self.fixture_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.fixture_path.with_suffix(
                f".json.backup.{timestamp}"
            )
            logging.info(f"Creating backup: {backup_path.name}")
            try:
                backup_path.write_text(self.fixture_path.read_text())
            except Exception as e:
                logging.warning(f"Failed to create backup: {e}")

        # Write new fixture using atomic write (temp file + rename)
        temp_path = self.fixture_path.with_suffix(".json.tmp")
        try:
            logging.info(f"Saving fixture to {self.fixture_path}...")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Validate JSON is parseable
            with temp_path.open("r", encoding="utf-8") as f:
                json.load(f)

            # Atomic rename
            temp_path.replace(self.fixture_path)

            logging.info(
                f"✓ Fixture saved: {len(data)} entries "
                f"({self.stats['added']} added, "
                f"{self.stats['updated']} updated, "
                f"{self.stats['unchanged']} unchanged)"
            )
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"Failed to save fixture: {e}") from e

    def load_existing_fixture(self) -> Dict[str, str]:
        """Load existing fixture data.

        Returns:
            Existing fixture data, or empty dict if not found
        """
        if not self.fixture_path.exists():
            logging.info("No existing fixture found, starting fresh")
            return {}

        try:
            logging.info(f"Loading existing fixture from {self.fixture_path}...")
            with self.fixture_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            logging.info(f"✓ Loaded {len(data)} existing entries")
            return data
        except Exception as e:
            logging.warning(f"Failed to load existing fixture: {e}")
            return {}

    async def validate_connection(self) -> bool:
        """Test connection to ETA device.

        Returns:
            True if connection successful, False otherwise
        """
        logging.info(f"Connecting to ETA device at {self.host}:{self.port}...")
        try:
            if await self.api.does_endpoint_exists():
                logging.info("✓ API connection successful")
                return True
            else:
                logging.error("API endpoint check failed")
                return False
        except Exception as e:
            logging.error(f"Failed to connect to ETA device: {e}")
            return False

    def print_summary(self, duration: float):
        """Print execution summary.

        Args:
            duration: Execution duration in seconds
        """
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        total_endpoints = (
            self.stats["varinfo_success"]
            + self.stats["varinfo_failed"]
            + self.stats["var_success"]
            + self.stats["var_failed"]
        )
        total_success = (
            self.stats["varinfo_success"] + self.stats["var_success"]
        )
        total_failed = self.stats["varinfo_failed"] + self.stats["var_failed"]

        print("\n" + "=" * 60)
        print("=== Summary ===")
        print(f"Duration: {minutes}m {seconds}s")
        print(f"Endpoints: {total_endpoints} ({total_success} success, {total_failed} failed)")
        print(
            f"Changes: {self.stats['added']} added, "
            f"{self.stats['updated']} updated, "
            f"{self.stats['unchanged']} unchanged"
        )

        if self.failed_endpoints:
            print(f"\nFailed endpoints ({len(self.failed_endpoints)}):")
            for endpoint, error in self.failed_endpoints[:10]:  # Show first 10
                print(f"  - {endpoint}: {error}")
            if len(self.failed_endpoints) > 10:
                print(f"  ... and {len(self.failed_endpoints) - 10} more")

        print(f"\nFixture: {self.fixture_path}")
        print("\nNext steps:")
        print(f"  1. Review changes: git diff {self.fixture_path}")
        print("  2. Run tests: pytest tests/custom_components/eta_webservices/test_api.py")
        print(f"  3. Commit: git add {self.fixture_path}")
        print("=" * 60)

    async def run(self) -> int:
        """Run the fixture update process.

        Returns:
            Exit code (0 for success, 1 for failure)
        """
        self.start_time = time()

        try:
            # Validate connection
            if not await self.validate_connection():
                return 1

            # Fetch menu
            menu_xml = await self.fetch_menu()

            # Store menu in fixture data
            new_fixture_data = {"/user/menu": menu_xml}

            # Extract URIs
            uri_to_fub = self.extract_uris_from_menu(menu_xml)

            if not uri_to_fub:
                logging.error("No URIs found in menu!")
                return 1

            # Fetch all endpoints
            endpoint_data = await self.fetch_all_endpoints(uri_to_fub)
            new_fixture_data.update(endpoint_data)

            total_success = (
                self.stats["varinfo_success"] + self.stats["var_success"]
            )
            total_failed = self.stats["varinfo_failed"] + self.stats["var_failed"]
            logging.info(
                f"✓ Fetched {total_success + total_failed} endpoints "
                f"({total_success} success, {total_failed} failed)"
            )

            # Load existing fixture (if mode requires it)
            if self.mode in ["update", "add-only"]:
                existing_fixture = self.load_existing_fixture()
            else:
                existing_fixture = {}

            # Merge data
            merged_data = self.merge_fixture_data(
                existing_fixture, new_fixture_data
            )

            # Save fixture
            self.save_fixture(merged_data)

            # Validate
            logging.info("✓ JSON validation passed")

            # Print summary
            duration = time() - self.start_time
            self.print_summary(duration)

            return 0

        except Exception as e:
            logging.error(f"Fatal error: {e}", exc_info=True)
            return 1


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Update test fixture with fresh data from ETA API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Update fixture with data from ETA device at 192.168.0.25
  %(prog)s --host 192.168.0.25

  # Refresh all data (replace existing)
  %(prog)s --host 192.168.0.25 --mode refresh

  # Only add new endpoints
  %(prog)s --host 192.168.0.25 --mode add-only

  # Use custom port and fixture path
  %(prog)s --host 192.168.0.25 --port 8080 --fixture custom_fixture.json
        """,
    )

    parser.add_argument(
        "--host",
        required=True,
        help="ETA device hostname or IP address",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="ETA device port number (default: 8080)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("../fixtures/api_endpoint_data.json"),
        help="Path to fixture file (default: ../fixtures/api_endpoint_data.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["update", "refresh", "add-only"],
        default="update",
        help=(
            "Update mode: "
            "update=update existing + add new (default), "
            "refresh=replace all data, "
            "add-only=only add new entries"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum concurrent requests (default: 5)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Display configuration
    print("=" * 60)
    print("ETA Test Fixture Updater")
    print("=" * 60)
    print(f"Host: {args.host}:{args.port}")
    print(f"Fixture: {args.fixture}")
    print(f"Mode: {args.mode}")
    print(f"Max concurrent: {args.max_concurrent}")
    print(f"Timeout: {args.timeout}s")
    print("=" * 60)

    # Confirm unless --yes
    if not args.yes:
        response = input("\nProceed? [y/N]: ")
        if response.lower() not in ["y", "yes"]:
            print("Aborted.")
            return 1

    # Run the updater
    async def run_updater():
        async with FixtureUpdater(
            host=args.host,
            port=args.port,
            fixture_path=args.fixture,
            mode=args.mode,
            timeout=args.timeout,
            max_concurrent=args.max_concurrent,
        ) as updater:
            return await updater.run()

    return asyncio.run(run_updater())


if __name__ == "__main__":
    sys.exit(main())
