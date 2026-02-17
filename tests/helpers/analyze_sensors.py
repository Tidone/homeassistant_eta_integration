#!/usr/bin/env python3
"""Analyze ETA sensors from a local XML file."""

import argparse
import sys
import xmltodict


class SensorAnalyzer:
    """Analyze ETA sensor data from XML."""

    def __init__(self):
        """Initialize the analyzer."""
        self._num_duplicates = 0
        self._all_keys_with_uris = {}  # Maps key -> list of all URIs

    def _evaluate_xml_dict(self, xml_dict, uri_dict, prefix=""):
        """Recursively evaluate XML dict and count duplicates.

        This is the same logic as EtaAPI._evaluate_xml_dict().
        """
        if isinstance(xml_dict, list):
            for child in xml_dict:
                self._evaluate_xml_dict(child, uri_dict, prefix)
        elif "object" in xml_dict:
            child = xml_dict["object"]
            new_prefix = f"{prefix}_{xml_dict['@name']}"
            # Track all URIs for this key
            if new_prefix not in self._all_keys_with_uris:
                self._all_keys_with_uris[new_prefix] = []
            self._all_keys_with_uris[new_prefix].append(xml_dict["@uri"])
            # add parent to uri_dict and evaluate childs then
            if new_prefix in uri_dict:
                self._num_duplicates += 1
            uri_dict[new_prefix] = xml_dict["@uri"]
            self._evaluate_xml_dict(child, uri_dict, new_prefix)
        else:
            key = f"{prefix}_{xml_dict['@name']}"
            # Track all URIs for this key
            if key not in self._all_keys_with_uris:
                self._all_keys_with_uris[key] = []
            self._all_keys_with_uris[key].append(xml_dict["@uri"])
            if key in uri_dict:
                self._num_duplicates += 1
            uri_dict[key] = xml_dict["@uri"]

    def analyze_xml_file(self, xml_file_path):
        """Analyze an XML file containing ETA sensor data.

        Args:
            xml_file_path: Path to the XML file to analyze

        Returns:
            tuple: (uri_dict, num_duplicates, duplicate_keys)
        """
        # Read and parse XML file
        try:
            with open(xml_file_path, 'r', encoding='utf-8') as f:
                xml_content = f.read()
        except FileNotFoundError:
            print(f"Error: File '{xml_file_path}' not found.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)

        # Parse XML
        try:
            data = xmltodict.parse(xml_content)
            # Extract the fub data structure like _get_raw_sensor_dict does
            raw_dict = data["eta"]["menu"]["fub"]
        except Exception as e:
            print(f"Error parsing XML: {e}", file=sys.stderr)
            sys.exit(1)

        # Process the data
        uri_dict = {}
        self._evaluate_xml_dict(raw_dict, uri_dict)

        # Filter to only keys with duplicates (more than 1 URI)
        duplicate_keys = {
            key: uris for key, uris in self._all_keys_with_uris.items()
            if len(uris) > 1
        }

        return uri_dict, self._num_duplicates, duplicate_keys


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze ETA sensors from a local XML file'
    )
    parser.add_argument(
        'xml_file',
        help='Path to the XML file containing ETA sensor data'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed output including all sensor URIs'
    )

    args = parser.parse_args()

    # Analyze the file
    analyzer = SensorAnalyzer()
    uri_dict, num_duplicates, duplicate_keys = analyzer.analyze_xml_file(args.xml_file)

    # Print results
    print(f"Total sensors found: {len(uri_dict)}")
    print(f"Number of duplicates: {num_duplicates}")

    if num_duplicates > 0:
        print(f"\nUnique keys with duplicates: {len(duplicate_keys)}")
        print("\nDuplicate keys:")
        for key, uris in sorted(duplicate_keys.items()):
            print(f"  Key: {key} ({len(uris)} occurrences)")
            for i, uri in enumerate(uris, 1):
                print(f"    URI {i}: {uri}")
            print()

    if args.verbose:
        print("Sensor URIs:")
        for key, uri in sorted(uri_dict.items()):
            print(f"  {key}: {uri}")


if __name__ == "__main__":
    main()
