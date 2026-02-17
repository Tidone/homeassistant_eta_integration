#!/usr/bin/env python3
"""Find unparsed sensor nodes by comparing fixture files."""

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from analyze_sensors import SensorAnalyzer


def extract_varinfo_uris(endpoint_data: dict) -> dict:
    """Extract all varinfo URIs with their metadata.

    Args:
        endpoint_data: Contents of api_endpoint_data.json

    Returns:
        Dictionary mapping URI to metadata and raw XML
    """
    varinfo_data = {}

    for key, xml_str in endpoint_data.items():
        if "/varinfo/" not in key:
            continue

        # Extract URI from key: /user/varinfo//120/10111/... -> /120/10111/...
        uri = key.replace("/user/varinfo/", "").lstrip("/")
        if not uri.startswith("/"):
            uri = "/" + uri

        # Try to parse XML to get metadata
        try:
            root = ET.fromstring(xml_str)
            ns = {"eta": "http://www.eta.co.at/rest/v1"}

            # Check for error response
            error = root.find(".//eta:error", ns)
            if error is not None:
                varinfo_data[uri] = {
                    "name": None,
                    "fullName": None,
                    "isWritable": None,
                    "error": error.text,
                    "raw_xml": xml_str,
                }
                continue

            # Parse variable info
            var_elem = root.find(".//eta:variable", ns)
            if var_elem is not None:
                varinfo_data[uri] = {
                    "name": var_elem.get("name", ""),
                    "fullName": var_elem.get("fullName", ""),
                    "isWritable": var_elem.get("isWritable", "0"),
                    "unit": var_elem.get("unit", ""),
                    "error": None,
                    "raw_xml": xml_str,
                }
        except ET.ParseError:
            # If XML parsing fails, store as error
            varinfo_data[uri] = {
                "name": None,
                "fullName": None,
                "isWritable": None,
                "error": "XML Parse Error",
                "raw_xml": xml_str,
            }

    return varinfo_data


def extract_var_uris(endpoint_data: dict) -> dict:
    """Extract all var URIs with their value data.

    Args:
        endpoint_data: Contents of api_endpoint_data.json

    Returns:
        Dictionary mapping URI to value data and raw XML
    """
    var_data = {}

    for key, xml_str in endpoint_data.items():
        if "/user/var/" not in key:
            continue

        # Extract URI from key: /user/var//120/10111/... -> /120/10111/...
        uri = key.replace("/user/var/", "").lstrip("/")
        if not uri.startswith("/"):
            uri = "/" + uri

        # Parse XML to extract value data
        try:
            root = ET.fromstring(xml_str)
            ns = {"eta": "http://www.eta.co.at/rest/v1"}

            # Check for error response
            error = root.find(".//eta:error", ns)
            if error is not None:
                var_data[uri] = {
                    "strValue": None,
                    "value": None,
                    "unit": None,
                    "error": error.text,
                    "raw_xml": xml_str,
                }
                continue

            # Extract value data
            value_elem = root.find(".//eta:value", ns)
            if value_elem is not None:
                var_data[uri] = {
                    "strValue": value_elem.get("strValue", ""),
                    "value": value_elem.text or "",
                    "unit": value_elem.get("unit", ""),
                    "error": None,
                    "raw_xml": xml_str,
                }
            else:
                var_data[uri] = {
                    "strValue": None,
                    "value": None,
                    "unit": None,
                    "error": "No value element found",
                    "raw_xml": xml_str,
                }
        except ET.ParseError:
            var_data[uri] = {
                "strValue": None,
                "value": None,
                "unit": None,
                "error": "XML Parse Error",
                "raw_xml": xml_str,
            }

    return var_data


def extract_duplicate_info(endpoint_data: dict) -> dict:
    """Extract duplicate information from menu XML.

    Args:
        endpoint_data: Contents of api_endpoint_data.json

    Returns:
        Dictionary mapping URI to list of all URIs sharing the same key
    """
    # Get menu XML from endpoint data
    menu_xml = endpoint_data.get("/user/menu")
    if not menu_xml:
        print("WARNING: /user/menu not found in endpoint data", file=sys.stderr)
        return {}

    # Use SensorAnalyzer to find duplicates
    analyzer = SensorAnalyzer()

    # Need to parse menu XML and analyze it
    # The analyzer expects parsed XML dict, not raw XML string
    import xmltodict

    try:
        data = xmltodict.parse(menu_xml)
        raw_dict = data["eta"]["menu"]["fub"]
    except Exception as e:
        print(f"WARNING: Failed to parse menu XML: {e}", file=sys.stderr)
        return {}

    # Analyze for duplicates
    uri_dict = {}
    analyzer._evaluate_xml_dict(raw_dict, uri_dict)

    # Create reverse mapping: uri -> all uris for that key
    uri_to_duplicates = {}
    for key, uris in analyzer._all_keys_with_uris.items():
        if len(uris) > 1:  # Only if there are duplicates
            # Normalize URIs to match format in unparsed.csv
            normalized_uris = ["/" + uri.lstrip("/") for uri in uris]
            for uri in normalized_uris:
                # Store all URIs including itself
                uri_to_duplicates[uri] = normalized_uris

    return uri_to_duplicates


