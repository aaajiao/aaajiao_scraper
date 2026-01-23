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

from .constants import (
    BASE_URL, CACHE_DIR, SITEMAP_URL, TIMEOUT,
    MATERIAL_KEYWORDS, CREDITS_PATTERNS, TYPE_KEYWORDS,
    CANONICAL_TYPES, TYPE_POLLUTANTS,
)

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

    def _split_bilingual_title(self, raw_title: str) -> Tuple[str, str]:
        """Split 'English / 中文' format title with Chinese validation.

        Args:
            raw_title: Raw title string that may contain bilingual format.

        Returns:
            Tuple of (english_title, chinese_title). Chinese title may be empty.
        """
        if "/" not in raw_title:
            return raw_title, ""

        parts = raw_title.split("/", 1)
        en_part = parts[0].strip()
        cn_part = parts[1].strip() if len(parts) > 1 else ""

        # Verify cn_part contains Chinese characters
        if cn_part and any('\u4e00' <= c <= '\u9fff' for c in cn_part):
            return en_part, cn_part

        # No Chinese chars found, return original title
        return raw_title, ""

    def _extract_video_link(self, soup) -> str:
        """Extract video link (Vimeo, YouTube, Bilibili) from page.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            Video URL string, or empty string if not found.
        """
        video_domains = ["vimeo.com", "youtube.com", "youtu.be", "bilibili.com"]

        # 1. Direct links in <a href>
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(domain in href for domain in video_domains):
                return href

        # 2. iframe src
        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"]
            if any(domain in src for domain in video_domains):
                return src

        # 3. data-vimeo-id attribute
        for elem in soup.find_all(attrs={"data-vimeo-id": True}):
            vid = elem["data-vimeo-id"]
            return f"https://vimeo.com/{vid}"

        return ""

    def extract_metadata_bs4(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract artwork metadata using local HTML parsing (No API cost).

        Attempts to parse the page structure to find title, year, description,
        materials, and type.

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

            # Try to split from project_title first
            title, title_cn = self._split_bilingual_title(raw_title)

            # --- 2. Extract type from "Filed under" tags (most reliable source) ---
            work_type = ""
            tags_span = soup.find("span", class_="tags")
            if tags_span:
                # Find type links like: <a href=".../filter/installation">installation</a>
                for a in tags_span.find_all("a", href=True):
                    href = a.get("href", "")
                    # Skip year links (e.g., /filter/2013)
                    if "/filter/" in href and not href.split("/")[-1].isdigit():
                        tag_text = a.get_text().strip().lower()
                        # Check if it's a known type
                        if tag_text in CANONICAL_TYPES:
                            work_type = CANONICAL_TYPES[tag_text]
                            break
                        # Also check TYPE_KEYWORDS
                        for kw in TYPE_KEYWORDS:
                            if kw.lower() in tag_text:
                                work_type = tag_text.title()
                                break
                        if work_type:
                            break

            # --- 3. Content Analysis ---
            content_div = soup.find("div", class_="project_content")

            year = ""
            materials = ""
            size = ""
            duration = ""
            video_link = ""
            credits = ""
            desc_en = ""
            desc_cn = ""

            if content_div:
                # Cleanup
                for s in content_div(["script", "style"]):
                    s.decompose()

                # Extract text lines
                import re  # Move import here for preprocessing
                text = content_div.get_text(separator="\n")
                raw_lines = [line.strip() for line in text.split("\n") if line.strip()]

                # === Preprocessing: Filter out interference lines ===
                skip_patterns = [
                    r'^Previous$',
                    r'^Next',
                    r'^\(?(\d+)\s+of\s+(\d+)\)?$',
                    r'^Fullscreen$',
                    r'^\.vimeo$',
                    r'^\.youku$',
                    r'^\.pdf$',
                    r'^\.video$',
                    r'^https?://',
                    r'^\d{5}\s+\w+',  # Postal code address
                    r'^Schöneberger|^Berlin|^Tiergarten',  # Address fragments
                ]
                lines = []
                for line in raw_lines:
                    if not any(re.match(p, line, re.IGNORECASE) for p in skip_patterns):
                        lines.append(line)

                # Heuristic Parsing

                # A0. Try to get bilingual title from content (format: "Title / 中文标题")
                if not title_cn:
                    for line in lines[:10]:  # Check first 10 lines
                        if "/" in line and title.lower() in line.lower():
                            _, cn = self._split_bilingual_title(line)
                            if cn:
                                title_cn = cn
                                break

                # A. Find Year (Priority: Standalone year specific regex)
                for line in lines:
                    # Match 2018 or 2018-2022
                    year_match = re.search(r'\b(20\d{2}(?:\s*[-–]\s*20\d{2})?)\b', line)
                    if year_match:
                        year = year_match.group(1).replace("–", "-") # Normalize en-dash
                        break

                # B. Find Category/Materials (Short lines with / or english/chinese mix)
                # This is tricky without NLP, so we look for short lines that aren't the year
                candidates = [l for l in lines if len(l) < 150 and l != year]

                # Use shared constants from constants.py
                # CREDITS_PATTERNS, MATERIAL_KEYWORDS, TYPE_KEYWORDS are imported at module level

                # Helper function: check if line is credits
                def is_credits_line(line: str) -> bool:
                    line_lower = line.lower().strip()
                    for pattern in CREDITS_PATTERNS:
                        if re.match(pattern, line_lower, re.IGNORECASE):
                            return True
                    return False

                # Helper function: check if line contains material keywords
                def has_MATERIAL_KEYWORDS(line: str) -> bool:
                    line_lower = line.lower()
                    return any(kw.lower() in line_lower for kw in MATERIAL_KEYWORDS)

                # Helper function: check if line is bilingual format (contains / separator with Chinese)
                def is_bilingual_line(line: str) -> bool:
                    if '/' not in line and '／' not in line:
                        return False
                    # Check if line has both English and Chinese characters
                    has_english = any(c.isalpha() and ord(c) < 128 for c in line)
                    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in line)
                    return has_english and has_chinese

                # Helper function: check if line contains type keywords
                def has_TYPE_KEYWORDS(line: str) -> bool:
                    line_lower = line.lower()
                    # Exclude size-related lines (common false positives)
                    size_indicators = ['variable size', '尺寸可变', 'dimension variable',
                                       'dimensions variable', 'variable media']
                    if any(x in line_lower for x in size_indicators):
                        return False
                    # Exclude lines that contain artist name (likely description/label format)
                    if 'aaajiao' in line_lower or '徐文恺' in line:
                        return False
                    # Exclude lines with colon followed by descriptive text (e.g., "cloud.data: Soothing iPad...")
                    # but allow "Video / 录像" format
                    if ':' in line and not re.match(r'^[A-Za-z]+:', line_lower):
                        # Has colon but doesn't start with a role pattern like "Photo:"
                        colon_pos = line.find(':')
                        after_colon = line[colon_pos+1:].strip()
                        # If text after colon is long, it's likely a description
                        if len(after_colon) > 30:
                            return False
                    # Exclude lines that look like descriptions (start with verb or article)
                    desc_starters = ['weigh', 'the ', 'invite', 'prep', '准备', '每周', '使用', '神秘']
                    if any(line_lower.startswith(s) for s in desc_starters):
                        return False
                    # Length limit: 80 for regular lines, 150 for bilingual lines
                    max_len = 150 if is_bilingual_line(line) else 80
                    if len(line) > max_len:
                        return False
                    # Must contain type keyword
                    if not any(kw.lower() in line_lower for kw in TYPE_KEYWORDS):
                        return False
                    # Type keyword should appear at the START of the line (first word or after punctuation)
                    # This is stricter to avoid matching descriptions that happen to contain a type word
                    for kw in TYPE_KEYWORDS:
                        kw_lower = kw.lower()
                        # Check if line starts with the keyword (allowing for leading whitespace)
                        if line_lower.strip().startswith(kw_lower):
                            return True
                        # Check if keyword appears after a slash (bilingual format like "Video / 视频")
                        if '/' in line_lower:
                            parts = line_lower.split('/')
                            for part in parts:
                                if part.strip().startswith(kw_lower):
                                    return True
                    return False

                # Helper function: check if line is a valid materials line
                def is_valid_materials_line(line: str, check_title: bool = True) -> bool:
                    # Length limit: 80 for regular lines, 150 for bilingual lines
                    max_len = 150 if is_bilingual_line(line) else 80
                    if len(line) > max_len:
                        return False
                    # Must have list separators (materials are listed, not described)
                    if not any(sep in line for sep in [',', '/', '、', '，']):
                        return False
                    # Exclude lines starting with common sentence starters
                    first_word = line.split()[0].lower() if line.split() else ''
                    sentence_starters = ['the', 'for', 'in', 'a', 'an', 'this', 'it', 'was', 'is', 'are']
                    if first_word in sentence_starters:
                        return False
                    # Exclude lines that look like type lines
                    if has_TYPE_KEYWORDS(line):
                        return False
                    # Exclude lines that are just year
                    if re.match(r'^20\d{2}(?:\s*[-–]\s*20\d{2})?$', line.strip()):
                        return False
                    # Exclude size-only lines
                    if re.match(r'^\d+\s*[×xX]\s*\d+(?:\s*[×xX]\s*\d+)?\s*(?:cm|mm|m)?$', line.strip(), re.IGNORECASE):
                        return False
                    # Exclude dimension variable lines
                    if 'dimension' in line.lower() and 'variable' in line.lower():
                        return False
                    if '尺寸可变' in line:
                        return False
                    # Exclude lines that match or contain the title (bilingual title line)
                    if check_title and title:
                        title_lower = title.lower().strip()
                        line_lower = line.lower().strip()
                        # Check if line starts with title or title is contained in line
                        if line_lower.startswith(title_lower) or title_lower in line_lower:
                            return False
                        # Also check title_cn
                        if title_cn:
                            if title_cn in line:
                                return False
                    # Exclude very short lines (likely not materials)
                    if len(line) < 10:
                        return False
                    # Exclude lines containing URLs
                    if 'http://' in line.lower() or 'https://' in line.lower() or 'www.' in line.lower():
                        return False
                    # Exclude lines that match credits patterns
                    if is_credits_line(line):
                        return False
                    # Exclude lines that look like event info (Opening, Feb, date patterns)
                    if re.search(r'\b(Opening|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Jan)\b', line, re.IGNORECASE):
                        if re.search(r'\d{1,2}[.,]\s*\d{4}', line):  # Date pattern like "21, 2014"
                            return False
                    # Exclude lines that look like addresses/venue info
                    address_keywords = ['venue', 'unit', 'no.', 'road', 'street', 'avenue', 'building',
                                        'floor', 'museum', 'gallery', 'center', 'centre']
                    line_lower = line.lower()
                    if sum(1 for kw in address_keywords if kw in line_lower) >= 2:
                        return False
                    # Exclude lines that are pure Chinese descriptions (no separators creating a list)
                    chinese_chars = sum(1 for c in line if '\u4e00' <= c <= '\u9fff')
                    if chinese_chars > 20 and chinese_chars / len(line) > 0.7:
                        # Mostly Chinese, likely a description
                        return False
                    # Check for material keywords (relaxed: only need one match)
                    if has_MATERIAL_KEYWORDS(line):
                        return True
                    # Fallback: accept lines with multiple comma-separated items that look like a list
                    # (e.g., "silicone, fiberglass, artificial hair, clothing, seat")
                    parts = re.split(r'[,，、/]', line)
                    if len(parts) >= 3:
                        # Multiple items, likely a materials list
                        # Check it's not a description (no verbs, articles at start of parts)
                        desc_words = ['the', 'a', 'an', 'is', 'are', 'was', 'were', 'has', 'have', 'and']
                        for part in parts[:2]:
                            part_lower = part.strip().lower()
                            if part_lower.split()[0] in desc_words if part_lower.split() else False:
                                return False
                        return True
                    return False

                # Process candidates with position-aware logic
                # Step 1: Find type line first (it's the anchor for materials)
                # Only if type wasn't already found from tags
                type_line_idx = -1
                type_from_tags = bool(work_type)  # Remember if type came from tags
                for idx, line in enumerate(candidates):
                    if has_TYPE_KEYWORDS(line):
                        for kw in TYPE_KEYWORDS:
                            if kw.lower() in line.lower()[:30]:
                                # Only override if we didn't get type from tags
                                if not type_from_tags:
                                    work_type = line
                                type_line_idx = idx
                                break
                        if type_line_idx >= 0:
                            break

                # Step 2: Find materials - check lines AFTER type line first (position-based)
                if type_line_idx >= 0 and not materials:
                    # Look at lines immediately after type (typical structure)
                    for offset in range(1, 4):  # Check next 3 lines
                        next_idx = type_line_idx + offset
                        if next_idx < len(candidates):
                            next_line = candidates[next_idx]
                            # Skip if it's size, year, or dimension variable
                            if re.match(r'^\d+\s*[×xX]\s*\d+', next_line):
                                continue
                            if re.match(r'^20\d{2}(?:\s*[-–]\s*20\d{2})?$', next_line.strip()):
                                continue
                            if 'dimension' in next_line.lower() and 'variable' in next_line.lower():
                                continue
                            if '尺寸可变' in next_line:
                                continue
                            # Check if it looks like materials (has separators, reasonable length)
                            if is_valid_materials_line(next_line):
                                materials = next_line
                                break

                # Step 3: Fallback - scan all candidates for materials and credits
                for line in candidates:
                    if work_type and materials and credits:
                        break

                    # Check credits
                    if not credits and is_credits_line(line):
                        credits = line
                        continue

                    # Fallback materials detection (if position-based failed)
                    if not materials and is_valid_materials_line(line):
                        if not is_credits_line(line):
                            materials = line
                            continue

                # B2. Find Size (尺寸)
                size_patterns = [
                    r'(Dimension[s]?\s+variable\s*/?\s*尺寸可变)',
                    r'(Dimension[s]?\s+variable)',
                    r'(尺寸可变)',
                    # Match: 180cm x 130 cm, 180 x 180 cm, 180×180×50cm
                    r'(\d+\s*(?:cm|mm|m)?\s*[×xX]\s*\d+\s*(?:cm|mm|m)?(?:\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)?)',
                ]
                for line in candidates:
                    if size:
                        break
                    for pattern in size_patterns:
                        match = re.search(pattern, line, re.IGNORECASE)
                        if match:
                            size = match.group(1).strip()
                            break

                # B3. Find Duration (时长) for video works
                # Unicode quotes: ' (\u2018), ' (\u2019), ′ (\u2032), " (\u201c\u201d)
                duration_patterns = [
                    r"(\d+['\u2018\u2019\u2032′']\d+['\u2018\u2019\u2032′''\"]{1,2})",  # 12'00''
                    r"^(\d+['\u2018\u2019\u2032′''\"]+)$",  # 单独一行的 12'
                    r"(\d+:\d+(?::\d+)?)",           # 4:30 或 1:23:45
                    r"(\d+\s*(?:min|minutes?|sec|seconds?))",  # 10 min
                ]
                for line in candidates:
                    if duration:
                        break
                    for pattern in duration_patterns:
                        match = re.search(pattern, line, re.IGNORECASE)
                        if match:
                            duration = match.group(1).strip()
                            break

                # B4. Extract and remove duration embedded in type field
                # E.g., "Single channel video, color,sound,15 minutes and 30 seconds"
                # Or: "6′00″ Video or Live performance"
                # Or: "video 4'4''" (quote-style in the middle)
                # Always clean type even if duration already found elsewhere
                if work_type:
                    # Pattern 1: Quote-style duration at start (6'00" or 15′00″)
                    duration_at_start = re.match(
                        r"^(\d+['\u2018\u2019\u2032′'\"]{1,2}\d*['\u2018\u2019\u2032′''\"]*)\s*(.*)$",
                        work_type
                    )
                    if duration_at_start:
                        # Only set duration if not already found
                        if not duration:
                            duration = duration_at_start.group(1).strip()
                        # Always clean remaining type, remove leading quotes/punctuation
                        remaining = duration_at_start.group(2).strip()
                        work_type = remaining.lstrip('"\'"′″\u201c\u201d\u2018\u2019 ')
                    else:
                        # Pattern 2: Quote-style duration in the middle/end (video 4'4'')
                        duration_quote_style = re.search(
                            r"\s+(\d+['\u2018\u2019\u2032′'\"]{1,2}\d*['\u2018\u2019\u2032′''\"]*)\s*$",
                            work_type
                        )
                        if duration_quote_style:
                            # Only set duration if not already found
                            if not duration:
                                duration = duration_quote_style.group(1).strip()
                            # Always clean up type by removing the duration part
                            work_type = re.sub(
                                r"\s+\d+['\u2018\u2019\u2032′'\"]{1,2}\d*['\u2018\u2019\u2032′''\"]*\s*$",
                                '',
                                work_type
                            ).strip()
                        else:
                            # Pattern 3: minutes/seconds embedded in type
                            duration_in_type = re.search(
                                r',?\s*(\d+\s*(?:min(?:utes?)?|seconds?)[^,]*)',
                                work_type,
                                re.IGNORECASE
                            )
                            if duration_in_type:
                                # Only set duration if not already found
                                if not duration:
                                    duration = duration_in_type.group(1).strip()
                                # Always clean up type by removing the duration part
                                work_type = re.sub(
                                    r',?\s*\d+\s*(?:min(?:utes?)?|seconds?)[^,]*',
                                    '',
                                    work_type,
                                    flags=re.IGNORECASE
                                ).strip().rstrip(',')

                # B5. Extract and remove size embedded in type field
                # E.g., "installation / 装置 76cm × 30cm × 280cm"
                # Always clean type even if size already found elsewhere
                if work_type:
                    size_in_type = re.search(
                        r'(\d+\s*(?:cm|mm|m)?\s*[×xX]\s*\d+\s*(?:cm|mm|m)?(?:\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)?)',
                        work_type
                    )
                    if size_in_type:
                        # Only set size if not already found
                        if not size:
                            size = size_in_type.group(1).strip()
                        # Always clean up type by removing the size part
                        work_type = re.sub(
                            r'\s*\d+\s*(?:cm|mm|m)?\s*[×xX]\s*\d+\s*(?:cm|mm|m)?(?:\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)?',
                            '',
                            work_type
                        ).strip().rstrip(',').rstrip('/').strip()

                # B6. Remove year range embedded in type field
                # E.g., "Single channel video, color,sound, 2017 – 2018,"
                if work_type:
                    work_type = re.sub(
                        r',?\s*20\d{2}\s*[-–]\s*20\d{2}\s*,?',
                        '',
                        work_type
                    ).strip().rstrip(',').strip()

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

            # --- 4. Video Link ---
            video_link = self._extract_video_link(soup)

            # --- 5. Normalize type and extract embedded materials ---
            if work_type:
                normalized_type, type_materials = normalize_type(work_type)
                work_type = normalized_type
                # If we extracted materials from type field and don't have materials yet
                if type_materials and not materials:
                    materials = type_materials

            return {
                "url": url,
                "title": title,
                "title_cn": title_cn,
                "year": year,
                "type": work_type,
                "materials": materials,
                "size": size,
                "duration": duration,
                "credits": credits,
                "description_en": desc_en.strip(),
                "description_cn": desc_cn.strip(),
                "images": images,
                "high_res_images": images,  # Alias for compatibility
                "source": "local",  # Marker for UI
                "video_link": video_link,
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


# ====================
# Utility Functions (Module-level)
# ====================

# Types to exclude (exhibitions, catalogs)
EXCLUDED_TYPES = ['exhibition', 'catalog']


def is_artwork(data: Dict[str, Any]) -> bool:
    """Check if the data represents an artwork (not an exhibition or catalog).

    Args:
        data: Dictionary containing work metadata with 'type' or 'category' field.

    Returns:
        True if the data is an artwork, False if it's an exhibition or catalog.

    Example:
        >>> is_artwork({'type': 'Installation'})
        True
        >>> is_artwork({'type': 'Exhibition'})
        False
    """
    type_val = (data.get('type') or data.get('category') or '').lower()
    return not any(excluded in type_val for excluded in EXCLUDED_TYPES)


def normalize_year(year_str: str) -> str:
    """Normalize year string to standard format (YYYY or YYYY-YYYY).

    Handles various date formats commonly found in exhibition dates and converts
    them to a simple year or year range format.

    Args:
        year_str: Raw year string that may contain month names, date ranges, etc.

    Returns:
        Normalized year string in format 'YYYY' or 'YYYY-YYYY'.
        Returns original string if no years found.

    Examples:
        >>> normalize_year('April 26, 2024 — May 25, 2024')
        '2024'
        >>> normalize_year('September 2019')
        '2019'
        >>> normalize_year('2018-2021')
        '2018-2021'
        >>> normalize_year('2018 - 2022')
        '2018-2022'
    """
    if not year_str:
        return year_str

    # Find all 4-digit years (1900-2099)
    years = re.findall(r'\b(19\d{2}|20\d{2})\b', year_str)

    if not years:
        return year_str

    # Remove duplicates while preserving order
    unique_years = list(dict.fromkeys(years))

    if len(unique_years) == 1:
        return unique_years[0]

    # Return first and last year as range
    return f"{unique_years[0]}-{unique_years[-1]}"


def normalize_type(type_str: str) -> tuple:
    """Normalize type string and extract materials if mixed.

    Contemporary art type fields often contain mixed information:
    - "Single channel video, color, projector, player" -> type + format + equipment
    - "Screen printing, chevron board, metal frame" -> technique + materials

    This function separates them properly.

    Args:
        type_str: Raw type string that may contain mixed info.

    Returns:
        Tuple of (normalized_type, extracted_materials):
        - normalized_type: Clean canonical type string
        - extracted_materials: Equipment/materials found in type field (or empty string)

    Examples:
        >>> normalize_type('installation / 装置')
        ('Installation', '')
        >>> normalize_type('Single channel video, color, projector, player')
        ('Single Channel Video', 'projector, player')
        >>> normalize_type('Screen printing, chevron board, metal frame')
        ('Screen Print', 'chevron board, metal frame')
    """
    if not type_str:
        return ('', '')

    type_str = type_str.strip()
    type_lower = type_str.lower()

    # Step 1: Try direct canonical mapping
    for key, canonical in CANONICAL_TYPES.items():
        if type_lower == key or type_lower.replace(' ', '') == key.replace(' ', ''):
            return (canonical, '')

    # Step 2: Check if type is polluted (contains equipment/materials)
    has_pollutants = any(p in type_lower for p in TYPE_POLLUTANTS)

    if not has_pollutants and len(type_str) < 50:
        # Clean short type, try to match prefix
        for key, canonical in CANONICAL_TYPES.items():
            if type_lower.startswith(key) or key in type_lower:
                return (canonical, '')
        # No match, return as-is (might be a valid type we don't know)
        return (type_str, '')

    # Step 3: Type is polluted - split and extract
    # Split by common separators
    parts = re.split(r'[,;/，；]', type_str)

    clean_type_parts = []
    material_parts = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        part_lower = part.lower()

        # Check if this part is a type keyword
        is_type_part = False
        for key in CANONICAL_TYPES.keys():
            if key in part_lower:
                is_type_part = True
                # Get canonical form
                for k, v in CANONICAL_TYPES.items():
                    if k in part_lower:
                        clean_type_parts.append(v)
                        break
                break

        if not is_type_part:
            # Check if it's a format descriptor (color, sound) - keep with type
            format_words = ['color', 'colour', '彩色', 'sound', '有声', 'silent', '无声']
            if any(fw in part_lower for fw in format_words):
                continue  # Skip format descriptors

            # Check if it's a pollutant (equipment/material)
            if any(p in part_lower for p in TYPE_POLLUTANTS):
                material_parts.append(part)
            elif len(part) > 3:  # Likely material if not recognized
                material_parts.append(part)

    # Build result
    if clean_type_parts:
        # Deduplicate while preserving order
        seen = set()
        unique_types = []
        for t in clean_type_parts:
            if t not in seen:
                seen.add(t)
                unique_types.append(t)
        normalized_type = ' / '.join(unique_types)
    else:
        # Fallback: use first part as type
        normalized_type = parts[0].strip() if parts else type_str

    extracted_materials = ', '.join(material_parts) if material_parts else ''

    return (normalized_type, extracted_materials)


def parse_size_duration(text: str) -> Dict[str, str]:
    """Extract size and duration from text using regex patterns.

    Args:
        text: Text content (usually markdown or plain text from a page).

    Returns:
        Dictionary with 'size' and 'duration' keys (may be empty strings).

    Example:
        >>> parse_size_duration('Installation 180 x 180 cm, video 4\\'30\\'\\'')
        {'size': '180 x 180 cm', 'duration': "4'30''"}
    """
    result = {"size": "", "duration": ""}

    if not text:
        return result

    # Process line by line for better accuracy
    lines = text[:3000].split('\n')  # Limit to first 3000 chars

    # Size patterns (from most specific to general)
    size_patterns = [
        r'[Ss]ize\s+(\d+\s*[×xX]\s*\d+(?:\s*[×xX]\s*\d+)?\s*(?:cm|mm|m)?)',
        r'(\d+\s*[×xX]\s*\d+\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)',  # 3D dimensions
        r'(\d+\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)',  # 2D dimensions
        r'(Dimension[s]?\s+variable\s*/\s*尺寸可变)',
        r'(Dimension[s]?\s+variable)',
        r'^(尺寸可变)$',
    ]

    # Duration patterns (include Unicode quotes: ' \u2018, ' \u2019, ′ \u2032)
    duration_patterns = [
        r"(\d+['\u2018\u2019\u2032′']\d+['\u2018\u2019\u2032′''\"]+)",  # 4'30''
        r"(\d+['\u2018\u2019\u2032′''\"]+)",  # 4' or 4''
        r"video\s+(\d+['\u2018\u2019\u2032′''\"]+)",
        r"(\d+:\d+(?::\d+)?)",  # 4:30 or 1:23:45
        r"(\d+\s*(?:min|minutes?|sec|seconds?))",  # 10 min
    ]

    for line in lines:
        line = line.strip()

        # Find size
        if not result["size"]:
            for pattern in size_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    result["size"] = match.group(1).strip()
                    break

        # Find duration
        if not result["duration"]:
            for pattern in duration_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    result["duration"] = match.group(1).strip()
                    break

        # Early exit if both found
        if result["size"] and result["duration"]:
            break

    return result


def is_extraction_complete(data: Dict[str, Any], strict_materials: bool = False) -> bool:
    """Check if extracted data has all essential fields.

    Used to determine whether to proceed to more expensive extraction methods.

    Args:
        data: Dictionary with extracted work metadata.
        strict_materials: If True, require materials for physical artworks
            (installation, sculpture, print, object). Defaults to False.

    Returns:
        True if extraction is complete, False otherwise.
    """
    if not data:
        return False

    # Must have title
    if not data.get('title'):
        return False

    # Must have year
    if not data.get('year'):
        return False

    # Must have type (unified field name)
    if not data.get('type'):
        return False

    type_val = data.get('type', '').lower()
    type_raw = data.get('type', '')

    # Check if type field is too long (likely contains mixed info like materials)
    # Clean type should be short (e.g., "Video Installation", "Single channel video")
    # If type is longer than 60 chars and contains equipment keywords, it's likely polluted
    equipment_keywords = ['projector', 'player', 'screen', 'monitor', 'computer',
                          '投影', '播放器', '显示器', '电脑']
    if len(type_raw) > 60 and any(kw in type_val for kw in equipment_keywords):
        # Type field contains equipment info that should be in materials
        if not data.get('materials'):
            return False

    # Video works should have duration or video_link
    if 'video' in type_val:
        if not (data.get('duration') or data.get('video_link')):
            return False

    # Physical artwork types should have materials (when strict mode enabled)
    if strict_materials:
        physical_types = ['installation', 'sculpture', 'print', 'object']
        if any(pt in type_val for pt in physical_types):
            if not data.get('materials'):
                return False

    return True
