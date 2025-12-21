#!/usr/bin/env python3
"""
aaajiao 作品集爬虫 (Optimized v3 - Firecrawl Edition)
从 https://eventstructure.com/ 抓取所有作品详细信息

v3 改进：
1. 使用 Firecrawl AI 提取结构化数据 (精准度大幅提升)
2. API Key 安全管理 (环境变量)
3. 智能速率控制 (避免 Rate Limit)
4. 本地缓存 (节省 API 调用)
5. 实时进度条 (用户友好)
"""

import os
import sys
import time
import re
import json
import logging
import hashlib
import pickle
import concurrent.futures
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin
import argparse
from threading import Lock
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from tqdm import tqdm

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class RateLimiter:
    """线程安全的速率限制器"""
    def __init__(self, calls_per_minute: int = 5):
        self.interval = 60.0 / calls_per_minute
        self.last_call = 0
        self.lock = Lock()
    
    def wait(self):
        """等待直到允许下一次调用"""
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
                logger.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self.last_call = time.time()

class AaajiaoScraper:
    BASE_URL = "https://eventstructure.com"
    SITEMAP_URL = "https://eventstructure.com/sitemap.xml"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    MAX_WORKERS = 2  # 降低并发数，配合速率控制
    TIMEOUT = 15
    FC_TIMEOUT = 30  # Firecrawl 专用超时

    def __init__(self, use_cache: bool = True):
        self.session = self._create_retry_session()
        self.works: List[Dict[str, Any]] = []
        self.use_cache = use_cache
        
        # 加载 API Key
        self.firecrawl_key = self._load_api_key()
        
        # 初始化速率限制器 (5 calls/min)
        self.rate_limiter = RateLimiter(calls_per_minute=5)
        
        logger.info(f"Scraper 初始化完成 (缓存: {'开启' if use_cache else '关闭'})")
    
    def _load_api_key(self) -> str:
        """从环境变量或 .env 文件加载 API Key"""
        # 优先从环境变量读取
        key = os.getenv("FIRECRAWL_API_KEY")
        
        # 如果没有，尝试读取 .env 文件
        if not key:
            env_file = os.path.join(os.path.dirname(__file__), '.env')
            if os.path.exists(env_file):
                with open(env_file, 'r') as f:
                    for line in f:
                        if line.startswith('FIRECRAWL_API_KEY='):
                            key = line.split('=', 1)[1].strip()
                            break
        
        if not key:
            raise ValueError(
                "未找到 Firecrawl API Key！\n"
                "请设置环境变量: export FIRECRAWL_API_KEY='your-key'\n"
                "或在项目根目录创建 .env 文件"
            )
        
        logger.info(f"API Key 加载成功 (长度: {len(key)})")
        return key

    def _create_retry_session(self, retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update(self.HEADERS)
        return session

    def get_all_work_links(self) -> List[str]:
        """从 Sitemap 获取所有作品链接"""
        logger.info(f"正在读取 Sitemap: {self.SITEMAP_URL}")
        try:
            response = self.session.get(self.SITEMAP_URL, timeout=self.TIMEOUT)
            response.raise_for_status()
            
            # 简单的 XML 解析 (避免引入 lxml 依赖)
            soup = BeautifulSoup(response.content, 'html.parser') # xml parser needs lxml usually, html.parser handles basic tags ok
            
            links = []
            for loc in soup.find_all('loc'):
                url = loc.get_text().strip()
                if self._is_valid_work_link(url):
                    links.append(url)
            
            # 去重
            links = sorted(list(set(links)))
            logger.info(f"Sitemap 中找到 {len(links)} 个有效作品链接")
            return links
            
        except Exception as e:
            logger.error(f"Sitemap 读取失败: {e}")
            # Fallback to main page scan if sitemap fails
            return self._fallback_scan_main_page()

    def _fallback_scan_main_page(self):
        """备用方案：从主页扫描链接"""
        logger.info("尝试扫描主页链接 (备用方案)...")
        try:
            r = self.session.get(self.BASE_URL, timeout=self.TIMEOUT)
            soup = BeautifulSoup(r.text, 'html.parser')
            links = set()
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('/'):
                    full = urljoin(self.BASE_URL, href)
                    if self._is_valid_work_link(full):
                        links.add(full)
            return list(links)
        except Exception as e:
            logger.error(f"主页扫描失败: {e}")
            return []

    def _is_valid_work_link(self, url: str) -> bool:
        """过滤非作品链接"""
        if not url.startswith(self.BASE_URL):
            return False
            
        path = url.replace(self.BASE_URL, '')
        
        # 排除列表
        excludes = [
            '/', '/rss', '/feed', '/filter', '/aaajiao', 
            '/contact', '/cv', '/about', '/index', '/sitemap'
        ]
        
        if path in ['/', '']: return False
        
        for ex in excludes:
            if ex in path and len(path) < 20: # simple heuristic
                if path == ex or path.startswith(ex + '/'):
                    return False
        
        # Cargo 特性: 往往作品链接都很短，或者包含特定关键词
        # 这里主要排除 filter 页面
        if '/filter/' in path: return False
        
        return True

    def extract_work_details(self, url: str, retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """提取详情 (使用 Firecrawl AI 提取，带缓存和重试)"""
        max_retries = 3
        
        # 1. 检查缓存
        if self.use_cache:
            cached = self._load_cache(url)
            if cached:
                logger.debug(f"命中缓存: {url}")
                return cached
        
        # 2. 速率限制
        self.rate_limiter.wait()
        
        try:
            logger.info(f"[{retry_count+1}/{max_retries}] 正在抓取: {url}")
            
            fc_endpoint = "https://api.firecrawl.dev/v1/scrape"
            
            schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The English title of the work"},
                    "title_cn": {"type": "string", "description": "The Chinese title of the work. If not explicitly found, leave empty."},
                    "year": {"type": "string", "description": "Creation year or year range (e.g. 2018-2022)"},
                    "type": {"type": "string", "description": "The art category (e.g. Video Installation, Software, Website)"},
                    "materials": {"type": "string", "description": "Materials list (e.g. LED screen, 3D printing)"},
                    "description_en": {"type": "string", "description": "Detailed work description in English. Exclude navigation text."},
                    "description_cn": {"type": "string", "description": "Detailed work description in Chinese. Exclude navigation text."},
                    "video_link": {"type": "string", "description": "Vimeo URL if present"}
                },
                "required": ["title"]
            }
            
            payload = {
                "url": url,
                "formats": ["extract"],
                "extract": {
                    "schema": schema,
                    "systemPrompt": "You are an art archivist. Extract the artwork metadata from the portfolio page. Ignore navigation links like 'Previous/Next project'. The title usually appears as 'English Title / Chinese Title'. Separate them."
                }
            }
            
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            resp = requests.post(fc_endpoint, json=payload, headers=headers, timeout=self.FC_TIMEOUT)
            
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and 'extract' in data['data']:
                    result = data['data']['extract']
                    
                    work = {
                        'url': url,
                        'title': result.get('title', ''),
                        'title_cn': result.get('title_cn', ''),
                        'type': result.get('type', ''),
                        'materials': result.get('materials', ''),
                        'year': result.get('year', ''),
                        'description_cn': result.get('description_cn', ''),
                        'description_en': result.get('description_en', ''),
                        'video_link': result.get('video_link', ''),
                        'size': '',
                        'duration': '',
                        'tags': []
                    }
                    
                    # 后处理：如果 AI 没分清标题
                    if not work['title_cn'] and '/' in work['title']:
                        parts = work['title'].split('/')
                        work['title'] = parts[0].strip()
                        if len(parts) > 1:
                            work['title_cn'] = parts[1].strip()
                    
                    # 保存到缓存
                    if self.use_cache:
                        self._save_cache(url, work)
                            
                    return work
                else:
                    logger.error(f"Firecrawl 返回格式异常: {data}")
                    
            elif resp.status_code == 429:
                # Rate Limit - 指数退避重试
                if retry_count >= max_retries:
                    logger.error(f"重试次数超限: {url}")
                    return None
                wait_time = 2 ** retry_count  # 1s, 2s, 4s
                logger.warning(f"Rate Limit，等待 {wait_time}s 后重试...")
                time.sleep(wait_time)
                return self.extract_work_details(url, retry_count + 1)
                
            else:
                logger.error(f"Firecrawl Error {resp.status_code}: {resp.text[:200]}")
                
            return None

        except Exception as e:
            logger.error(f"API 请求错误 {url}: {e}")
            return None
    
    # ==================== 缓存系统 ====================
    
    def _get_cache_path(self, url: str) -> str:
        """生成缓存文件路径"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_dir = os.path.join(os.path.dirname(__file__), '.cache')
        return os.path.join(cache_dir, f"{url_hash}.pkl")
    
    def _load_cache(self, url: str) -> Optional[Dict]:
        """加载缓存"""
        cache_path = self._get_cache_path(url)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception:
                pass
        return None
    
    def _save_cache(self, url: str, data: Dict):
        """保存到缓存"""
        cache_path = self._get_cache_path(url)
        cache_dir = os.path.dirname(cache_path)
        os.makedirs(cache_dir, exist_ok=True)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"缓存保存失败: {e}")
    
    # ==================== 数据验证 ====================
    
    def validate_work(self, work: Dict) -> bool:
        """验证作品数据完整性"""
        if not work.get('title'):
            logger.warning(f"作品缺少标题: {work.get('url')}")
            return False
        return True

    def scrape_all(self):
        """抓取所有作品（带进度条和验证）"""
        work_links = self.get_all_work_links()
        total = len(work_links)
        valid_count = 0
        failed_count = 0
        
        logger.info(f"开始抓取 {total} 个作品...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_url = {executor.submit(self.extract_work_details, url): url for url in work_links}
            
            # 使用 tqdm 进度条
            for future in tqdm(concurrent.futures.as_completed(future_to_url), 
                               total=total, 
                               desc="抓取进度",
                               unit="作品"):
                url = future_to_url[future]
                try:
                    data = future.result()
                    if data and self.validate_work(data):
                        self.works.append(data)
                        valid_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"处理失败 {url}: {e}")
                    failed_count += 1

        logger.info(f"抓取完成！有效: {valid_count}/{total}, 失败: {failed_count}")
        return self.works

    def save_to_json(self, filename: str = 'aaajiao_works.json'):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.works, f, ensure_ascii=False, indent=2)

    def generate_markdown(self, filename: str = 'aaajiao_portfolio.md'):
        """生成 Markdown 格式的作品集文档"""
        lines = [
            "# aaajiao 作品集 / aaajiao Portfolio\n",
            f"Source: {self.BASE_URL}\n",
            "Generated by aaajiao Scraper v3 (Firecrawl Edition)\n",
            "\n---\n\n"
        ]
        
        # Sort by year
        sorted_works = sorted(self.works, key=lambda x: x.get('year') or '0000', reverse=True)
        
        current_year = None
        for work in sorted_works:
            year = work.get('year', 'Unknown')
            if year != current_year:
                lines.append(f"## {year}\n\n")
                current_year = year
                
            title = work.get('title', 'Untitled')
            title_cn = work.get('title_cn', '')
            
            header = f"### [{title}]({work['url']})"
            if title_cn:
                header += f" / {title_cn}"
            lines.append(header + "\n\n")
            
            if work.get('type'): 
                lines.append(f"**Type**: {work['type']}\n\n")
            if work.get('materials'):
                lines.append(f"**Materials**: {work['materials']}\n\n")
            if work.get('video_link'): 
                lines.append(f"**Video**: {work['video_link']}\n\n")
            
            if work.get('description_cn'):
                lines.append(f"> {work['description_cn']}\n\n")
                
            if work.get('description_en'):
                lines.append(f"{work['description_en']}\n\n")
                 
            lines.append("---\n")
            
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("".join(lines))
        
        logger.info(f"Markdown 文件已生成: {filename}")

    # ==================== Agent 模式 ====================
    
    def agent_search(self, prompt: str, urls: Optional[List[str]] = None, max_credits: int = 50) -> Optional[Dict[str, Any]]:
        """
        使用 Firecrawl Agent 进行开放式查询
        
        Args:
            prompt: 查询描述（自然语言）
            urls: 可选，指定要搜索的 URL 列表
            max_credits: 最大消耗 credits 数（控制成本）
            
        Returns:
            Agent 返回的结构化数据
        """
        logger.info(f"🤖 启动 Agent 任务...")
        logger.info(f"   Prompt: {prompt}")
        if urls:
            logger.info(f"   URLs: {urls}")
        
        agent_endpoint = "https://api.firecrawl.dev/v2/agent"
        
        headers = {
            "Authorization": f"Bearer {self.firecrawl_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "prompt": prompt,
            "maxCredits": max_credits
        }
        
        if urls:
            payload["urls"] = urls
        
        try:
            # 1. 启动 Agent 任务
            resp = requests.post(agent_endpoint, json=payload, headers=headers, timeout=self.FC_TIMEOUT)
            
            if resp.status_code != 200:
                logger.error(f"Agent 启动失败: {resp.status_code} - {resp.text[:200]}")
                return None
            
            result = resp.json()
            
            if not result.get("success"):
                logger.error(f"Agent 启动失败: {result}")
                return None
            
            job_id = result.get("id")
            if not job_id:
                # 同步模式：直接返回结果
                if result.get("status") == "completed":
                    logger.info(f"✅ Agent 任务完成 (credits: {result.get('creditsUsed', 'N/A')})")
                    return result.get("data")
                logger.error(f"Agent 返回格式异常: {result}")
                return None
            
            # 2. 轮询等待任务完成
            logger.info(f"   任务 ID: {job_id}")
            status_endpoint = f"{agent_endpoint}/{job_id}"
            max_wait = 300  # 最长等待 5 分钟
            poll_interval = 5  # 每 5 秒查询一次
            elapsed = 0
            
            while elapsed < max_wait:
                time.sleep(poll_interval)
                elapsed += poll_interval
                
                status_resp = requests.get(status_endpoint, headers=headers, timeout=self.FC_TIMEOUT)
                
                if status_resp.status_code != 200:
                    logger.warning(f"状态查询失败: {status_resp.status_code}")
                    continue
                
                status_data = status_resp.json()
                status = status_data.get("status")
                
                if status == "processing":
                    logger.info(f"   ⏳ 处理中... ({elapsed}s)")
                    continue
                elif status == "completed":
                    credits_used = status_data.get("creditsUsed", "N/A")
                    logger.info(f"✅ Agent 任务完成 (耗时: {elapsed}s, credits: {credits_used})")
                    return status_data.get("data")
                elif status == "failed":
                    logger.error(f"Agent 任务失败: {status_data}")
                    return None
                else:
                    logger.warning(f"未知状态: {status}")
            
            logger.error(f"Agent 任务超时 ({max_wait}s)")
            return None
            
        except Exception as e:
            logger.error(f"Agent 请求错误: {e}")
            return None


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="aaajiao 作品集爬虫 - Firecrawl Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 抓取所有作品（默认模式）
  python3 aaajiao_scraper.py
  
  # Agent 模式：开放式查询
  python3 aaajiao_scraper.py --agent "Find all video installations by aaajiao"
  
  # Agent 模式 + 指定 URL
  python3 aaajiao_scraper.py --agent "Summarize this artwork" --urls "https://eventstructure.com/Absurd-Reality-Check"
        """
    )
    
    parser.add_argument(
        "--agent", "-a",
        type=str,
        metavar="PROMPT",
        help="使用 Agent 模式进行开放式查询"
    )
    
    parser.add_argument(
        "--urls", "-u",
        type=str,
        metavar="URL1,URL2",
        help="Agent 模式下指定的 URL 列表（逗号分隔）"
    )
    
    parser.add_argument(
        "--max-credits",
        type=int,
        default=50,
        help="Agent 模式下的最大 credits 消耗（默认: 50）"
    )
    
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用缓存，强制重新抓取"
    )
    
    args = parser.parse_args()
    
    scraper = AaajiaoScraper(use_cache=not args.no_cache)
    
    if args.agent:
        # Agent 模式
        urls = args.urls.split(",") if args.urls else None
        result = scraper.agent_search(args.agent, urls=urls, max_credits=args.max_credits)
        
        if result:
            print("\n" + "="*50)
            print("📋 Agent 结果:")
            print("="*50)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("❌ Agent 查询失败")
            sys.exit(1)
    else:
        # 默认模式：抓取所有作品
        scraper.scrape_all()
        scraper.save_to_json()
        scraper.generate_markdown()


if __name__ == "__main__":
    main()