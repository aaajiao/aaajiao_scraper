#!/usr/bin/env python3
"""
Quick Start Example - aaajiao Portfolio Scraper

展示基本使用流程：初始化、爬取、导出
"""

from scraper import AaajiaoScraper


def main():
    """基础使用示例"""
    print("🚀 aaajiao 作品爬虫 - 快速开始\n")
    
    # 1. 初始化爬虫（自动从.env加载API key）
    print("📦 初始化爬虫...")
    scraper = AaajiaoScraper(use_cache=True)
    
    # 2. 获取所有作品链接（基础模式）
    print("\n🔍 从 sitemap 获取作品链接...")
    work_urls = scraper.get_all_work_links(incremental=False)
    print(f"   找到 {len(work_urls)} 个作品")
    
    # 3. 提取单个作品详情（AI 模式）
    if work_urls:
        print("\n🎨 提取第一个作品的详情...")
        first_url = work_urls[0]
        work_data = scraper.extract_work_details(first_url)
        
        if work_data:
            print(f"   ✅ 成功提取：{work_data.get('title', 'Unknown')}")
            print(f"   📅 年份：{work_data.get('year', 'N/A')}")
            print(f"   🏷️  类型：{work_data.get('category', 'N/A')}")
        else:
            print("   ❌ 提取失败")
    
    # 4. 导出结果
    print("\n💾 导出结果...")
    if scraper.works:
        scraper.save_to_json("output/quick_start_results.json")
        scraper.generate_markdown("output/quick_start_portfolio.md")
        print("   ✅ 已保存到 output/ 目录")
    else:
        print("   ⚠️  没有数据可导出")
    
    print("\n✨ 完成！")


if __name__ == "__main__":
    main()
