"""
Basic scraper mixin for HTML-based extraction.

This module provides fundamental scraping functionality:
- Sitemap parsing to discover artwork pages
- Incremental scraping based on lastmod timestamps
- HTML link extraction as a fallback mechanism
- URL filtering to identify valid artwork pages

Uses BeautifulSoup for HTML parsing and integrates with the cache system
for incremental updates.
"""

import logging
from typing import Dict, List

from bs4 import BeautifulSoup

from .constants import BASE_URL, SITEMAP_URL, TIMEOUT

logger = logging.getLogger(__name__)


class BasicScraperMixin:
    """Mixin providing basic HTML scraping functionality.
    
    This mixin implements sitemap-based discovery and HTML parsing for
    extracting artwork links. It supports both full and incremental modes
    by comparing sitemap lastmod timestamps.
    
    Attributes:
        session: HTTP session from CoreScraper.
        TIMEOUT: Request timeout from constants.
        
    Note:
        This mixin requires the CacheMixin for incremental functionality.
    """

    def get_all_work_links(self, incremental: bool = False) -> List[str]:
        """Get all artwork links from sitemap with optional incremental mode.
        
        Args:
            incremental: If True, only return URLs that are new or have been
                modified since the last scrape (based on lastmod timestamps).
                If False, return all URLs. Defaults to False.
        
        Returns:
            Sorted list of artwork URLs. In incremental mode, only changed URLs.
            Empty list if sitemap parsing fails and fallback also fails.
            
        Note:
            - In incremental mode, compares current sitemap with cached version
            - Falls back to main page scanning if sitemap is unavailable
            - Automatically caches sitemap data for future incremental runs
            
        Example:
            >>> scraper = AaajiaoScraper()
            >>> # Full scrape
            >>> all_links = scraper.get_all_work_links(incremental=False)
            >>> # Incremental scrape (only new/updated)
            >>> new_links = scraper.get_all_work_links(incremental=True)
        """
        logger.info(f"Reading sitemap: {SITEMAP_URL}")
        try:
            response = self.session.get(SITEMAP_URL, timeout=TIMEOUT)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            # Parse URLs and lastmod timestamps
            current_sitemap: Dict[str, str] = {}  # {url: lastmod}
            raw_urls = soup.find_all("url")
            logger.info(f"Sitemap raw url tags found: {len(raw_urls)}")

            for url_tag in raw_urls:
                loc = url_tag.find("loc")
                lastmod = url_tag.find("lastmod")
                if loc:
                    url = loc.get_text().strip()
                    if self._is_valid_work_link(url):
                        current_sitemap[url] = lastmod.get_text().strip() if lastmod else ""

            logger.info(
                f"Found {len(current_sitemap)} valid artwork links in sitemap "
                f"(filtered from {len(raw_urls)})"
            )

            if not incremental:
                # Full mode: save cache and return all links
                self._save_sitemap_cache(current_sitemap)
                return sorted(list(current_sitemap.keys()))

            # Incremental mode: compare with cache
            cached_sitemap = self._load_sitemap_cache()
            changed_urls: List[str] = []

            for url, lastmod in current_sitemap.items():
                if url not in cached_sitemap:
                    # New URL
                    changed_urls.append(url)
                    logger.info(f"🆕 New: {url}")
                elif lastmod and lastmod != cached_sitemap.get(url, ""):
                    # lastmod changed
                    changed_urls.append(url)
                    logger.info(f"🔄 Updated: {url} ({cached_sitemap.get(url)} → {lastmod})")

            if changed_urls:
                logger.info(f"📊 Incremental detection: {len(changed_urls)} updated/new")
            else:
                logger.info("✅ No updates detected")

            # Save new cache
            self._save_sitemap_cache(current_sitemap)

            return sorted(changed_urls)

        except Exception as e:
            logger.error(f"Sitemap parsing failed: {e}")
            return self._fallback_scan_main_page()

    def _fallback_scan_main_page(self) -> List[str]:
        """Fallback method to scan main page for artwork links.
        
        Used when sitemap is unavailable or parsing fails. Extracts all
        links from the main page and filters them using URL validation.
        
        Returns:
            Sorted list of unique artwork URLs found on main page.
            Empty list if main page scanning fails.
            
        Note:
            This is a less reliable method than sitemap parsing as it
            only discovers links present on the main page at scan time.
        """
        logger.info("Attempting to scan main page (fallback)...")
        try:
            resp = self.session.get(BASE_URL, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.content, "html.parser")
            links: List[str] = []
            
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # Construct absolute URL
                full_url = (
                    href
                    if href.startswith("http")
                    else f"{BASE_URL.rstrip('/')}/{href.lstrip('/')}"
                )
                if self._is_valid_work_link(full_url):
                    links.append(full_url)
                    
            deduped_links = sorted(list(set(links)))
            logger.info(f"Found {len(deduped_links)} unique artwork links on main page")
            return deduped_links
            
        except Exception as e:
            logger.error(f"Main page scanning failed: {e}")
            return []

    def _is_valid_work_link(self, url: str) -> bool:
        """Check if a URL is a valid artwork page link.
        
        Args:
            url: The URL to validate.
            
        Returns:
            True if the URL appears to be an artwork page, False otherwise.
            
        Note:
            Validation rules:
            - Must start with BASE_URL
            - Must not be root path or common non-artwork pages
            - Must not contain '/tag/' (tag archive pages)
            - Uses path length heuristic to filter out navigation pages
            
        Example:
            >>> scraper._is_valid_work_link("https://eventstructure.com/work/title")
            True
            >>> scraper._is_valid_work_link("https://eventstructure.com/about")
            False
        """
        if not url.startswith(BASE_URL):
            return False

        path = url.replace(BASE_URL, "")

        # Exclude common non-artwork paths
        excludes = [
            "/",
            "/rss",
            "/feed",
            "/filter",
            "/aaajiao",
            "/contact",
            "/cv",
            "/about",
            "/index",
            "/sitemap",
        ]

        if path in ["/", ""]:
            return False

        # Check exclusions with length heuristic
        for ex in excludes:
            if ex in path and len(path) < 20:  # Simple heuristic: short paths are likely navigation
                if path == ex or path.startswith(ex + "/"):
                    return False

        # Exclude tag archive pages
        if "/tag/" in path:
            return False

        return True

