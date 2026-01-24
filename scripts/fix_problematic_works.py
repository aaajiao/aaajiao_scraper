#!/usr/bin/env python3
"""
Fix problematic works in aaajiao_works.json.

This script identifies and fixes the following issues:
1. Type "null" - should be empty or a valid type
2. Duplicate titles (title / title patterns)
3. Materials containing descriptions or credits
4. Missing fields

Usage:
    python scripts/fix_problematic_works.py [--dry-run]
"""

import json
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def fix_type_null(work: dict) -> bool:
    """Fix type field if it's literal 'null'."""
    if work.get('type', '').lower().strip() == 'null':
        work['type'] = ''
        return True
    return False


def fix_duplicate_title(work: dict) -> bool:
    """Fix duplicate title patterns like 'A / A' or 'A / B / B'."""
    changed = False
    title = work.get('title', '')
    title_cn = work.get('title_cn', '')

    # Skip if no slash in title
    if '/' not in title:
        return False

    parts = [p.strip() for p in title.split('/')]
    if len(parts) < 2:
        return False

    # Check which parts have Chinese characters
    has_chinese = [any('\u4e00' <= c <= '\u9fff' for c in p) for p in parts]

    # Case 1: "English / Chinese" bilingual format
    if not has_chinese[0] and has_chinese[-1]:
        new_title = parts[0]
        new_cn = parts[-1]

        # Check if title_cn is wrongly set to the full bilingual title
        if title_cn == title:
            work['title'] = new_title
            work['title_cn'] = new_cn
            return True

        # If title_cn is already set to the Chinese part, we're good
        if title_cn == new_cn:
            if title != new_title:
                work['title'] = new_title
                return True
            return False

        # If title_cn is empty, update both
        if not title_cn:
            work['title'] = new_title
            work['title_cn'] = new_cn
            return True

        # title_cn exists but is different
        if new_cn in title_cn or title_cn in new_cn:
            work['title'] = new_title
            work['title_cn'] = new_cn
            return True

    # Case 2: Both parts are identical (skip - might be intentional)
    if len(parts) == 2 and parts[0] == parts[1]:
        return False

    # Case 3: English-only with repetition
    if not has_chinese[0] and not has_chinese[-1] and len(parts) == 2:
        if parts[0].lower() in parts[1].lower() and parts[0] != parts[1]:
            work['title'] = parts[0]
            if any('\u4e00' <= c <= '\u9fff' for c in parts[1]):
                work['title_cn'] = parts[1]
            changed = True

    # Fix duplicate title_cn
    if title_cn and '/' in title_cn:
        cn_parts = [p.strip() for p in title_cn.split('/')]
        if len(cn_parts) >= 2 and cn_parts[0] == cn_parts[-1]:
            work['title_cn'] = cn_parts[0]
            changed = True

    return changed


def is_description_or_credits(text: str) -> bool:
    """Check if text looks like a description or credits, not materials."""
    if not text:
        return False

    text_lower = text.lower()

    # Credits indicators
    credits_indicators = [
        'collaboration', 'made possible', 'curated by', 'this piece was done',
        'team:', 'concept:', 'sound:', 'photo:', 'director:', 'venue',
        'copyright', 'born in', 'work involves'
    ]
    if any(ci in text_lower for ci in credits_indicators):
        return True

    # Description indicators (sentence-like)
    desc_indicators = [' is ', ' are ', ' was ', ' were ', ' build ', ' builds ',
                       ' through ', 'invit', ' explore', ' examine', ' the ']
    indicator_count = sum(1 for ind in desc_indicators if ind in text_lower)
    if indicator_count >= 2:
        return True

    # Starts with quote (Chinese or English, various quote styles)
    # Using explicit Unicode code points for clarity
    quote_chars = [
        '"',      # U+0022 basic quote
        '\u201c', # Left double quotation mark
        '\u201d', # Right double quotation mark
        '\u300c', # Left corner bracket
        '\u300d', # Right corner bracket
        '\u300e', # Left white corner bracket
        "'",      # Basic single quote
        '\u2018', # Left single quotation mark
        '\u300a', # Left double angle bracket
    ]
    if any(text.startswith(q) for q in quote_chars):
        return True

    # Too long for materials
    if len(text) > 150:
        return True

    # Check for copyright symbol
    if '\u00a9' in text:  # (c) symbol
        return True

    # Chinese description indicators
    chinese_desc_indicators = ['生于', '工作涉及', '展览', '概念', '探索', '邀请', '创作']
    if any(ind in text for ind in chinese_desc_indicators):
        # Check if it's mostly Chinese (likely a description paragraph)
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if chinese_chars > 20:
            return True

    return False