def extract_assigned_urls(assignment_data: dict) -> set:
    """Extract all assigned URLs from reference values file.

    Args:
        assignment_data: Contents of api_assignment_reference_values_v12.json

    Returns:
        Set of assigned URLs
    """
    urls = set()

    # Note: writable_dict is excluded because it only contains duplicates
    # of nodes already present in float_dict, switches_dict, or text_dict
    for dict_name in ["float_dict", "switches_dict", "text_dict"]:
        if dict_name in assignment_data:
            for entry in assignment_data[dict_name].values():
                if "url" in entry:
                    urls.add(entry["url"])

    return urls


def create_parsed_info(metadata: dict) -> str:
    """Create the parsed_info column value.

    Args:
        metadata: Varinfo metadata dict

    Returns:
        Formatted string like "name | fullName | writable=X"
    """
    if metadata["error"]:
        return f"ERROR: {metadata['error']}"

    name = metadata.get("name", "")
    full_name = metadata.get("fullName", "")
    is_writable = metadata.get("isWritable", "0")

    return f"{name} | {full_name} | writable={is_writable}"


def write_unparsed_csv(unparsed_data: dict, output_path: Path, uri_to_duplicates: dict, assigned_urls: set, var_uris: dict):
    """Write unparsed nodes to CSV file with var data columns.

    Args:
        unparsed_data: Dictionary of unparsed URIs with combined varinfo and var data
        output_path: Path to output CSV file
        uri_to_duplicates: Mapping of URI to all duplicate URIs
        assigned_urls: Set of URIs already assigned in the fixture
        var_uris: Dictionary mapping URIs to var endpoint data
    """
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        # Update header with new columns
        writer.writerow([
            "node",
            "parsed_info",
            "duplicates",
            "correctly_enumerated_duplicate",
            "strValue",
            "value",
            "unit",
            "correctly_enumerated_unit",
            "correctly_enumerated_strValue",
            "correctly_enumerated_value",
            "raw_var_xml",
            "raw_varinfo_xml",
            "correctly_enumerated_raw_var_xml"
        ])

        # Sort URIs for consistent output
        for uri in sorted(unparsed_data.keys()):
            combined_data = unparsed_data[uri]
            varinfo_metadata = combined_data["varinfo"]
            var_data = combined_data.get("var", {})

            # Existing columns
            parsed_info = create_parsed_info(varinfo_metadata)
            raw_varinfo_xml = varinfo_metadata["raw_xml"]

            # Duplicates column
            duplicate_uris = uri_to_duplicates.get(uri, [])
            if duplicate_uris:
                # Filter out the current URI to show only the other duplicates
                other_duplicates = [dup for dup in duplicate_uris if dup != uri]
                duplicates_str = ",".join(other_duplicates)

                # Find which duplicates are correctly enumerated (assigned)
                correctly_enumerated = [dup for dup in other_duplicates if dup in assigned_urls]
                correctly_enumerated_str = ",".join(correctly_enumerated)

                # Get var data from first correctly enumerated duplicate
                if correctly_enumerated:
                    first_enumerated_uri = correctly_enumerated[0]
                    enumerated_var_data = var_uris.get(first_enumerated_uri, {})

                    correctly_enumerated_unit = enumerated_var_data.get("unit") or ""
                    correctly_enumerated_strValue = enumerated_var_data.get("strValue") or ""
                    correctly_enumerated_value = enumerated_var_data.get("value") or ""

                    # Handle var errors for enumerated duplicate
                    if enumerated_var_data.get("error"):
                        correctly_enumerated_raw_var_xml = f"ERROR: {enumerated_var_data['error']}"
                    else:
                        correctly_enumerated_raw_var_xml = enumerated_var_data.get("raw_xml", "")
                else:
                    correctly_enumerated_unit = ""
                    correctly_enumerated_strValue = ""
                    correctly_enumerated_value = ""
                    correctly_enumerated_raw_var_xml = ""
            else:
                duplicates_str = ""
                correctly_enumerated_str = ""
                correctly_enumerated_unit = ""
                correctly_enumerated_strValue = ""
                correctly_enumerated_value = ""
                correctly_enumerated_raw_var_xml = ""

            # New var columns
            str_value = var_data.get("strValue") or ""
            value = var_data.get("value") or ""
            unit = var_data.get("unit") or ""

            # Handle var errors
            if var_data.get("error"):
                raw_var_xml = f"ERROR: {var_data['error']}"
            else:
                raw_var_xml = var_data.get("raw_xml", "")

            writer.writerow([
                uri,
                parsed_info,
                duplicates_str,
                correctly_enumerated_str,
                str_value,
                value,
                unit,
                correctly_enumerated_unit,
                correctly_enumerated_strValue,
                correctly_enumerated_value,
                raw_var_xml,
                raw_varinfo_xml,
                correctly_enumerated_raw_var_xml
            ])


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Find unparsed sensor nodes by comparing fixture files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script compares varinfo endpoints in api_endpoint_data.json with
assigned sensors in api_assignment_reference_values_v12.json and generates
a CSV file of unparsed nodes.

