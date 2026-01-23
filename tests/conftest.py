"""Pytest configuration and shared fixtures."""

import json
from pathlib import Path
import pytest


@pytest.fixture
def fixture_data_dir():
    """Return path to fixture data directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture(fixture_data_dir):
    """Load fixture data from JSON files."""
    def _load(filename: str) -> dict:
        """Load and parse JSON fixture file."""
        fixture_path = fixture_data_dir / filename
        with open(fixture_path, "r") as f:
            return json.load(f)
    return _load
