#!/usr/bin/env python3
"""
Clean materials and credits fields in aaajiao_works.json.

This script:
1. Moves credits/collaborator info from 'materials' to new 'credits' field
2. Cleans 'type' field by removing credits and long descriptions
3. Ensures proper separation of materials, type, and credits

Usage:
    # Preview changes (dry-run)
    python scripts/clean_materials_credits.py --dry-run

    # Apply changes
    python scripts/clean_materials_credits.py

    # Output to different file
    python scripts/clean_materials_credits.py -o cleaned_works.json
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


# === Credits detection patterns ===
CREDITS_PATTERNS = [
    r'^Photo(?:\s+by)?:\s*.+',
    r'^concept:\s*.+',
    r'^sound:\s*.+',
    r'^software:\s*.+',
    r'^hardware:\s*.+',
    r'^computer graphics:\s*.+',
    r'^video editing:\s*.+',
    r'^technical support:\s*.+',
    r'^architecture:\s*.+',
    r'^interactive:\s*.+',
    r'^dancer:\s*.+',
    r'^actress:\s*.+',
    r'^curated by\s+.+',
    r'^Copyright\s+(?:of|by)\s+.+',
    r'.+:\s*[a-zA-Z]+(?:,\s*[a-zA-Z]+)*(?:;\s*[a-zA-Z\s]+:\s*[a-zA-Z]+(?:,\s*[a-zA-Z]+)*)+',  # role: name; role: name
    r'made possible (?:with|by)\s+.+',
    r'collaboration (?:of|with)\s+.+',
    r'Web software:\s*.+',
]


def is_credits(text: str) -> bool:
    """Check if text looks like credits/collaborator info."""
    if not text:
        return False
    text_lower = text.lower().strip()
    for pattern in CREDITS_PATTERNS:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def is_long_description(text: str) -> bool:
    """Check if text is too long to be a type field (likely a description)."""
    return len(text) > 100


def is_url(text: str) -> bool:
    """Check if text is a URL."""
    return text.startswith('http') if text else False


def clean_work(work: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Clean a single work's materials, type, and credits fields.

    Returns:
        Tuple of (cleaned_work, list_of_changes)
    """
    changes = []

    old_materials = work.get('materials', '')
    old_type = work.get('type', '')
    old_credits = work.get('credits', '')

    new_credits = old_credits
    new_materials = old_materials
    new_type = old_type

    # 1. If materials looks like credits, move to credits field
    if old_materials and is_credits(old_materials):
        if not old_credits:
            new_credits = old_materials
            changes.append(f"materials→credits: '{old_materials[:50]}...'")
        new_materials = ''

    # 2. If type looks like credits, move to credits field
    if old_type and is_credits(old_type):
        if not new_credits:
            new_credits = old_type
            changes.append(f"type→credits: '{old_type[:50]}...'")
        new_type = ''

    # 3. If type is URL, clear it
    if old_type and is_url(old_type):
        changes.append(f"type cleared (URL): '{old_type[:50]}...'")
        new_type = ''

    # 4. If type is too long (description), clear it
    if old_type and is_long_description(old_type):
        changes.append(f"type cleared (too long): '{old_type[:50]}...'")
        new_type = ''

    # 5. If materials contains dimension info, it should stay in materials but check for mixed content
    # E.g., "Dimension variable / 尺寸可变" is actually size, not materials
    if new_materials and re.match(r'^Dimension', new_materials, re.IGNORECASE):
        # This is actually size info, move if size is empty
        if not work.get('size'):
            work['size'] = new_materials
            changes.append(f"materials→size: '{new_materials}'")
        new_materials = ''

    # Update work
    work['materials'] = new_materials
    work['type'] = new_type
    work['credits'] = new_credits

    return work, changes


def process_works(works: List[Dict[str, Any]], dry_run: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Process all works and return cleaned data with statistics.

    Returns:
        Tuple of (cleaned_works, statistics_dict)
    """
    stats = {
        'total': len(works),
        'modified': 0,
        'materials_to_credits': 0,
        'type_to_credits': 0,
        'type_cleared': 0,
        'materials_to_size': 0,
        'credits_added': 0,
    }

    all_changes = []
    cleaned_works = []

    for work in works:
        title = work.get('title', 'Unknown')
        work_copy = work.copy()

        cleaned, changes = clean_work(work_copy)
        cleaned_works.append(cleaned)

        if changes:
            stats['modified'] += 1
            for change in changes:
                all_changes.append(f"[{title}] {change}")
                if 'materials→credits' in change:
                    stats['materials_to_credits'] += 1
                    stats['credits_added'] += 1
                elif 'type→credits' in change:
                    stats['type_to_credits'] += 1
                    stats['credits_added'] += 1
                elif 'type cleared' in change:
                    stats['type_cleared'] += 1
                elif 'materials→size' in change:
                    stats['materials_to_size'] += 1

    if dry_run:
        print("\n=== DRY RUN - No changes will be made ===\n")

    print(f"Total works: {stats['total']}")
    print(f"Modified: {stats['modified']}")
    print(f"  - materials → credits: {stats['materials_to_credits']}")
    print(f"  - type → credits: {stats['type_to_credits']}")
    print(f"  - type cleared (invalid): {stats['type_cleared']}")
    print(f"  - materials → size: {stats['materials_to_size']}")
    print(f"  - credits field added: {stats['credits_added']}")

    if all_changes:
        print("\n=== Changes ===")
        for change in all_changes:
            print(f"  {change}")

    return cleaned_works, stats


def main():
    parser = argparse.ArgumentParser(
        description='Clean materials and credits fields in aaajiao_works.json'
    )
    parser.add_argument(
        'input_file',
        nargs='?',
        default='aaajiao_works.json',
        help='Input JSON file (default: aaajiao_works.json)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output file (default: overwrites input file)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )

    args = parser.parse_args()

    # Resolve paths
    input_path = Path(args.input_file)
    if not input_path.is_absolute():
        # Try relative to script directory first, then cwd
        script_dir = Path(__file__).parent.parent
        if (script_dir / input_path).exists():
            input_path = script_dir / input_path

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_path

    # Load data
    print(f"Loading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        works = json.load(f)

    # Process
    cleaned_works, stats = process_works(works, dry_run=args.dry_run)

    # Save (unless dry-run)
    if not args.dry_run:
        print(f"\nSaving to: {output_path}")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(cleaned_works, f, ensure_ascii=False, indent=2)
        print("Done!")
    else:
        print("\n(Dry-run mode - no files modified)")


if __name__ == '__main__':
    main()
