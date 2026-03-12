#!/usr/bin/env python3
"""
验证 Layer 2 (Firecrawl Extract) 提取质量

测试几个不同类型的作品，检查 Layer 2 返回的数据是否完整准确。

Usage:
    python portfolio_scraper/scripts/verify_layer2.py
"""
import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT))

from scraper import AaajiaoScraper

# 测试 URL - 选择不同类型的作品
TEST_URLS = [
    # Installation 作品
    "https://eventstructure.com/ai-ai-ai",
    # Video Installation 作品
    "https://eventstructure.com/A-I-Goooooooooogle-infiltration",
    # Website/Software 作品
    "https://eventstructure.com/010000-org",
    # Mixed media
    "https://eventstructure.com/Absurd-Reality-Check",
]

# 期望的字段
EXPECTED_FIELDS = {
    'title': '必须有',
    'year': '必须有',
    'type': '应该有',
    'description_en': '应该有',
    'materials': '根据类型',
    'size': '根据类型',
    'duration': '仅 Video',
}


def verify_extraction():
    """验证 Layer 2 提取质量"""
    scraper = AaajiaoScraper(use_cache=False)  # 不使用缓存，直接调用 API

    print("=" * 60)
    print("Layer 2 提取质量验证")
    print("=" * 60)

    results = []

    for url in TEST_URLS:
        print(f"\n📍 测试: {url.split('/')[-1]}")
        print("-" * 40)

        # 直接调用 Layer 2 (Schema Extract)
        data = scraper._extract_with_schema(url)

        if not data:
            print("❌ 提取失败!")
            results.append({'url': url, 'success': False})
            continue

        # 打印提取结果
        print(f"✅ 提取成功")
        print(f"   title:          {data.get('title', '❌ 缺失')}")
        print(f"   title_cn:       {data.get('title_cn', '—')}")
        print(f"   year:           {data.get('year', '❌ 缺失')}")
        print(f"   type:           {data.get('type', '—')}")
        print(f"   materials:      {data.get('materials', '—')[:50] if data.get('materials') else '—'}...")
        print(f"   size:           {data.get('size', '—')}")
        print(f"   duration:       {data.get('duration', '—')}")
        print(f"   credits:        {data.get('credits', '—')[:50] if data.get('credits') else '—'}...")
        print(f"   description_en: {len(data.get('description_en', '')) if data.get('description_en') else 0} chars")
        print(f"   description_cn: {len(data.get('description_cn', '')) if data.get('description_cn') else 0} chars")

        # 评估完整性
        score = 0
        total = 0

        # 必须字段
        if data.get('title'):
            score += 1
        total += 1

        if data.get('year'):
            score += 1
        total += 1

        # 应该有的字段
        if data.get('type'):
            score += 1
        total += 1

        if data.get('description_en') or data.get('description_cn'):
            score += 1
        total += 1

        # 可选字段 (有则加分)
        if data.get('materials'):
            score += 0.5
        if data.get('size'):
            score += 0.5
        if data.get('duration'):
            score += 0.5
        if data.get('credits'):
            score += 0.5

        total += 2  # 可选字段总共算 2 分

        completeness = score / total * 100
        print(f"\n   完整度: {completeness:.0f}%")

        results.append({
            'url': url,
            'success': True,
            'data': data,
            'completeness': completeness
        })

    # 总结
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)

    success_count = sum(1 for r in results if r['success'])
    avg_completeness = sum(r.get('completeness', 0) for r in results if r['success']) / max(success_count, 1)

    print(f"成功率: {success_count}/{len(TEST_URLS)}")
    print(f"平均完整度: {avg_completeness:.0f}%")

    if avg_completeness >= 80:
        print("\n✅ Layer 2 提取质量良好")
    elif avg_completeness >= 60:
        print("\n⚠️ Layer 2 提取质量一般，可能需要优化 prompt")
    else:
        print("\n❌ Layer 2 提取质量差，需要检查 schema 和 prompt")

    return results


if __name__ == "__main__":
    verify_extraction()
