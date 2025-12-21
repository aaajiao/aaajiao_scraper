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
    CACHE_DIR = ".cache"
    
    # ==================== 提取 Schema 定义 ====================
    # Quick 模式：仅提取核心字段，节省 credits
    QUICK_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "English title of the artwork"},
            "title_cn": {"type": "string", "description": "Chinese title if available"},
            "year": {"type": "string", "description": "Creation year or year range"},
            "category": {"type": "string", "description": "Art category (e.g. Video, Installation)"},
            "has_images": {"type": "boolean", "description": "Whether the page contains images"}
        }
    }
    
    # Full 模式：完整字段提取
    FULL_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "English title"},
            "title_cn": {"type": "string", "description": "Chinese title"},
            "year": {"type": "string", "description": "Creation year"},
            "category": {"type": "string", "description": "Art category"},
            "description_en": {"type": "string", "description": "Full English description"},
            "description_cn": {"type": "string", "description": "Full Chinese description"},
            "high_res_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "High-res image URLs, prefer 'src_o' attribute"
            },
            "video_link": {"type": "string", "description": "Vimeo/YouTube URL if present"},
            "materials": {"type": "string", "description": "Materials used in the artwork"}
        }
    }
    
    # ==================== Prompt 模板库 ====================
    PROMPT_TEMPLATES = {
        "quick": "Extract basic artwork info: title (English and Chinese if available), year, and category. Return JSON only, no explanation.",
        "full": "Extract complete artwork details including title, year, category, full descriptions in English and Chinese, materials, and all high-resolution image URLs (use 'src_o' attribute when available). Return JSON only.",
        "images_only": "Extract all high-resolution image URLs from the page. Prioritize 'src_o' attributes for high-res versions. Exclude thumbnails and icons. Return as JSON array of URLs.",
        "default": "Extract all text content from the page (title, description, metadata, full text). Also extract the URL of the first visible image (or main artwork image) and map it to the field 'image'. IMPORTANT: If the image has a 'src_o' attribute, extract that URL for high resolution."
    }


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

    def get_all_work_links(self, incremental: bool = False) -> List[str]:
        """
        从 Sitemap 获取所有作品链接
        
        Args:
            incremental: 是否只返回更新/新增的链接
        
        Returns:
            有效作品链接列表
        """
        logger.info(f"正在读取 Sitemap: {self.SITEMAP_URL}")
        try:
            response = self.session.get(self.SITEMAP_URL, timeout=self.TIMEOUT)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 解析 URL 和 lastmod
            current_sitemap = {}  # {url: lastmod}
            raw_urls = soup.find_all('url')
            logger.info(f"Sitemap raw url tags found: {len(raw_urls)}")
            
            for url_tag in raw_urls:
                loc = url_tag.find('loc')
                lastmod = url_tag.find('lastmod')
                if loc:
                    url = loc.get_text().strip()
                    if self._is_valid_work_link(url):
                        current_sitemap[url] = lastmod.get_text().strip() if lastmod else ""
                    else:
                        # logger.debug(f"Filtered: {url}") # Optional: log filtered
                        pass
            
            logger.info(f"Sitemap 中找到 {len(current_sitemap)} 个有效作品链接 (Filtered from {len(raw_urls)})")
            
            if not incremental:
                # 全量模式：保存缓存后返回所有链接
                self._save_sitemap_cache(current_sitemap)
                return sorted(list(current_sitemap.keys()))
            
            # 增量模式：比较缓存
            cached_sitemap = self._load_sitemap_cache()
            changed_urls = []
            
            for url, lastmod in current_sitemap.items():
                if url not in cached_sitemap:
                    # 新增 URL
                    changed_urls.append(url)
                    logger.info(f"🆕 新增: {url}")
                elif lastmod and lastmod != cached_sitemap.get(url, ""):
                    # lastmod 变化
                    changed_urls.append(url)
                    logger.info(f"🔄 更新: {url} ({cached_sitemap.get(url)} → {lastmod})")
            
            if changed_urls:
                logger.info(f"📊 增量检测: {len(changed_urls)} 个更新/新增")
            else:
                logger.info("✅ 没有检测到更新")
            
            # 保存新缓存
            self._save_sitemap_cache(current_sitemap)
            
            return sorted(changed_urls)
            
        except Exception as e:
            logger.error(f"Sitemap 读取失败: {e}")
            return self._fallback_scan_main_page()
    
    def _load_sitemap_cache(self) -> Dict[str, str]:
        """加载 sitemap lastmod 缓存"""
        cache_path = os.path.join(self.CACHE_DIR, "sitemap_lastmod.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_sitemap_cache(self, sitemap: Dict[str, str]):
        """保存 sitemap lastmod 缓存"""
        cache_path = os.path.join(self.CACHE_DIR, "sitemap_lastmod.json")
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(sitemap, f, ensure_ascii=False, indent=2)

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
            
            fc_endpoint = "https://api.firecrawl.dev/v2/scrape"
            
            schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The English title of the work"},
                    "title_cn": {"type": "string", "description": "The Chinese title of the work. If not explicitly found, leave empty."},
                    "year": {"type": "string", "description": "Creation year or year range (e.g. 2018-2022)"},
                    "year": {"type": "string", "description": "Creation year or year range (e.g. 2018-2022)"},
                    "category": {"type": "string", "description": "The art category (e.g. Video Installation, Software, Website)"},
                    "materials": {"type": "string", "description": "Materials list (e.g. LED screen, 3D printing)"},
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
                        'type': result.get('category', '') or result.get('type', ''),
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
    
    # ==================== Extract 缓存（v2/extract 专用）====================
    
    @property
    def cache_dir(self) -> str:
        """缓存目录路径"""
        return os.path.join(os.path.dirname(__file__), '.cache')
    
    def _get_extract_cache_path(self, url: str, prompt_hash: str) -> str:
        """生成 Extract 缓存路径（包含 prompt hash 防止不同 prompt 冲突）"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"extract_{url_hash}_{prompt_hash[:8]}.pkl")
    
    def _load_extract_cache(self, url: str, prompt: str) -> Optional[Dict]:
        """加载 Extract 缓存"""
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_path = self._get_extract_cache_path(url, prompt_hash)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    logger.debug(f"Extract 缓存命中: {url[:50]}...")
                    return pickle.load(f)
            except Exception:
                pass
        return None
    
    def _save_extract_cache(self, url: str, prompt: str, data: Dict):
        """保存 Extract 缓存"""
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_path = self._get_extract_cache_path(url, prompt_hash)
        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"Extract 缓存保存失败: {e}")
    
    # ==================== Discovery 缓存（扫描结果持久化）====================
    
    def _get_discovery_cache_path(self, url: str, scroll_mode: str) -> str:
        """生成 Discovery 缓存路径"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"discovery_{url_hash}_{scroll_mode}.json")
    
    def _is_discovery_cache_valid(self, cache_path: str, ttl_hours: int = 24) -> bool:
        """检查 Discovery 缓存是否有效（默认 24h TTL）"""
        if not os.path.exists(cache_path):
            return False
        mtime = os.path.getmtime(cache_path)
        return (time.time() - mtime) < (ttl_hours * 3600)
    
    # ==================== 数据验证 ====================
    
    def validate_work(self, work: Dict) -> bool:
        """验证作品数据完整性"""
        if not work.get('title'):
            logger.warning(f"作品缺少标题: {work.get('url')}")
            return False
        return True

    def scrape_all(self, incremental: bool = False):
        """
        抓取所有作品（带进度条和验证）
        
        Args:
            incremental: 增量模式，只抓取更新/新增的页面
        """
        work_links = self.get_all_work_links(incremental=incremental)
        
        if incremental and not work_links:
            logger.info("✅ 增量模式：没有检测到更新，跳过抓取")
            return 0, 0  # (valid_count, failed_count)
        
        total = len(work_links)
        valid_count = 0
        failed_count = 0
        
        mode_label = "增量抓取" if incremental else "全量抓取"
        logger.info(f"开始{mode_label} {total} 个作品...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_url = {executor.submit(self.extract_work_details, url): url for url in work_links}
            
            for future in tqdm(concurrent.futures.as_completed(future_to_url), 
                               total=total, 
                               desc=mode_label,
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
        return valid_count, failed_count

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

    # ==================== Discovery Mode ====================

    def discover_urls_with_scroll(self, url: str, scroll_mode: str = "auto", use_cache: bool = True) -> List[str]:
        """
        Phase 1: 使用 Scrape 模式 + 滚动动作去发现作品链接
        
        Args:
            url: 目标列表页 URL
            scroll_mode: 滚动模式 ("auto", "horizontal", "vertical")
            use_cache: 是否使用缓存（默认 True，24h TTL）
            
        Returns:
            发现的作品 URL 列表
        """
        
        # === 缓存检查 ===
        cache_path = self._get_discovery_cache_path(url, scroll_mode)
        if use_cache and self._is_discovery_cache_valid(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    cached = json.load(f)
                    logger.info(f"✅ Discovery 缓存命中: {len(cached)} 链接 (TTL: 24h)")
                    return cached
            except Exception:
                pass
        
        logger.info(f"🕵️  启动 Discovery Phase: {url} (Mode: {scroll_mode})")
        
        # 1. 配置滚动动作 (按照 Firecrawl 官方文档格式)
        actions = []
        
        # 初始等待页面加载
        actions.append({"type": "wait", "milliseconds": 2000})
        
        if scroll_mode == "horizontal":
            # 横向滚动：使用增强版 JS 脚本 (模拟滚动到底部触发加载)
            # 调整为 20 次循环 (这是一个平衡点：15次不够全，30次会超时)
            # 每次 1.5s，总耗时约 35s，安全可靠
            for i in range(20):
                actions.append({
                    "type": "executeJavascript", 
                    "script": """
                        // 1. 滚动到当前最右侧
                        window.scrollTo(document.documentElement.scrollWidth, 0);
                        // 2. 触发 scroll 事件以激活懒加载
                        window.dispatchEvent(new Event('scroll'));
                    """
                })
                # 等待 Carg CMS 加载新内容
                actions.append({"type": "wait", "milliseconds": 1500})
                
        elif scroll_mode == "vertical":
            # 垂直滚动：使用原生 scroll
            for _ in range(5):
                actions.append({"type": "scroll", "direction": "down"})
                actions.append({"type": "wait", "milliseconds": 1500})
            
        else:  # auto Mode
            # 混合模式：横向增强 + 垂直
            # 1. 横向滚动 (JS)
            for i in range(15):
                actions.append({
                    "type": "executeJavascript", 
                    "script": "window.scrollTo(document.documentElement.scrollWidth, 0); window.dispatchEvent(new Event('scroll'));"
                })
                actions.append({"type": "wait", "milliseconds": 1500})
            
            # 2. 垂直滚动
            for _ in range(3):
                actions.append({"type": "scroll", "direction": "down"})
                actions.append({"type": "wait", "milliseconds": 1500})
        
        payload = {
            "url": url,
            "formats": ["html"],
            "actions": actions,
            "onlyMainContent": False,  # 获取完整 DOM 以便提取链接
            "timeout": 300000 # 5分钟超时，确保跑完所有滚动动作
        }
        
        # 使用 v2 endpoint (官方文档推荐)
        endpoint = "https://api.firecrawl.dev/v2/scrape"
        headers = {
            "Authorization": f"Bearer {self.firecrawl_key}",
            "Content-Type": "application/json"
        }
        
        try:
            logger.info(f"   正在执行 Scrape + Actions (共 {len(actions)} 步)...")
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=300)
            
            if resp.status_code != 200:
                logger.error(f"Scrape 失败: {resp.status_code} - {resp.text[:200]}")
                return []
                
            data = resp.json()
            if not data.get("success"):
                logger.error(f"Scrape 任务失败: {data}")
                return []
                
            html_content = data.get("data", {}).get("html", "")
            if not html_content:
                logger.error("未获取到 HTML 内容")
                return []
                
            # 2. 从 HTML 提取链接
            logger.info(f"   获取到 HTML ({len(html_content)} chars)，正在提取链接...")
            found_links = self._extract_links_from_html(html_content, url)
            
            # === 保存到缓存 ===
            if found_links and use_cache:
                try:
                    os.makedirs(self.cache_dir, exist_ok=True)
                    with open(cache_path, 'w') as f:
                        json.dump(found_links, f)
                    logger.info(f"📝 Discovery 结果已缓存 ({len(found_links)} 链接)")
                except Exception as e:
                    logger.debug(f"Discovery 缓存保存失败: {e}")
            
            return found_links
            
        except Exception as e:
            logger.error(f"Discovery 异常: {e}")
            return []

    def _extract_links_from_html(self, html: str, base_url: str) -> List[str]:
        """从 HTML 中提取有价值的作品链接"""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        soup = BeautifulSoup(html, 'html.parser')
        links = set()
        
        # 经过分析，作品链接使用 'nohover' class，且位于 #content_container 内
        # 示例: <a class="nohover" href="/Project-Name">Title</a>
        # 我们使用精准的 CSS selector 来提取
        
        # 1. 尝试使用精准 selector
        artwork_links = soup.select('a.nohover')
        
        if not artwork_links:
             # Fallback if class changes: search inside content container
             container = soup.select_one('#content_container')
             if container:
                 artwork_links = container.find_all('a', href=True)
             else:
                 artwork_links = soup.find_all('a', href=True)
                 
        for a_tag in artwork_links:
            href = a_tag.get('href')
            if not href:
                continue
                
            full_url = urljoin(base_url, href)
            
            # 过滤逻辑：再次确保不包含非作品页
            if base_url in full_url:
                # 排除常见非作品页面 (Double Check)
                if not any(x in full_url.lower() for x in ['contact', 'about', 'cv', 'text', 'press', 'index', 'filter']):
                    links.add(full_url)
                
        sorted_links = sorted(list(links))
        logger.info(f"   发现 {len(sorted_links)} 个潜在作品链接")
        return sorted_links

    # ==================== Agent 模式 ====================
    
    def agent_search(self, prompt: str, urls: Optional[List[str]] = None, 
                      max_credits: int = 50, extraction_level: str = "custom") -> Optional[Dict[str, Any]]:
        """
        智能搜索/提取入口
        
        Args:
            prompt: 提取指令
            urls: 要提取的 URL 列表（可选）
            max_credits: 最大处理数量 / Agent 预算
            extraction_level: 提取级别 - "quick"(核心字段), "full"(完整), "custom"(用户自定义)
        
        策略分离:
        1. 指定 URLs -> 使用 v2/extract 批量提取 -> 针对已知页面进行结构化/内容提取
        2. 无 URLs (开放查询) -> 使用 v2/agent -> 成本高 (自主调研)
        """
        
        # === 根据提取级别选择 Schema 和 Prompt ===
        schema = None
        if extraction_level == "quick":
            schema = self.QUICK_SCHEMA
            if not prompt or prompt == self.PROMPT_TEMPLATES["default"]:
                prompt = self.PROMPT_TEMPLATES["quick"]
            logger.info(f"📋 使用 Quick 模式 (核心字段)")
        elif extraction_level == "full":
            schema = self.FULL_SCHEMA
            if not prompt or prompt == self.PROMPT_TEMPLATES["default"]:
                prompt = self.PROMPT_TEMPLATES["full"]
            logger.info(f"📋 使用 Full 模式 (完整字段)")
        elif extraction_level == "images_only":
            if not prompt or prompt == self.PROMPT_TEMPLATES["default"]:
                prompt = self.PROMPT_TEMPLATES["images_only"]
            logger.info(f"🖼️ 使用 Images Only 模式 (仅高清图)")
        # custom 模式使用用户提供的 prompt，不添加 schema
        
        # === 场景 1: 批量提取 (指定 URL) ===
        if urls and len(urls) > 0:
            # 限制 URL 数量以符合 Max Credits
            target_urls = urls[:max_credits]
            
            # === 缓存检查：分离已缓存和未缓存的 URL ===
            cached_results = []
            uncached_urls = []
            for url in target_urls:
                cached = self._load_extract_cache(url, prompt)
                if cached:
                    cached_results.append(cached)
                else:
                    uncached_urls.append(url)
            
            logger.info(f"🔍 缓存检查: 命中 {len(cached_results)}, 待提取 {len(uncached_urls)}")
            
            # 如果全部命中缓存，直接返回
            if not uncached_urls:
                logger.info(f"✅ 全部命中缓存，节省 API 调用！")
                return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
            
            logger.info(f"🚀 启动批量提取任务 (Target: {len(uncached_urls)} URLs)")
            logger.info(f"   Prompt: {prompt[:100]}...")
            
            extract_endpoint = "https://api.firecrawl.dev/v2/extract"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "urls": uncached_urls,  # 只提取未缓存的 URL
                "prompt": prompt,
                "enableWebSearch": False
            }
            
            # 如果指定了 Schema，添加到 payload
            if schema:
                payload["schema"] = schema

            try:
                # 1. 提交任务
                resp = requests.post(extract_endpoint, json=payload, headers=headers, timeout=self.FC_TIMEOUT)
                
                if resp.status_code != 200:
                    logger.error(f"Extract 启动失败: {resp.status_code} - {resp.text}")
                    # 如果 API 调用失败但有缓存结果，返回缓存部分
                    if cached_results:
                        return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                    return None
                    
                result = resp.json()
                if not result.get("success"):
                    logger.error(f"Extract 启动失败: {result}")
                    if cached_results:
                        return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                    return None
                
                job_id = result.get("id")
                if not job_id:
                     if result.get("status") == "completed":
                         new_data = result.get("data", [])
                         # 保存新结果到缓存
                         for item in new_data if isinstance(new_data, list) else [new_data]:
                             item_url = item.get("url") or item.get("sourceURL") or item.get("source_url")
                             if item_url:
                                 self._save_extract_cache(item_url, prompt, item)
                         return {"data": cached_results + (new_data if isinstance(new_data, list) else [new_data])}
                     return None

                # 2. 轮询等待
                logger.info(f"   Extract 任务 ID: {job_id}")
                status_endpoint = f"{extract_endpoint}/{job_id}"
                max_wait = 600 # 10分钟
                poll_interval = 5
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    
                    status_resp = requests.get(status_endpoint, headers=headers, timeout=self.FC_TIMEOUT)
                    if status_resp.status_code != 200: continue
                    
                    status_data = status_resp.json()
                    status = status_data.get("status")
                    
                    if status == "processing":
                        logger.info(f"   ⏳ 提取中... ({elapsed}s)")
                    elif status == "completed":
                        credits = status_data.get("creditsUsed", "N/A")
                        new_data = status_data.get("data", [])
                        
                        # === 保存新结果到缓存 ===
                        for item in new_data if isinstance(new_data, list) else [new_data]:
                            item_url = item.get("url") or item.get("sourceURL") or item.get("source_url")
                            if item_url:
                                self._save_extract_cache(item_url, prompt, item)
                                logger.debug(f"   💾 已缓存: {item_url[:50]}...")
                        
                        logger.info(f"✅ 提取完成 (Credits: {credits}, 新增缓存: {len(new_data) if isinstance(new_data, list) else 1})")
                        
                        # 合并缓存和新结果
                        all_data = cached_results + (new_data if isinstance(new_data, list) else [new_data])
                        return {"data": all_data, "cached_count": len(cached_results), "new_count": len(new_data) if isinstance(new_data, list) else 1}
                    elif status == "failed":
                        logger.error(f"提取任务失败: {status_data}")
                        if cached_results:
                            return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                        return None
                        
                return None
                
            except Exception as e:
                logger.error(f"Extract Exception: {e}")
                if cached_results:
                    return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                return None

        # === 场景 2: 开放式 Agent 搜索 (无 URL) ===
        else:
            logger.info(f"🤖 启动 Smart Agent 任务 (开放搜索)...")
            logger.info(f"   Prompt: {prompt}")
            
            agent_endpoint = "https://api.firecrawl.dev/v2/agent"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "prompt": prompt,
                "maxCredits": max_credits
            }
            
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
                    # 同步模式
                    if result.get("status") == "completed":
                        logger.info(f"✅ Agent 任务完成 (credits: {result.get('creditsUsed', 'N/A')})")
                        return result.get("data")
                    return None
                
                # 2. 轮询等待任务完成
                logger.info(f"   任务 ID: {job_id}")
                status_endpoint = f"{agent_endpoint}/{job_id}"
                max_wait = 300 
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(5)
                    elapsed += 5
                    
                    status_resp = requests.get(status_endpoint, headers=headers, timeout=self.FC_TIMEOUT)
                    
                    if status_resp.status_code != 200: continue
                    
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
                
                logger.error(f"Agent 任务超时 ({max_wait}s)")
                return None
                
            except Exception as e:
                logger.error(f"Agent 请求错误: {e}")
                return None


    # ==================== 图片下载和报告生成 ====================
    
    def download_images(self, image_urls: List[str], output_dir: str, timestamp: str = "") -> List[str]:
        """
        下载图片到本地
        
        Args:
            image_urls: 图片 URL 列表
            output_dir: 输出目录
            timestamp: 时间戳，用于创建独立的图片文件夹
            
        Returns:
            本地图片路径列表
        """
        # 使用带时间戳的文件夹名
        folder_name = f"images_{timestamp}" if timestamp else "images"
        images_dir = os.path.join(output_dir, folder_name)
        os.makedirs(images_dir, exist_ok=True)
        
        local_paths = []
        for i, url in enumerate(image_urls):
            try:
                # 清理 URL
                url = url.strip()
                if not url or not url.startswith(('http://', 'https://')):
                    continue
                
                # 生成文件名
                ext = os.path.splitext(url.split('?')[0])[-1] or '.jpg'
                if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    ext = '.jpg'
                filename = f"{i+1:02d}_image{ext}"
                local_path = os.path.join(images_dir, filename)
                
                logger.info(f"   下载图片 [{i+1}/{len(image_urls)}]: {filename}")
                
                # 下载
                resp = self.session.get(url, timeout=30, stream=True)
                if resp.status_code == 200:
                    with open(local_path, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    local_paths.append(f"{folder_name}/{filename}")
                else:
                    logger.warning(f"   下载失败: {url} (状态码: {resp.status_code})")
                    
            except Exception as e:
                logger.warning(f"   下载异常: {url} - {e}")
                
        return local_paths
    
    def generate_agent_report(self, data: Dict[str, Any], output_dir: str, prompt: str = "", extraction_level: str = "custom"):
        """
        根据 Agent 返回的数据生成 Markdown 报告和下载图片
        
        Args:
            data: Agent 返回的数据
            output_dir: 输出目录
            prompt: 用户输入的查询 prompt
            extraction_level: 提取级别
        """
        from datetime import datetime
        
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"📁 生成报告到: {output_dir}")
        
        # 解析数据列表
        data_list = data.get("data", [data]) if isinstance(data, dict) else [data]
        if not isinstance(data_list, list):
            data_list = [data_list]
        
        # 1. 创建图片目录并下载所有图片，建立 URL -> 本地路径映射
        images_dir = f"images_{timestamp}"
        images_path = os.path.join(output_dir, images_dir)
        os.makedirs(images_path, exist_ok=True)
        
        url_to_local = {}  # URL -> 相对路径映射
        img_counter = 0
        
        for item in data_list:
            if not isinstance(item, dict):
                continue
            images = item.get("high_res_images") or item.get("images") or []
            for img_url in images:
                if img_url in url_to_local:
                    continue  # 已下载
                img_counter += 1
                try:
                    ext = os.path.splitext(img_url.split("?")[0])[-1] or ".jpg"
                    if not ext.startswith("."):
                        ext = ".jpg"
                    local_filename = f"{img_counter:02d}{ext}"
                    local_path = os.path.join(images_path, local_filename)
                    
                    resp = requests.get(img_url, timeout=30)
                    if resp.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(resp.content)
                        url_to_local[img_url] = f"{images_dir}/{local_filename}"
                        logger.info(f"📥 下载图片 [{img_counter}]: {local_filename}")
                except Exception as e:
                    logger.warning(f"图片下载失败: {img_url[:50]}... - {e}")
        
        logger.info(f"✅ 成功下载 {len(url_to_local)} 张图片")
        
        # 2. 生成 Markdown 报告
        report_filename = f"report_{timestamp}.md"
        report_path = os.path.join(output_dir, report_filename)
        
        lines = []
        
        # 报告头部
        lines.append("# 作品提取报告\n\n")
        lines.append(f"> **提取时间:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        lines.append(f"> **提取模式:** {extraction_level.upper()}\n")
        lines.append(f"> **作品数量:** {len(data_list)}\n")
        lines.append("\n---\n\n")
        
        # 每个作品一个章节
        for i, item in enumerate(data_list, 1):
            if not isinstance(item, dict):
                continue
            
            title = item.get("title", f"作品 {i}")
            title_cn = item.get("title_cn", "")
            year = item.get("year", "")
            
            if title_cn and title_cn != title:
                lines.append(f"## {i}. {title} / {title_cn}\n\n")
            else:
                lines.append(f"## {i}. {title}\n\n")
            
            # 属性列表
            if year:
                lines.append(f"| 年份 | {year} |\n")
            if item.get("category") or item.get("type"):
                lines.append(f"| 类型 | {item.get('category') or item.get('type')} |\n")
            if item.get("video_link"):
                lines.append(f"| 视频 | [{item['video_link']}]({item['video_link']}) |\n")
            if item.get("materials"):
                lines.append(f"| 材料 | {item['materials']} |\n")
            lines.append("\n")
            
            # 描述
            desc_en = item.get("description_en") or item.get("description", "")
            desc_cn = item.get("description_cn", "")
            
            if desc_en or desc_cn:
                lines.append("### Description / 描述\n\n")
                if desc_en:
                    lines.append(f"**English:**\n\n{desc_en}\n\n")
                if desc_cn:
                    lines.append(f"**中文:**\n\n{desc_cn}\n\n")
            
            # 图片（使用本地相对路径）
            images = item.get("high_res_images") or item.get("images") or []
            if images:
                lines.append("### 图片\n\n")
                for img_url in images[:6]:
                    local_rel_path = url_to_local.get(img_url)
                    if local_rel_path:
                        lines.append(f"![]({local_rel_path})\n\n")
                    else:
                        lines.append(f"![]({img_url})\n\n")  # fallback to URL
            
            lines.append("---\n\n")
        
        # 写入文件
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("".join(lines))
        
        logger.info(f"📄 Markdown 报告已生成: {report_path}")
        
        # 同时保存原始 JSON
        json_filename = f"data_{timestamp}.json"
        json_path = os.path.join(output_dir, json_filename)
        
        output_data = {
            "_meta": {
                "prompt": prompt,
                "extraction_level": extraction_level,
                "timestamp": datetime.now().isoformat(),
            },
            **data
        }
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📋 JSON 数据已保存: {json_path}")
    
    def _extract_image_urls(self, data: Dict[str, Any]) -> List[str]:
        """从 Agent 返回数据中提取所有图片 URL"""
        urls = []
        
        # 常见的图片字段名
        image_fields = ['image_urls', 'images', 'image', 'imageUrls', 'imageUrl', 
                       'cover_image', 'thumbnail', 'photos', 'gallery']
        
        def extract_from_value(value):
            if isinstance(value, str):
                if value.startswith(('http://', 'https://')) and any(ext in value.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', 'image']):
                    urls.append(value)
            elif isinstance(value, list):
                for item in value:
                    extract_from_value(item)
            elif isinstance(value, dict):
                for v in value.values():
                    extract_from_value(v)
        
        # 优先检查已知字段
        for field in image_fields:
            if field in data:
                extract_from_value(data[field])
        
        # 递归搜索所有值
        if not urls:
            extract_from_value(data)
        
        return list(set(urls))  # 去重


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
  
  # Agent 模式 + 指定 URL + 图片下载
  python3 aaajiao_scraper.py --agent "Get complete info including images" --urls "https://eventstructure.com/Absurd-Reality-Check" --output-dir ./agent_output
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
        "--discovery-url", "-d",
        type=str,
        help="[New] 使用 Scrape+Agent 模式：先滚动发现 URL，再用 Agent 提取"
    )
    
    parser.add_argument(
        "--scroll-mode",
        choices=["auto", "horizontal", "vertical"],
        default="auto",
        help="Discovery 模式下的滚动策略 (default: auto)"
    )
    
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        metavar="DIR",
        help="Agent 模式下的输出目录（将下载图片并生成 Markdown 报告）"
    )
    
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用缓存，强制重新抓取"
    )
    
    args = parser.parse_args()
    
    scraper = AaajiaoScraper(use_cache=not args.no_cache)
    
    if args.discovery_url:
        # ====================== Discovery Mode ======================
        logger.info(f"🚀 启动混合模式 (Scrape Discovery -> Agent Extraction) [Scroll: {args.scroll_mode}]")
        
        # Phase 1: Discovery
        found_urls = scraper.discover_urls_with_scroll(args.discovery_url, scroll_mode=args.scroll_mode)
        
        if not found_urls:
            logger.error("❌ 未发现任何链接，退出")
            sys.exit(1)
            
        logger.info(f"📋 共发现 {len(found_urls)} 个作品链接")
        
        # 限制数量用于测试 (可选，这里先处理前 5 个避免消耗过多)
        # found_urls = found_urls[:5] 
        # logger.info(f"⚠️  测试模式：仅处理前 5 个链接")
        
        # Phase 2: Agent Extraction
        prompt = args.agent or "Deeply analyze these artworks. Extract title, year, materials, description, concept, and exhibition history."
        # Enhanced Prompt logic
        final_prompt = prompt
        if args.output_dir and "image" not in prompt.lower():
            final_prompt = f"{prompt}. IMPORTANT: For images, extract the 'src_o' attribute (if available) or 'src'. 'src_o' contains the high-res version. Ignore sidebar thumbnails. for each artwork."
        
        logger.info("🤖 提交 Agent 批量处理任务 (这可能需要一些时间)...")
        
        # 传递发现的所有 URL 给 Agent
        # 注意：URL 太多可能会导致 Agent 任务过大，Firecrawl 建议一次处理少量 URL
        # 这里演示原理，实际使用可能需要切片分批处理
        
        result = scraper.agent_search(enhanced_prompt, urls=found_urls, max_credits=args.max_credits)
        
        if result:
            print("\n" + "="*50)
            print("📋 Discovery + Agent 结果:")
            print("="*50)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            if args.output_dir:
                scraper.generate_agent_report(result, args.output_dir, prompt=enhanced_prompt)
        else:
            print("❌ Agent 任务失败")
            sys.exit(1)
            
    elif args.agent:
        # ====================== Standard Agent Mode ======================
        # Agent 模式 - 增强 prompt 以请求图片
        enhanced_prompt = args.agent
        if args.output_dir:
            # 自动添加图片请求到 prompt
            if "image" not in args.agent.lower():
                enhanced_prompt = f"{args.agent}. Also extract all image URLs from the page."
        
        urls = args.urls.split(",") if args.urls else None
        result = scraper.agent_search(enhanced_prompt, urls=urls, max_credits=args.max_credits)
        
        if result:
            print("\n" + "="*50)
            print("📋 Agent 结果:")
            print("="*50)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # 如果指定了输出目录，下载图片并生成报告
            if args.output_dir:
                scraper.generate_agent_report(result, args.output_dir, prompt=enhanced_prompt)
        else:
            print("❌ Agent 查询失败")
            sys.exit(1)
    else:
        # ====================== Standard Scrape Mode ======================
        # 默认模式：抓取所有作品
        scraper.scrape_all()
        scraper.save_to_json()
        scraper.generate_markdown()


if __name__ == "__main__":
    main()