#!/usr/bin/env python3
"""
Batch Extraction Example - 批量提取示例

使用 Firecrawl 的批量提取 API，高效处理多个URL
"""

from scraper import AaajiaoScraper


def main():
    """批量提取作品信息"""
    print("🚀 批量提取示例\n")
    
    # 初始化
    scraper = AaajiaoScraper(use_cache=True)
    
    # 1. 获取所有作品URL
    print("📋 获取作品列表...")
    work_urls = scraper.get_all_work_links(incremental=False)
    print(f"   找到 {len(work_urls)} 个作品\n")
    
    # 2. 批量提取（使用 agent_search）
    # 这比逐个调用 extract_work_details 更高效
    print("🔄 批量提取中...")
    print("   提取级别：Quick（快速模式）")
    print("   启用缓存：是\n")
    
    result = scraper.agent_search(
        prompt="提取所有作品的基本信息：标题、年份、类型",
        urls=work_urls[:10],  # 先处理前10个作为示例
        extraction_level="quick"
    )
    
    # 3. 查看结果
    if result and "data" in result:
        extracted_works = result["data"]
        print(f"✅ 成功提取 {len(extracted_works)} 个作品")
        print(f"📊 缓存命中：{result.get('cached_count', 0)} 个")
        print(f"🆕 新提取：{result.get('new_count', 0)} 个")
        print(f"💰 API 消耗：{result.get('creditsUsed', 'N/A')} credits\n")
        
        # 显示前3个作品
        print("📝 示例作品：")
        for i, work in enumerate(extracted_works[:3], 1):
            print(f"   {i}. {work.get('title', 'Unknown')} ({work.get('year', 'N/A')})")
        
        # 4. 保存结果
        print("\n💾 保存结果...")
        scraper.works = extracted_works
        scraper.save_to_json("output/batch_extraction_results.json")
        print("   ✅ 已保存到 output/batch_extraction_results.json")
    else:
        print("❌ 批量提取失败")
    
    print("\n✨ 完成！")


if __name__ == "__main__":
    main()
