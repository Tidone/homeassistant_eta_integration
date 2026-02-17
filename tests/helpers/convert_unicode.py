#!/usr/bin/env python3
"""Convert unicode escape sequences to actual unicode characters in JSON files."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def create_backup(path: Path) -> Path:
    """Create timestamped backup of file.

    Args:
        path: Path to file to backup

    Returns:
        Path to backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f"{path.suffix}.backup.{timestamp}")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def convert_unicode_escapes(input_path: Path, create_backup_flag: bool = True) -> None:
    """Convert unicode escape sequences to actual characters.

    Args:
        input_path: Path to JSON file to convert
        create_backup_flag: Whether to create backup before conversion
    """
    print(f"Processing: {input_path}")

    # Load JSON (this reads escape sequences as-is)
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Create backup if requested
    if create_backup_flag:
        backup_path = create_backup(input_path)
        print(f"  Created backup: {backup_path}")

    # Save with ensure_ascii=False to write actual unicode characters
    with input_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  ✓ Converted unicode escapes to characters")


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Convert unicode escape sequences to actual unicode characters in JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert a single file
  %(prog)s ../fixtures/api_endpoint_data.json

  # Convert multiple files
  %(prog)s ../fixtures/*.json

  # Convert without creating backup
  %(prog)s --no-backup ../fixtures/api_endpoint_data.json
        """,
    )

    parser.add_argument("files", type=Path, nargs="+", help="JSON file(s) to convert")

    parser.add_argument(
        "--no-backup", action="store_true", help="Don't create backup files"
    )

    args = parser.parse_args()

    # Process each file
    errors = []
    for file_path in args.files:
        try:
            if not file_path.exists():
                print(f"ERROR: File not found: {file_path}", file=sys.stderr)
                errors.append(file_path)
                continue

            if not file_path.suffix.lower() == ".json":
                print(f"WARNING: Skipping non-JSON file: {file_path}")
                continue

            convert_unicode_escapes(file_path, create_backup_flag=not args.no_backup)

        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in {file_path}: {e}", file=sys.stderr)
            errors.append(file_path)
        except Exception as e:
            print(f"ERROR processing {file_path}: {e}", file=sys.stderr)
            errors.append(file_path)

    # Summary
    print(
        f"\nProcessed {len(args.files) - len(errors)}/{len(args.files)} files successfully"
    )

    if errors:
        print(f"Failed to process {len(errors)} file(s)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
