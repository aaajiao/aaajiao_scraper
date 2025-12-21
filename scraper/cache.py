"""
Caching mixin for the aaajiao scraper.

This module provides caching functionality to minimize API calls and improve performance:
- General cache: Basic URL-based caching using pickle
- Sitemap cache: Stores sitemap lastmod timestamps for incremental updates
- Extract cache: Prompt-specific caching for LLM extraction results
- Discovery cache: Caches discovered URLs from scroll operations

All cache files are stored in the CACHE_DIR directory (.cache by default).
"""

import hashlib
import json
import logging
import os
import pickle
import time
from typing import Dict, Optional

from .constants import CACHE_DIR

logger = logging.getLogger(__name__)


class CacheMixin:
    """Mixin providing caching functionality for scraper operations.
    
    This mixin adds various caching methods that can be mixed into the
    main scraper class. Caches are keyed by URL and optionally by additional
    parameters (e.g., prompt for extract, scroll mode for discovery).
    
    All cache methods are prefixed with underscore to indicate they're
    internal utilities.
    """

    # ====================
    # General Cache
    # ====================

    def _get_cache_path(self, url: str) -> str:
        """Generate cache file path for a given URL.
        
        Args:
            url: The URL to generate cache path for.
            
        Returns:
            Absolute path to the cache file.
            
        Note:
            Uses MD5 hash of URL to create a unique filename.
        """
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{url_hash}.pkl")

    def _load_cache(self, url: str) -> Optional[Dict]:
        """Load cached data for a URL.
        
        Args:
            url: The URL whose cache to load.
            
        Returns:
            Cached data dictionary if found and valid, None otherwise.
            
        Note:
            Silently returns None if cache doesn't exist or is corrupted.
        """
        cache_path = self._get_cache_path(url)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
        return None

    def _save_cache(self, url: str, data: Dict) -> None:
        """Save data to cache for a URL.
        
        Args:
            url: The URL to cache data for.
            data: Dictionary of data to cache.
            
        Note:
            Failures are logged at debug level and silently ignored.
        """
        cache_path = self._get_cache_path(url)
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"Cache save failed: {e}")

    # ====================
    # Sitemap Cache
    # ====================

    def _load_sitemap_cache(self) -> Dict[str, str]:
        """Load sitemap lastmod timestamps cache.
        
        Returns:
            Dictionary mapping URLs to their lastmod timestamps.
            Empty dict if cache doesn't exist or is invalid.
            
        Note:
            Used for incremental scraping to detect updated pages.
        """
        cache_path = os.path.join(CACHE_DIR, "sitemap_lastmod.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_sitemap_cache(self, sitemap: Dict[str, str]) -> None:
        """Save sitemap lastmod timestamps cache.
        
        Args:
            sitemap: Dictionary mapping URLs to lastmod timestamps.
            
        Note:
            Errors are logged but don't raise exceptions.
        """
        cache_path = os.path.join(CACHE_DIR, "sitemap_lastmod.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(sitemap, f, indent=2)
        except Exception as e:
            logger.error(f"Sitemap cache save failed: {e}")

    # ====================
    # Extract Cache (V2)
    # ====================

    def _get_extract_cache_path(self, url: str, prompt_hash: str) -> str:
        """Generate cache path for LLM extraction results.
        
        Args:
            url: The URL being extracted.
            prompt_hash: Hash of the extraction prompt.
            
        Returns:
            Absolute path to the extract cache file.
            
        Note:
            Cache is keyed by both URL and prompt to handle different
            extraction modes (quick, full, custom).
        """
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"extract_{url_hash}_{prompt_hash[:8]}.pkl")

    def _load_extract_cache(self, url: str, prompt: str) -> Optional[Dict]:
        """Load cached LLM extraction result.
        
        Args:
            url: The URL whose extraction to load.
            prompt: The extraction prompt used (for cache key).
            
        Returns:
            Cached extraction data if found and valid, None otherwise.
            
        Note:
            Different prompts for the same URL will have separate caches.
        """
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_path = self._get_extract_cache_path(url, prompt_hash)

        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                    return data
            except Exception:
                pass
        return None

    def _save_extract_cache(self, url: str, prompt: str, data: Dict) -> None:
        """Save LLM extraction result to cache.
        
        Args:
            url: The URL being extracted.
            prompt: The extraction prompt used (for cache key).
            data: Extraction result data to cache.
            
        Note:
            Failures are logged at debug level and silently ignored.
        """
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_path = self._get_extract_cache_path(url, prompt_hash)
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"Extract cache save failed: {e}")

    # ====================
    # Discovery Cache
    # ====================

    def _get_discovery_cache_path(self, url: str, scroll_mode: str) -> str:
        """Generate cache path for discovery scroll results.
        
        Args:
            url: The URL being scanned for links.
            scroll_mode: Scroll mode used (auto/slow/custom).
            
        Returns:
            Absolute path to the discovery cache file.
        """
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"discovery_{url_hash}_{scroll_mode}.json")

    def _is_discovery_cache_valid(self, cache_path: str, ttl_hours: int = 24) -> bool:
        """Check if discovery cache is still valid based on TTL.
        
        Args:
            cache_path: Path to the cache file.
            ttl_hours: Time-to-live in hours. Defaults to 24 hours.
            
        Returns:
            True if cache exists and is within TTL, False otherwise.
            
        Note:
            Discovery caches expire after TTL to ensure fresh results
            for dynamic pages.
        """
        if not os.path.exists(cache_path):
            return False
        mtime = os.path.getmtime(cache_path)
        if (time.time() - mtime) > ttl_hours * 3600:
            return False
        return True

