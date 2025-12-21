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
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .constants import BASE_URL, CACHE_DIR, SITEMAP_URL, TIMEOUT

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

    def extract_metadata_bs4(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract artwork metadata using local HTML parsing (No API cost).
        
        Attempts to parse the page structure to find title, year, description,
        materials, and category.
        
        Args:
            url: The artwork page URL.
            
        Returns:
            Dictionary with extracted fields if successful, None otherwise.
            Includes 'source': 'local' to indicate origin.
        """
        try:
            logger.info(f"Parsing locally (BS4): {url}")
            resp = self.session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.content, "html.parser")
            
            # --- 1. Title ---
            title_div = soup.find("div", class_="project_title")
            raw_title = title_div.get_text().strip() if title_div else ""
            if not raw_title:
                return None  # Minimum requirement
                
            title = raw_title
            title_cn = ""
            
            # Split "English / Chinese"
            if "/" in raw_title:
                parts = raw_title.split("/", 1)
                title = parts[0].strip()
                title_cn = parts[1].strip()
                
            # --- 2. Content Analysis ---
            content_div = soup.find("div", class_="project_content")
            
            year = ""
            category = ""
            materials = ""
            desc_en = ""
            desc_cn = ""
            
            if content_div:
                # Cleanup
                for s in content_div(["script", "style"]):
                    s.decompose()
                
                # Extract text lines
                text = content_div.get_text(separator="\n")
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                
                # Heuristic Parsing
                import re
                
                # A. Find Year (Priority: Standalone year specific regex)
                for line in lines:
                    # Match 2018 or 2018-2022
                    year_match = re.search(r'\b(20\d{2}(?:\s*[-–]\s*20\d{2})?)\b', line)
                    if year_match:
                        year = year_match.group(1).replace("–", "-") # Normalize en-dash
                        break
                
                # B. Find Category/Materials (Short lines with / or english/chinese mix)
                # This is tricky without NLP, so we look for short lines that aren't the year
                candidates = [l for l in lines if len(l) < 100 and l != year]
                
                # Heuristic: Category often comes early
                if candidates:
                    # Try to guess based on keywords
                    common_cats = ["Video", "Installation", "Website", "Software", "Print", "Data", "Performance", "装置", "录像"]
                    for line in candidates:
                        if any(c.lower() in line.lower() for c in common_cats):
                            category = line
                            break
                            
                # C. Descriptions (Longer lines)
                long_lines = [l for l in lines if len(l) > 100]
                if long_lines:
                    # Determine language by character checking
                    for line in long_lines:
                        # Simple check for Chinese characters
                        if any('\u4e00' <= char <= '\u9fff' for char in line):
                            desc_cn += line + "\n\n"
                        else:
                            desc_en += line + "\n\n"
                            
            # --- 3. Images ---
            images = self.extract_images_from_page(url)
            
            return {
                "url": url,
                "title": title,
                "title_cn": title_cn,
                "year": year,
                "category": category,
                "materials": materials,  # Hard to separate from category without LLM
                "description_en": desc_en.strip(),
                "description_cn": desc_cn.strip(),
                "images": images,
                "high_res_images": images, # Alias for compatibility
                "source": "local",  # Marker for UI
                "video_link": "", # Hard to extract without JS sometimes
            }
            
        except Exception as e:
            logger.warning(f"Local metadata extraction failed: {e}")
            return None

    # ====================
    # Image Extraction (HTML-based, no API)
    # ====================

    def extract_images_from_page(self, url: str) -> List[str]:
        """Extract high-resolution image URLs from an artwork page.
        
        Uses HTML parsing to find images specific to this artwork by targeting
        the slideshow container associated with the active project.
        
        Args:
            url: The artwork page URL to extract images from.
            
        Returns:
            List of image URLs (preferring src_o for high resolution).
            Empty list if extraction fails or no images found.
            
        Note:
            - Targets `slideshow_container_{ID}` to avoid extracting images
              from other works visible on the page
            - Prefers `src_o` attribute for high-res, falls back to `data-src` or `src`
            - Filters out thumbnails and navigation images
        """
        try:
            logger.debug(f"Extracting images from: {url}")
            resp = self.session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            
            images: List[str] = []
            
            # Strategy 1: Find active project's slideshow container
            # Look for project_thumb with 'active' class to get the project ID
            active_thumb = soup.find(class_=re.compile(r"project_thumb.*active"))
            
            if active_thumb and active_thumb.get("id"):
                # Extract numeric ID from "item_12345678"
                item_id = active_thumb.get("id", "").replace("item_", "")
                
                if item_id:
                    # Find the corresponding slideshow container
                    container = soup.find(id=re.compile(f"slideshow_container_{item_id}"))
                    
                    if container:
                        for img in container.find_all("img"):
                            src = self._get_best_image_src(img)
                            if src and self._is_valid_image(src):
                                full_url = urljoin(url, src)
                                if full_url not in images:
                                    images.append(full_url)
                        
                        if images:
                            logger.debug(f"Found {len(images)} images in slideshow container")
                            return images
            
            # Strategy 2: Fallback - find main content images
            # Look for images in common content containers
            content_selectors = [
                ".project_content",
                ".slide_content", 
                ".content_inner",
                "article",
                "main"
            ]
            
            for selector in content_selectors:
                container = soup.select_one(selector)
                if container:
                    for img in container.find_all("img"):
                        src = self._get_best_image_src(img)
                        if src and self._is_valid_image(src):
                            full_url = urljoin(url, src)
                            if full_url not in images:
                                images.append(full_url)
            
            # Strategy 3: Last resort - all images with src_o attribute
            if not images:
                for img in soup.find_all("img", attrs={"src_o": True}):
                    src = img.get("src_o")
                    if src and self._is_valid_image(src):
                        full_url = urljoin(url, src)
                        if full_url not in images:
                            images.append(full_url)
            
            logger.debug(f"Found {len(images)} images (fallback strategies)")
            return images
            
        except Exception as e:
            logger.error(f"Image extraction failed for {url}: {e}")
            return []

    def _get_best_image_src(self, img_tag) -> Optional[str]:
        """Get the best available image source from an img tag.
        
        Priority: src_o (high-res) > data-src (lazy load) > src
        """
        return (
            img_tag.get("src_o") or 
            img_tag.get("data-src") or 
            img_tag.get("src")
        )

    def _is_valid_image(self, src: str) -> bool:
        """Check if an image URL is valid (not a thumbnail or icon)."""
        if not src:
            return False
        
        # Skip common non-artwork images
        skip_patterns = [
            "thumbnail",
            "thumb_",
            "icon",
            "logo",
            "avatar",
            "placeholder",
            "loading",
            "spinner",
            "/assets/",
            "1x1.gif",
            "blank.gif"
        ]
        
        src_lower = src.lower()
        for pattern in skip_patterns:
            if pattern in src_lower:
                return False
        
        # Must be an actual image file
        valid_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif")
        if not any(src_lower.endswith(ext) or ext + "?" in src_lower for ext in valid_extensions):
            # Check if URL contains image-like patterns
            if "image" not in src_lower and "img" not in src_lower and "photo" not in src_lower:
                return False
        
        return True

    def download_image(self, url: str, output_dir: str, filename: Optional[str] = None) -> Optional[str]:
        """Download a single image to the specified directory.
        
        Args:
            url: Image URL to download.
            output_dir: Directory to save the image to.
            filename: Optional custom filename. If None, extracts from URL.
            
        Returns:
            Local file path if successful, None otherwise.
        """
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate filename from URL if not provided
            if not filename:
                filename = url.split("/")[-1].split("?")[0]
                # Ensure valid filename
                filename = re.sub(r'[^\w\-_\.]', '_', filename)
                if not filename or len(filename) < 4:
                    filename = f"image_{hash(url) % 10000}.jpg"
            
            local_path = os.path.join(output_dir, filename)
            
            # Skip if already exists
            if os.path.exists(local_path):
                logger.debug(f"Image already exists: {filename}")
                return local_path
            
            # Download
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            
            with open(local_path, "wb") as f:
                f.write(resp.content)
            
            logger.debug(f"Downloaded: {filename}")
            return local_path
            
        except Exception as e:
            logger.warning(f"Failed to download {url}: {e}")
            return None

    def get_all_cached_works(self) -> List[Dict[str, Any]]:
        """Load all cached work data from the cache directory.
        
        Returns:
            List of cached work dictionaries, each containing metadata
            like title, url, year, etc.
        """
        import pickle
        
        works: List[Dict[str, Any]] = []
        
        if not os.path.exists(CACHE_DIR):
            logger.warning(f"Cache directory not found: {CACHE_DIR}")
            return works
        
        for filename in os.listdir(CACHE_DIR):
            # Only load basic cache files (not extract or discovery caches)
            if filename.endswith(".pkl") and not filename.startswith(("extract_", "discovery_")):
                cache_path = os.path.join(CACHE_DIR, filename)
                try:
                    with open(cache_path, "rb") as f:
                        data = pickle.load(f)
                        if isinstance(data, dict) and data.get("url"):
                            works.append(data)
                except Exception as e:
                    logger.debug(f"Failed to load cache {filename}: {e}")
        
        logger.info(f"Loaded {len(works)} cached works")
        return works

    def enrich_work_with_images(self, work: Dict[str, Any], output_dir: str = "output") -> Dict[str, Any]:
        """Enrich a work entry with local images (Download Strategy).
        
        Logic:
        1. If work has 'images' (URLs), iterate and download them.
        2. If work has NO 'images', fallback to extracting from HTML, then download.
        3. Save downloaded paths to 'local_images'.
        
        Args:
            work: Work dictionary to enrich.
            output_dir: Base directory for output.
            
        Returns:
            Updated work dictionary with 'local_images' populated.
        """
        url = work.get("url")
        if not url:
            return work
            
        # Determine image list source
        existing_urls = work.get("images", [])
        if not existing_urls:
            # Fallback: Extract from HTML if no URLs exist
            logger.info(f"No existing images for {work.get('title')}, scraping from HTML...")
            existing_urls = self.extract_images_from_page(url)
            # Update work with newly found URLs to persist them
            work["images"] = existing_urls
            
        if not existing_urls:
            logger.debug(f"No images found for {url}")
            return work

        # Prepare storage
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in work.get("title", "untitled"))[:50]
        work_images_dir = os.path.join(output_dir, "images", safe_title)
        os.makedirs(work_images_dir, exist_ok=True)
        
        local_images = []
        
        # Download Loop
        for i, img_url in enumerate(existing_urls):
            try:
                # Extension
                parsed = urlparse(img_url)
                ext = os.path.splitext(parsed.path)[1]
                if not ext:
                    ext = ".jpg"
                    
                filename = f"{i+1:02d}{ext}"
                saved_path = self.download_image(img_url, work_images_dir, filename)
                
                if saved_path:
                    # Store absolute path for consistency, report generator handles relative
                    local_images.append(os.path.abspath(saved_path))
            except Exception as e:
                logger.warning(f"Failed to download image {img_url}: {e}")
                
        # Update work
        work["local_images"] = local_images
        return work