def is_title_as_materials(text: str, title: str, title_cn: str) -> bool:
    """Check if materials field contains the title (incorrect)."""
    if not text:
        return False

    text_lower = text.lower().strip()
    title_lower = title.lower().strip() if title else ''
    title_cn_strip = title_cn.strip() if title_cn else ''

    # Check if materials equals title
    if title_lower and text_lower == title_lower:
        return True

    # Check if materials is "Title / Chinese" format
    if '/' in text:
        parts = [p.strip() for p in text.split('/')]
        if len(parts) == 2:
            if parts[0].lower() == title_lower:
                return True
            if title_cn_strip and parts[1] == title_cn_strip:
                return True

    return False


def fix_materials(work: dict) -> bool:
    """Fix materials field if it contains description or credits."""
    materials = work.get('materials', '')
    title = work.get('title', '')
    title_cn = work.get('title_cn', '')

    if not materials:
        return False

    # Check if materials is actually the title
    if is_title_as_materials(materials, title, title_cn):
        work['materials'] = ''
        return True

    # Check if materials is description or credits
    if is_description_or_credits(materials):
        # Move to credits if appropriate
        credits = work.get('credits', '')
        if not credits and any(c in materials.lower() for c in ['team:', 'concept:', 'collaboration']):
            work['credits'] = materials
        work['materials'] = ''
        return True

    return False


def fix_duration_as_date(work: dict) -> bool:
    """Fix duration field if it contains a date range instead of duration."""
    duration = work.get('duration', '')
    if duration:
        # Check if it's a date range with month names
        if re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', duration, re.IGNORECASE):
            work['duration'] = ''
            return True
        # Check if it's a date format like "21.02.2014 - 15.03.2014"
        if re.match(r'\d{1,2}\.\d{2}\.\d{4}\s*[-\u2013]\s*\d{1,2}\.\d{2}\.\d{4}', duration):
            work['duration'] = ''
            return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix problematic works in aaajiao_works.json')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without saving')
    args = parser.parse_args()

    json_path = PROJECT_ROOT / 'aaajiao_works.json'

    if not json_path.exists():
        print(f"Error: {json_path} not found")
        return 1

    with open(json_path, 'r', encoding='utf-8') as f:
        works = json.load(f)

    print(f"Loaded {len(works)} works from {json_path}")

    fixes = {
        'type_null': [],
        'duplicate_title': [],
        'materials': [],
        'duration': [],
    }

    for work in works:
        title = work.get('title', 'Unknown')

        if fix_type_null(work):
            fixes['type_null'].append(title)

        if fix_duplicate_title(work):
            fixes['duplicate_title'].append(title)

        if fix_materials(work):
            fixes['materials'].append(title)

        if fix_duration_as_date(work):
            fixes['duration'].append(title)

    # Print summary
    print("\n=== Fix Summary ===")
    for fix_type, affected in fixes.items():
        if affected:
            print(f"\n{fix_type} ({len(affected)} works):")
            for title in affected:
                print(f"  - {title}")

    total_fixes = sum(len(v) for v in fixes.values())
    print(f"\nTotal: {total_fixes} fixes applied")

    if args.dry_run:
        print("\n[DRY RUN] No changes saved")
    else:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(works, f, ensure_ascii=False, indent=2)
        print(f"\nChanges saved to {json_path}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
