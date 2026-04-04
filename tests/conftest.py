"""Pytest configuration and shared fixtures."""

import json
from pathlib import Path
import pytest


@pytest.fixture
def fixture_data_dir():
    """Return path to fixture data directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture(request, fixture_data_dir):
    """Load fixture data from JSON files, optionally from a subdirectory.

    When used with indirect parametrization, ``request.param`` is treated as a
    subdirectory relative to the base fixtures directory (e.g. "additional_data").
    When used directly (no indirect param), files are loaded from the base directory.
    """
    subdir = getattr(request, "param", "")
    def _load(filename: str) -> dict:
        """Load and parse JSON fixture file."""
        fixture_path = fixture_data_dir / subdir / filename
        with open(fixture_path, "r") as f:
            return json.load(f)
    return _load
