#!/usr/bin/env python3
"""
清洗现有数据，将尺寸和时长信息从 materials 字段分离到独立字段。

Usage:
    python scripts/clean_size_materials.py aaajiao_works.json --dry-run
    python scripts/clean_size_materials.py aaajiao_works.json -o cleaned.json
"""
import json
import re
import sys
import argparse
from typing import Tuple


def clean_materials(materials: str) -> Tuple[str, str, str]:
    """
    将 materials 字段中的尺寸和时长信息分离出来。
    
    Args:
        materials: 原始 materials 字符串
        
    Returns:
        (cleaned_materials, size, duration)
    """
    if not materials:
        return "", "", ""
    
    size = ""
    duration = ""
    cleaned = materials
    
    # 1. 先检查是否整个字段就是尺寸信息
    pure_size_patterns = [
        r'^Dimension[s]?\s+variable\s*/?\s*尺寸可变$',
        r'^Dimension[s]?\s+variable$',
        r'^尺寸可变$',
        r'^Variable\s+dimensions?$',
    ]
    for pattern in pure_size_patterns:
        if re.match(pattern, cleaned.strip(), re.IGNORECASE):
            return "", cleaned.strip(), ""
    
    # 2. 提取时长 (先处理，避免数字被误认为尺寸)
    duration_patterns = [
        (r"video\s+(\d+['′'\"]+)", r"video\s+\d+['′'\"]+"),  # video 43''
        (r"(\d+['′]\s*\d+['′'\"]+)", r"\d+['′]\s*\d+['′'\"]+"),  # 4'30'' 或 2′47′'
        (r"(\d+:\d+(?::\d+)?)", r"\d+:\d+(?::\d+)?"),     # 4:30 或 1:23:45
        (r"(\d+\s*min(?:utes?)?)", r"\d+\s*min(?:utes?)?"),  # 10 min
    ]
    
    for capture_pattern, remove_pattern in duration_patterns:
        match = re.search(capture_pattern, cleaned, re.IGNORECASE)
        if match:
            duration = match.group(1).strip()
            cleaned = re.sub(remove_pattern, '', cleaned, flags=re.IGNORECASE)
            break
    
    # 3. 提取尺寸
    size_patterns = [
        # 完整的双语尺寸
        (r'Dimension[s]?\s+variable\s*/\s*尺寸可变', 'Dimension variable / 尺寸可变'),
        (r'Dimension[s]?\s+variable', 'Dimension variable'),
        (r'尺寸可变', '尺寸可变'),
        # "size XxYxZ cm" 格式
        (r'[,;]?\s*size\s+(\d+\s*[×xX]\s*\d+(?:\s*[×xX]\s*\d+)?\s*(?:cm|mm|m)?)', None),
        # 独立的尺寸数字
        (r'[,;]?\s*(\d+\s*[×xX]\s*\d+(?:\s*[×xX]\s*\d+)?\s*(?:cm|mm)?)\s*[,;]?', None),
    ]
    
    for pattern, replacement in size_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            if replacement:
                size = replacement
            else:
                size = match.group(1) if match.lastindex else match.group(0)
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            break
    
    # 4. 清理多余的分隔符和空格
    cleaned = re.sub(r'[,;]\s*[,;]', ',', cleaned)
    cleaned = re.sub(r'^[,;\s]+|[,;\s]+$', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = cleaned.strip()
    size = size.strip()
    duration = duration.strip()
    
    return cleaned, size, duration


def process_file(input_path: str, output_path: str = None, dry_run: bool = False) -> int:
    """
    处理 JSON 文件，分离 materials 中的尺寸和时长信息。
    
    Args:
        input_path: 输入 JSON 文件路径
        output_path: 输出 JSON 文件路径（None 表示不保存）
        dry_run: 是否仅预览不修改
        
    Returns:
        修改的作品数量
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        works = json.load(f)
    
    changes = 0
    
    for work in works:
        old_materials = work.get('materials', '')
        old_size = work.get('size', '')
        old_duration = work.get('duration', '')
        
        # 只处理有 materials 且 size/duration 为空的情况
        if old_materials and (not old_size or not old_duration):
            new_materials, new_size, new_duration = clean_materials(old_materials)
            
            # 检查是否有变化
            has_change = False
            if new_materials != old_materials:
                has_change = True
            if new_size and not old_size:
                has_change = True
            if new_duration and not old_duration:
                has_change = True
            
            if has_change:
                changes += 1
                
                if dry_run:
                    print(f"\n📦 {work.get('title', 'Unknown')}")
                    print(f"   URL: {work.get('url', '')[:60]}...")
                    if old_materials != new_materials:
                        print(f"   Materials: '{old_materials}' → '{new_materials}'")
                    if new_size and not old_size:
                        print(f"   Size: '' → '{new_size}'")
                    if new_duration and not old_duration:
                        print(f"   Duration: '' → '{new_duration}'")
                else:
                    work['materials'] = new_materials
                    if new_size and not old_size:
                        work['size'] = new_size
                    if new_duration and not old_duration:
                        work['duration'] = new_duration
    
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Total changes: {changes} / {len(works)} works")
    
    if not dry_run and output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(works, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved to: {output_path}")
    
    return changes


def main():
    parser = argparse.ArgumentParser(
        description='清洗 aaajiao 作品数据，分离尺寸和时长信息'
    )
    parser.add_argument('input', help='输入 JSON 文件路径')
    parser.add_argument('-o', '--output', help='输出 JSON 文件路径（默认覆盖原文件）')
    parser.add_argument('--dry-run', action='store_true', help='仅预览变更，不修改文件')
    
    args = parser.parse_args()
    
    if args.dry_run:
        output_path = None
    elif args.output:
        output_path = args.output
    else:
        output_path = args.input  # 覆盖原文件
    
    process_file(args.input, output_path, args.dry_run)


if __name__ == "__main__":
    main()
