#!/usr/bin/env python3
"""
Incremental Scrape Example - 增量爬取示例

只处理新增或修改的作品，节省时间和API消耗
"""

import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT))

from scraper import AaajiaoScraper
from scraper.paths import OUTPUT_DIR


def main():
    """增量爬取示例"""
    print("🔄 增量爬取示例\n")
    
    # 初始化（必须启用缓存）
    scraper = AaajiaoScraper(use_cache=True)
    
    # 1. 增量模式获取URL
    # 第一次运行会获取所有URL
    # 之后运行只会获取新增或修改的URL
    print("🔍 检查更新...")
    work_urls = scraper.get_all_work_links(incremental=True)
    
    if not work_urls:
        print("   ✅ 没有检测到新作品或更新")
        print("   💡 提示：如果需要重新爬取，删除 .cache/ 目录")
        return
    
    print(f"   🆕 发现 {len(work_urls)} 个新增/更新的作品\n")
    
    # 2. 仅提取更新的作品（使用两层混合策略）
    print("📥 提取更新的作品...")
    for i, url in enumerate(work_urls, 1):
        print(f"   [{i}/{len(work_urls)}] 处理中...")

        work_data = scraper.extract_work_details_v2(url)
        if work_data:
            title = work_data.get('title', 'Unknown')
            print(f"      ✅ {title}")
        else:
            print(f"      ❌ 失败：{url}")
    
    # 3. 保存结果
    if scraper.works:
        print(f"\n💾 保存 {len(scraper.works)} 个作品...")
        
        # 保存为带时间戳的文件
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = OUTPUT_DIR / f"incremental_{timestamp}.json"
        
        scraper.save_to_json(str(output_file))
        print(f"   ✅ 已保存到 {output_file}")
    
    # 4. 使用提示
    print("\n💡 增量爬取提示：")
    print("   - 定期运行此脚本，只会处理新内容")
    print("   - 缓存文件位于 .cache/ 目录")
    print("   - 如需完全重新爬取，删除 .cache/sitemap_lastmod.json")
    
    print("\n✨ 完成！")


if __name__ == "__main__":
    main()
