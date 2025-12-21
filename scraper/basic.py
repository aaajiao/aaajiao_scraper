
import logging
from bs4 import BeautifulSoup
from typing import List, Dict

from .constants import BASE_URL, SITEMAP_URL

logger = logging.getLogger(__name__)

class BasicScraperMixin:
    """Basic extraction functionality via Sitemap & HTML"""
    
    def get_all_work_links(self, incremental: bool = False) -> List[str]:
        """
        从 Sitemap 获取所有作品链接
        """
        logger.info(f"正在读取 Sitemap: {SITEMAP_URL}")
        try:
            response = self.session.get(SITEMAP_URL, timeout=self.TIMEOUT)
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
            
    def _fallback_scan_main_page(self) -> List[str]:
        """备用方案：从主页扫描链接"""
        logger.info("尝试扫描主页链接 (备用方案)...")
        try:
            resp = self.session.get(BASE_URL, timeout=self.TIMEOUT)
            soup = BeautifulSoup(resp.content, 'html.parser')
            links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                full_url = href if href.startswith('http') else f"{BASE_URL.rstrip('/')}/{href.lstrip('/')}"
                if self._is_valid_work_link(full_url):
                    links.append(full_url)
            return sorted(list(set(links)))
        except Exception as e:
            logger.error(f"主页扫描失败: {e}")
            return []

    def _is_valid_work_link(self, url: str) -> bool:
        """过滤非作品链接"""
        if not url.startswith(BASE_URL):
            return False
            
        path = url.replace(BASE_URL, '')
        
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
        
        # 排除包含 'tag' 的链接
        if '/tag/' in path:
            return False
            
        return True
