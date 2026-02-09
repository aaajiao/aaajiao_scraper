#!/usr/bin/env python3
"""
批量更新作品数据 - 使用两层混合提取策略

这个脚本使用 AaajiaoScraper 的 extract_work_details_v2 方法进行批量提取，
采用 Layer 1 (BS4) + Layer 2 (Schema Extract) 混合策略。

Usage:
    python scripts/batch_update_works.py --dry-run          # 预览模式
    python scripts/batch_update_works.py --limit 10         # 只处理前 10 个
    python scripts/batch_update_works.py                    # 处理所有作品
"""
import json
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import AaajiaoScraper


def batch_update(
    input_file: str,
    output_file: str,
    limit: int = None,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """批量更新作品数据

    Args:
        input_file: 输入 JSON 文件路径
        output_file: 输出 JSON 文件路径
        limit: 限制处理数量
        dry_run: 预览模式，不实际修改
        force: 强制重新提取所有作品（忽略已有字段）

    Returns:
        更新的作品数量
    """
    # 加载现有数据
    with open(input_file, 'r', encoding='utf-8') as f:
        works = json.load(f)

    # 初始化 scraper
    scraper = AaajiaoScraper(use_cache=True)

    # 筛选需要更新的作品（缺失关键字段的）
    required_fields = ['size', 'duration', 'materials', 'description_en', 'credits']

    if force:
        to_update = works
    else:
        to_update = [
            w for w in works
            if sum(1 for f in required_fields if not w.get(f)) >= 2
        ]

    if limit:
        to_update = to_update[:limit]

    print(f"📊 总作品数: {len(works)}")
    print(f"📋 需要更新: {len(to_update)}")
    print(f"💰 预计消耗: ~{len(to_update) * 30} Credits (按 ~30 credits/page 估算)")
    print()

    if dry_run:
        print("[DRY RUN] 以下作品将被更新:")
        for w in to_update[:10]:
            missing = [f for f in required_fields if not w.get(f)]
            print(f"  - {w.get('title', 'Unknown')[:40]}")
            print(f"    缺失字段: {', '.join(missing)}")
        if len(to_update) > 10:
            print(f"  ... 还有 {len(to_update) - 10} 个")
        return 0

    # 创建 URL 到 work 的映射
    url_to_work = {w['url']: w for w in works}

    updated = 0
    errors = 0

    for i, work in enumerate(to_update, 1):
        url = work.get('url')
        title = work.get('title', 'Unknown')[:30]

        print(f"[{i}/{len(to_update)}] {title}...")

        # 使用新的两层混合策略提取
        extracted = scraper.extract_work_details_v2(url)

        if extracted:
            # 更新作品数据
            changes = []
            for field in required_fields:
                if extracted.get(field) and not work.get(field):
                    url_to_work[url][field] = extracted[field]
                    value_preview = str(extracted[field])[:30]
                    changes.append(f"{field}='{value_preview}'")

            # 同时更新其他可能改进的字段
            for field in ['title_cn', 'description_cn', 'type']:
                if extracted.get(field) and not work.get(field):
                    url_to_work[url][field] = extracted[field]
                    changes.append(f"{field}")

            if changes:
                print(f"    ✅ 更新: {', '.join(changes[:4])}")
                if len(changes) > 4:
                    print(f"       + {len(changes) - 4} 更多字段")
                updated += 1
            else:
                print(f"    ⚪ 无新数据")
        else:
            print(f"    ❌ 提取失败")
            errors += 1

        # 每 20 个保存一次进度
        if i % 20 == 0:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(works, f, ensure_ascii=False, indent=2)
            print(f"    💾 进度已保存 ({i}/{len(to_update)})")

    # 最终保存
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(works, f, ensure_ascii=False, indent=2)

    print()
    print(f"✅ 完成! 更新: {updated}, 错误: {errors}")
    print(f"💾 保存到: {output_file}")

    return updated


def main():
    parser = argparse.ArgumentParser(description='批量更新作品信息（两层混合策略）')
    parser.add_argument('-i', '--input', default='aaajiao_works.json', help='输入文件')
    parser.add_argument('-o', '--output', default='aaajiao_works.json', help='输出文件')
    parser.add_argument('--limit', type=int, help='限制处理数量')
    parser.add_argument('--dry-run', action='store_true', help='预览模式')
    parser.add_argument('--force', action='store_true', help='强制更新所有作品')

    args = parser.parse_args()

    batch_update(
        args.input,
        args.output,
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    main()
