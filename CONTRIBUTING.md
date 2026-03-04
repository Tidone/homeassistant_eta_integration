# Contributing

## Scope

This repository contains the Home Assistant integration for ETA heating systems. Contributions should prioritize correctness, maintainability, and predictable behavior against real ETA API responses.

## Before opening an issue

- Check the README for setup notes and known limitations.
- Use the issue templates.
- Include the relevant Home Assistant version, integration version, ETA API version, and a minimal log excerpt.

## Local development

1. Create and activate a virtual environment.
2. Install test dependencies:
   `pip install -r requirements_test.txt`
3. Run the test suite from the repository root:
   `pytest tests/ -v`

## Pull requests

- Keep PRs focused. Separate refactors, behavior changes, and documentation updates when practical.
- Update translations and README text if the user-facing behavior changes.
- Add or update tests if parser, coordinator, config flow, or API behavior changes.
- Avoid committing private ETA hostnames, credentials, or full Home Assistant logs.

## Fixtures and helper scripts

The `tests/fixtures/` files are recorded ETA API responses used by the test suite.

- `tests/helpers/update_endpoint_data_fixture.py` refreshes API response fixtures from a live ETA device.
- `tests/helpers/update_sensor_reference_v11.py` and `tests/helpers/update_sensor_reference_v12.py` rebuild the expected sensor-assignment reference files from fixture data.

If you update fixtures, describe why in the PR so reviewers know whether the change is expected parser behavior or only refreshed source data.