Examples:
  # Generate unparsed.csv in parent directory
  %(prog)s

  # Specify custom output path
  %(prog)s --output custom_unparsed.csv

  # Use custom fixture paths
  %(prog)s --endpoint-data custom_endpoint.json --reference-values custom_ref.json
        """,
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
        "--output",
        type=Path,
        default=Path("../unparsed.csv"),
        help="Output CSV path (default: ../unparsed.csv)",
    )

    args = parser.parse_args()

    try:
        # Load endpoint data
        print(f"Loading endpoint data from {args.endpoint_data}...")
        with args.endpoint_data.open("r", encoding="utf-8") as f:
            endpoint_data = json.load(f)

        # Load assignment data
        print(f"Loading assignment data from {args.reference_values}...")
        with args.reference_values.open("r", encoding="utf-8") as f:
            assignment_data = json.load(f)

        # Extract duplicate information
        print("Analyzing duplicates from menu structure...")
        uri_to_duplicates = extract_duplicate_info(endpoint_data)
        if uri_to_duplicates:
            print(f"  Found {len(uri_to_duplicates)} URIs that are duplicates")

        # Extract varinfo URIs
        print("Extracting varinfo endpoints...")
        varinfo_uris = extract_varinfo_uris(endpoint_data)
        print(f"  Found {len(varinfo_uris)} varinfo endpoints")

        # Extract var endpoints
        print("Extracting var endpoints...")
        var_uris = extract_var_uris(endpoint_data)
        print(f"  Found {len(var_uris)} var endpoints")

        # Extract assigned URLs
        print("Extracting assigned URLs...")
        assigned_urls = extract_assigned_urls(assignment_data)
        print(f"  Found {len(assigned_urls)} assigned URLs")

        # Find unparsed and combine varinfo + var data
        print("Finding unparsed nodes...")
        unparsed_uri_set = set(varinfo_uris.keys()) - assigned_urls
        unparsed_data = {
            uri: {
                "varinfo": varinfo_uris[uri],
                "var": var_uris.get(uri, {
                    "strValue": None,
                    "value": None,
                    "unit": None,
                    "error": "Missing from fixture",
                    "raw_xml": ""
                })
            }
            for uri in unparsed_uri_set
        }
        print(f"  Found {len(unparsed_data)} unparsed nodes")

        # Count duplicates in unparsed
        unparsed_duplicates = sum(
            1 for uri in unparsed_data.keys() if uri in uri_to_duplicates
        )
        if unparsed_duplicates:
            print(f"  {unparsed_duplicates} of these are duplicates")

        # Write CSV with duplicates column
        print(f"Writing results to {args.output}...")
        write_unparsed_csv(unparsed_data, args.output, uri_to_duplicates, assigned_urls, var_uris)
        print(f"✓ Done! Wrote {len(unparsed_data)} unparsed nodes to {args.output}")

        # Summary statistics
        error_count = sum(1 for data in unparsed_data.values() if data["varinfo"]["error"])
        var_error_count = sum(1 for data in unparsed_data.values() if data["var"].get("error"))
        valid_count = len(unparsed_data) - error_count
        print(f"\nSummary:")
        print(f"  Valid unparsed nodes: {valid_count}")
        print(f"  Varinfo error responses: {error_count}")
        print(f"  Var error responses: {var_error_count}")
        print(f"  Duplicate nodes: {unparsed_duplicates}")

        return 0

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
