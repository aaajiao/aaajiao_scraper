#!/usr/bin/env python3
"""
批量更新作品数据 - 使用 Firecrawl scrape + markdown 模式

这个脚本使用低成本的 scrape 模式（约 1 Credit/页）获取渲染后的 markdown，
然后本地解析提取尺寸、时长等信息。

Usage:
    python scripts/batch_update_works.py --dry-run          # 预览模式
    python scripts/batch_update_works.py --limit 10         # 只处理前 10 个
    python scripts/batch_update_works.py                    # 处理所有作品
"""
import json
import re
import time
import argparse
import requests
from typing import Dict, Any, Optional, Tuple
from datetime import datetime


def load_api_key() -> str:
    """从 .env 文件加载 API key"""
    with open('.env', 'r') as f:
        for line in f:
            if line.startswith('FIRECRAWL_API_KEY'):
                return line.split('=')[1].strip()
    raise ValueError("FIRECRAWL_API_KEY not found in .env")


def scrape_markdown(url: str, api_key: str) -> Optional[str]:
    """使用 Firecrawl scrape 获取渲染后的 markdown（约 1 Credit）"""
    payload = {
        "url": url,
        "formats": ["markdown"],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v2/scrape",
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("markdown", "")
        elif resp.status_code == 429:
            print(f"    ⚠️ Rate limited, waiting 5s...")
            time.sleep(5)
            return scrape_markdown(url, api_key)  # 重试
        else:
            print(f"    ❌ Error {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        print(f"    ❌ Exception: {e}")
        return None


def parse_work_from_markdown(md: str, url: str) -> Dict[str, str]:
    """从 markdown 中解析作品的尺寸、时长等信息"""
    result = {
        "size": "",
        "duration": "",
        "type": "",
        "materials": "",
    }
    
    if not md:
        return result
    
    # 简化：直接从整个 markdown 文本中提取信息
    # 因为每个页面的 markdown 开头就是当前作品的信息
    
    # 只取前 2000 字符（通常包含主要作品信息）
    text = md[:2000]
    lines = text.split('\n')
    
    # 解析尺寸 - 匹配各种格式
    size_patterns = [
        r'size\s+(\d+\s*[×xX]\s*\d+(?:\s*[×xX]\s*\d+)?\s*(?:cm|mm|m)?)',  # size 280cm × 102cm
        r'^(\d+\s*[×xX]\s*\d+\s*[×xX]\s*\d+\s*(?:cm|mm)?)$',  # 280 × 102 × 30 cm (独立行)
        r'(Dimension[s]?\s+variable\s*/\s*尺寸可变)',  # 完整双语
        r'(Dimension[s]?\s+variable)',  # 英文
        r'^(尺寸可变)$',  # 中文独立行
    ]
    
    for line in lines:
        line = line.strip()
        if result["size"]:
            break
        for pattern in size_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                result["size"] = match.group(1).strip()
                break
    
    # 解析时长 - 视频作品
    duration_patterns = [
        r"^(\d+['′]\d+['′''\"]*)\s*$",   # 6'34 或 12'00'' (独立行)
        r"^(\d+['′''\"]+)\s*$",           # 43'' (独立行)
        r"video\s+(\d+['′''\"]+)",        # video 43''
        r"^(\d+:\d+(?::\d+)?)\s*$",       # 12:00 (独立行)
    ]
    
    for line in lines:
        line = line.strip()
        if result["duration"]:
            break
        for pattern in duration_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                result["duration"] = match.group(1).strip()
                break
    
    # 解析类型（通常在开头 15 行内）
    type_keywords = [
        'video installation', 'installation', 'video', 'website', 
        'software', 'performance', 'exhibition', 'single channel video',
        '装置', '录像装置', '录像', '网站'
    ]
    
    for line in lines[:15]:
        line_lower = line.strip().lower()
        for kw in type_keywords:
            if line_lower == kw or line_lower.startswith(kw + ' ') or line_lower.startswith(kw + '/'):
                result["type"] = line.strip()
                break
        if result["type"]:
            break
    
    return result


def batch_update(
    input_file: str,
    output_file: str,
    limit: int = None,
    dry_run: bool = False
) -> int:
    """批量更新作品数据"""
    
    # 加载现有数据
    with open(input_file, 'r', encoding='utf-8') as f:
        works = json.load(f)
    
    api_key = load_api_key()
    
    # 筛选需要更新的作品（没有 size 和 duration 的）
    to_update = [
        w for w in works 
        if not w.get('size') or not w.get('duration')
    ]
    
    if limit:
        to_update = to_update[:limit]
    
    print(f"📊 总作品数: {len(works)}")
    print(f"📋 需要更新: {len(to_update)}")
    print(f"💰 预计消耗: ~{len(to_update)} Credits")
    print()
    
    if dry_run:
        print("[DRY RUN] 以下作品将被更新:")
        for w in to_update[:10]:
            print(f"  - {w.get('title', 'Unknown')}: {w.get('url')}")
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
        
        # 抓取 markdown
        md = scrape_markdown(url, api_key)
        
        if md:
            # 解析提取信息
            extracted = parse_work_from_markdown(md, url)
            
            # 更新作品数据
            changes = []
            if extracted['size'] and not work.get('size'):
                url_to_work[url]['size'] = extracted['size']
                changes.append(f"size='{extracted['size']}'")
            
            if extracted['duration'] and not work.get('duration'):
                url_to_work[url]['duration'] = extracted['duration']
                changes.append(f"duration='{extracted['duration']}'")
            
            if extracted['type'] and not work.get('type'):
                url_to_work[url]['type'] = extracted['type']
                changes.append(f"type='{extracted['type']}'")
            
            if changes:
                print(f"    ✅ 更新: {', '.join(changes)}")
                updated += 1
            else:
                print(f"    ⚪ 无新数据")
        else:
            print(f"    ❌ 抓取失败")
            errors += 1
        
        # 避免 rate limit
        time.sleep(0.5)
        
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
    parser = argparse.ArgumentParser(description='批量更新作品的尺寸和时长信息')
    parser.add_argument('-i', '--input', default='aaajiao_works.json', help='输入文件')
    parser.add_argument('-o', '--output', default='aaajiao_works.json', help='输出文件')
    parser.add_argument('--limit', type=int, help='限制处理数量')
    parser.add_argument('--dry-run', action='store_true', help='预览模式')
    
    args = parser.parse_args()
    
    batch_update(
        args.input,
        args.output,
        limit=args.limit,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
