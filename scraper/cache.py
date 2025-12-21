
import os
import pickle
import json
import hashlib
import logging
from typing import Dict, Optional
from .constants import CACHE_DIR

logger = logging.getLogger(__name__)

class CacheMixin:
    """Caching functionalities for Scraper"""
    
    # ==================== General Cache ====================
    def _get_cache_path(self, url: str) -> str:
        """生成缓存文件路径"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{url_hash}.pkl")
    
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
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"缓存保存失败: {e}")

    # ==================== Sitemap Cache ====================
    def _load_sitemap_cache(self) -> Dict[str, str]:
        """加载 sitemap lastmod 缓存"""
        cache_path = os.path.join(CACHE_DIR, "sitemap_lastmod.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_sitemap_cache(self, sitemap: Dict[str, str]):
        """保存 sitemap lastmod 缓存"""
        cache_path = os.path.join(CACHE_DIR, "sitemap_lastmod.json")
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(sitemap, f, indent=2)
        except Exception as e:
            logger.error(f"Sitemap 缓存保存失败: {e}")

    # ==================== Extract Cache (V2) ====================
    def _get_extract_cache_path(self, url: str, prompt_hash: str) -> str:
        """生成 Extract 缓存路径"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"extract_{url_hash}_{prompt_hash[:8]}.pkl")
    
    def _load_extract_cache(self, url: str, prompt: str) -> Optional[Dict]:
        """加载 Extract 缓存"""
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_path = self._get_extract_cache_path(url, prompt_hash)
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    data = pickle.load(f)
                    return data
            except Exception:
                pass
        return None

    def _save_extract_cache(self, url: str, prompt: str, data: Dict):
        """保存 Extract 缓存"""
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_path = self._get_extract_cache_path(url, prompt_hash)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"Extract 缓存保存失败: {e}")
            
    # ==================== Discovery Cache ====================
    def _get_discovery_cache_path(self, url: str, scroll_mode: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"discovery_{url_hash}_{scroll_mode}.json")
        
    def _is_discovery_cache_valid(self, cache_path: str, ttl_hours: int = 24) -> bool:
        if not os.path.exists(cache_path):
            return False
        mtime = os.path.getmtime(cache_path)
        if (time.time() - mtime) > ttl_hours * 3600:
            return False
        return True
