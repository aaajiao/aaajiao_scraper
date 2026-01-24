"""
Firecrawl API integration mixin for AI-powered extraction.

This module provides advanced scraping capabilities using Firecrawl V2 API:
- LLM-based content extraction with custom schemas
- Batch URL processing with async job polling
- Discovery mode with JavaScript scrolling for infinite-scroll pages
- Smart caching to minimize API credit usage

All methods integrate with the caching system to reduce API costs.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import requests

from .constants import (
    FC_TIMEOUT, FULL_SCHEMA, PROMPT_TEMPLATES, QUICK_SCHEMA,
    MATERIAL_KEYWORDS, CREDITS_PATTERNS,
    ArtworkSchema, ARTWORK_EXTRACT_PROMPT,
)
from .basic import is_artwork, normalize_year, parse_size_duration, is_extraction_complete

logger = logging.getLogger(__name__)


class FirecrawlMixin:
    """Mixin providing Firecrawl V2 API integration.
    
    This mixin adds AI-powered extraction capabilities using Firecrawl's
    LLM-based scraping service. Supports multiple extraction modes with
    automatic schema selection and caching.
    
    Attributes:
        firecrawl_key: API key from CoreScraper.
        rate_limiter: Rate limiter from CoreScraper.
        use_cache: Cache flag from CoreScraper.
        
    Note:
        Requires valid FIRECRAWL_API_KEY in environment for AI features.
    """

    def extract_work_details(self, url: str, retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """[LEGACY] Extract artwork details using old three-tier strategy.

        DEPRECATED: Use extract_work_details_v2() instead for better results.

        This method is kept for backwards compatibility but may be removed in v7.0.
        The new two-layer strategy (v2) provides higher accuracy with similar cost.

        Args:
            url: Artwork page URL to extract from.
            retry_count: Current retry attempt (for internal recursion).

        Returns:
            Dictionary with extracted artwork fields, or None if extraction fails.
        """
        max_retries = 3

        # ===== Layer 0: Cache Check =====
        if self.use_cache:
            cached = self._load_cache(url)
            if cached:
                # Check if cached item is an exhibition (skip it)
                if not is_artwork(cached):
                    logger.debug(f"Cache hit (exhibition, skipped): {url}")
                    return None
                logger.debug(f"Cache hit: {url}")
                return cached

        # ===== Layer 1: Local BS4 Extraction (0 credits) =====
        local_data = None
        if hasattr(self, "extract_metadata_bs4"):
            local_data = self.extract_metadata_bs4(url)
            if local_data:
                # Check if it's an exhibition - skip early
                if not is_artwork(local_data):
                    logger.info(f"⏭️ Skipping exhibition (local): {local_data.get('title', url)}")
                    if self.use_cache:
                        self._save_cache(url, local_data)  # Cache so we skip next time
                    return None

                # Normalize year
                if local_data.get("year"):
                    local_data["year"] = normalize_year(local_data["year"])

                # Check if extraction is complete
                if is_extraction_complete(local_data):
                    logger.info(f"✅ Layer 1 success (0 credits): {local_data['title']}")
                    if self.use_cache:
                        self._save_cache(url, local_data)
                    return local_data

                logger.info(f"📝 Layer 1 partial: {local_data.get('title', 'Unknown')} - missing fields")

        # ===== Layer 2: Markdown Scrape + Regex (1 credit) =====
        markdown = self.scrape_markdown(url)
        if markdown:
            # Try to detect exhibition from markdown
            type_hint = self._extract_type_from_markdown(markdown)
            if type_hint and not is_artwork({"type": type_hint}):
                logger.info(f"⏭️ Skipping exhibition (markdown): {url}")
                # Create minimal data for cache
                skip_data = {"url": url, "type": type_hint, "title": url.split("/")[-1]}
                if self.use_cache:
                    self._save_cache(url, skip_data)
                return None

            # Enrich local_data with regex parsing
            if local_data:
                enriched = self._enrich_with_regex(local_data, markdown)
                if is_extraction_complete(enriched, strict_materials=True):
                    logger.info(f"✅ Layer 2 success (1 credit): {enriched['title']}")
                    if self.use_cache:
                        self._save_cache(url, enriched)
                    return enriched

        # ===== Layer 3: LLM Extract (~20-50 credits, token-based) - Last Resort =====
        logger.info(f"🔥 Layer 3: Using LLM extraction for {url}")
        llm_data = self._extract_with_llm(url, retry_count)

        # Merge LLM data with Layer 1/2 data to preserve images and descriptions
        if llm_data and local_data:
            merged = self._merge_extraction_data(local_data, llm_data)
            if self.use_cache:
                self._save_cache(url, merged)
            return merged

        # If no local_data, just return LLM data
        if llm_data and self.use_cache:
            self._save_cache(url, llm_data)
        return llm_data

    def scrape_markdown(self, url: str) -> Optional[str]:
        """Scrape a URL and return markdown content (1 credit).

        Uses Firecrawl's scrape endpoint with markdown format only,
        which is much cheaper than LLM extraction.

        Args:
            url: URL to scrape.

        Returns:
            Markdown content string, or None if scraping fails.
        """
        if not self.firecrawl_key:
            logger.warning("No Firecrawl API key, skipping markdown scrape")
            return None

        self.rate_limiter.wait()

        try:
            payload = {
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                # Enable Firecrawl server-side caching (2 days default)
                # This can speed up repeated scrapes by up to 5x
                "maxAge": 172800,  # 2 days in seconds
            }
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json",
            }

            resp = requests.post(
                "https://api.firecrawl.dev/v2/scrape",
                json=payload,
                headers=headers,
                timeout=FC_TIMEOUT,
            )

            if resp.status_code == 200:
                data = resp.json()
                markdown = data.get("data", {}).get("markdown", "")
                if markdown:
                    logger.debug(f"Scraped markdown: {len(markdown)} chars")
                    return markdown
            elif resp.status_code == 429:
                logger.warning("Rate limited on markdown scrape")
                time.sleep(2)
                return self.scrape_markdown(url)  # Simple retry
            else:
                logger.warning(f"Markdown scrape failed: {resp.status_code}")

            return None

        except Exception as e:
            logger.error(f"Markdown scrape error: {e}")
            return None

    def _extract_type_from_markdown(self, markdown: str) -> Optional[str]:
        """Extract type/category hint from markdown content.

        Args:
            markdown: Markdown content from scrape.

        Returns:
            Type string if found (e.g., "Exhibition", "Installation"), None otherwise.
        """
        # Look for type indicators in first 1000 chars
        text = markdown[:1000]
        lines = [l.strip().lower() for l in text.split('\n') if l.strip()]

        # Check first 10 lines for standalone type indicators
        for line in lines[:10]:
            # Exhibition page: type line is just "exhibition" or "solo exhibition"
            if line in ['exhibition', 'solo exhibition', 'group exhibition']:
                return "Exhibition"
            # Catalog page
            if line in ['catalog', 'catalogue']:
                return "Catalog"

        # Try to find type line (common patterns) - must be standalone or near start
        type_patterns = [
            r"^(video\s*installation|installation|video|performance|website|software|media\s*sculpture)",
            r"\n(video\s*installation|installation|video|performance|website|software|media\s*sculpture)\n",
        ]
        for pattern in type_patterns:
            match = re.search(pattern, text.lower(), re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip().title()

        return None

    def _enrich_with_regex(
        self, data: Dict[str, Any], markdown: str
    ) -> Dict[str, Any]:
        """Enrich extracted data with additional fields from markdown using regex.

        Args:
            data: Existing extracted data dictionary.
            markdown: Markdown content to parse.

        Returns:
            Enriched data dictionary with size/duration/video_link/title_cn/materials/credits filled.
        """
        result = data.copy()

        # Use parse_size_duration to extract missing fields
        parsed = parse_size_duration(markdown)

        if not result.get("size") and parsed.get("size"):
            result["size"] = parsed["size"]
            logger.debug(f"Enriched size: {parsed['size']}")

        if not result.get("duration") and parsed.get("duration"):
            result["duration"] = parsed["duration"]
            logger.debug(f"Enriched duration: {parsed['duration']}")

        # Extract video_link from markdown
        if not result.get("video_link"):
            video_match = re.search(
                r'(https?://(?:www\.)?(?:vimeo\.com|youtube\.com|youtu\.be|bilibili\.com)[^\s\)\]]+)',
                markdown
            )
            if video_match:
                result["video_link"] = video_match.group(1)
                logger.debug(f"Enriched video_link: {result['video_link']}")

        # Extract title_cn from markdown (format: **Title / 中文标题**)
        if not result.get("title_cn"):
            title_match = re.search(r'\*\*([^*]+)\s*/\s*([^*]+)\*\*', markdown)
            if title_match:
                cn_part = title_match.group(2).strip()
                # Verify Chinese characters exist
                if any('\u4e00' <= c <= '\u9fff' for c in cn_part):
                    result["title_cn"] = cn_part
                    logger.debug(f"Enriched title_cn: {cn_part}")

        # === Extract materials from markdown ===
        if not result.get("materials"):
            materials = self._extract_materials_from_markdown(markdown)
            if materials:
                result["materials"] = materials
                logger.debug(f"Enriched materials: {materials}")

        # === Extract credits from markdown ===
        if not result.get("credits"):
            credits = self._extract_credits_from_markdown(markdown)
            if credits:
                result["credits"] = credits
                logger.debug(f"Enriched credits: {credits}")

        # === Clean type field and extract embedded duration/size ===
        if result.get("type"):
            original_type = result["type"]
            cleaned_type, extracted_duration, extracted_size = self._clean_type_field_with_duration(original_type)
            result["type"] = cleaned_type
            # Use extracted duration if we don't have one yet
            if extracted_duration and not result.get("duration"):
                result["duration"] = extracted_duration
                logger.debug(f"Extracted duration from type: {extracted_duration}")
            # Use extracted size if we don't have one yet
            if extracted_size and not result.get("size"):
                result["size"] = extracted_size
                logger.debug(f"Extracted size from type: {extracted_size}")

        # Normalize year if present
        if result.get("year"):
            result["year"] = normalize_year(result["year"])

        return result

    def _extract_materials_from_markdown(self, markdown: str) -> str:
        """Extract materials from markdown content.

        Uses strict validation to avoid false positives (descriptions, credits).

        Args:
            markdown: Markdown content to parse.

        Returns:
            Materials string if found, empty string otherwise.
        """
        # Sentence starters to exclude (likely descriptions, not material lists)
        sentence_starters = ['the', 'for', 'in', 'a', 'an', 'this', 'it', 'was', 'is', 'are']

        def is_bilingual_line(line: str) -> bool:
            """Check if line is bilingual format (English/Chinese with / separator)."""
            if '/' not in line and '／' not in line:
                return False
            has_english = any(c.isalpha() and ord(c) < 128 for c in line)
            has_chinese = any('\u4e00' <= c <= '\u9fff' for c in line)
            return has_english and has_chinese

        text = markdown[:3000]
        lines = text.split('\n')

        for line in lines[:30]:  # Check first 30 lines
            line = line.strip()
            # Remove markdown formatting
            line = re.sub(r'^\*+|\*+$', '', line).strip()
            line = re.sub(r'^#+\s*', '', line).strip()

            if not line:
                continue

            # === Strict validation (same as Layer 1) ===

            # 1. Length limit: 80 for regular lines, 150 for bilingual lines
            max_len = 150 if is_bilingual_line(line) else 80
            if len(line) > max_len:
                continue

            # 2. Must have list separators (materials are listed, not described)
            if not any(sep in line for sep in [',', '/', '、', '，']):
                continue

            # 3. Exclude lines starting with sentence starters
            first_word = line.split()[0].lower() if line.split() else ''
            if first_word in sentence_starters:
                continue

            # 4. Exclude lines containing artist name
            line_lower = line.lower()
            if 'aaajiao' in line_lower or '徐文恺' in line:
                continue

            # 5. Skip lines that look like credits
            is_credits = False
            for pattern in CREDITS_PATTERNS:
                if re.match(pattern, line_lower, re.IGNORECASE):
                    is_credits = True
                    break
            if is_credits:
                continue

            # 6. Must contain material keywords
            if any(kw.lower() in line_lower for kw in MATERIAL_KEYWORDS):
                return line

        return ""

    def _extract_credits_from_markdown(self, markdown: str) -> str:
        """Extract credits/collaborators from markdown content.

        Args:
            markdown: Markdown content to parse.

        Returns:
            Credits string if found, empty string otherwise.
        """
        text = markdown[:3000]

        for pattern in CREDITS_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                # Use group(0) for full match since patterns may not have capture groups
                return match.group(0).strip()

        return ""

    def _clean_type_field(self, type_val: str) -> str:
        """Clean type field by removing credits, size info, and long descriptions.

        Args:
            type_val: Raw type string.

        Returns:
            Cleaned type string, or empty string if invalid.
        """
        cleaned, _, _ = self._clean_type_field_with_duration(type_val)
        return cleaned

    def _clean_type_field_with_duration(self, type_val: str) -> tuple:
        """Clean type field and extract embedded duration and size.

        Args:
            type_val: Raw type string.

        Returns:
            Tuple of (cleaned_type, extracted_duration, extracted_size).
            Any may be empty string.
        """
        if not type_val:
            return "", "", ""

        type_lower = type_val.lower()
        extracted_duration = ""
        extracted_size = ""

        # Helper: check if line is bilingual format
        def is_bilingual_line(line: str) -> bool:
            if '/' not in line and '／' not in line:
                return False
            has_english = any(c.isalpha() and ord(c) < 128 for c in line)
            has_chinese = any('\u4e00' <= c <= '\u9fff' for c in line)
            return has_english and has_chinese

        # If type looks like credits, return empty
        credits_indicators = [
            r'^Photo(?:\s+by)?:',
            r'^concept:',
            r'^sound:',
            r'^software:',
            r'^Copyright',
            r'^made possible',
        ]
        for pattern in credits_indicators:
            if re.match(pattern, type_lower, re.IGNORECASE):
                return "", "", ""

        # If type is URL, return empty
        if type_val.startswith('http'):
            return "", "", ""

        # Length limit: 80 for regular, 150 for bilingual
        max_len = 150 if is_bilingual_line(type_val) else 80
        if len(type_val) > max_len:
            return "", "", ""

        # Exclude size-related lines (common false positives)
        size_indicators = ['variable size', '尺寸可变', 'dimension variable',
                           'dimensions variable', 'variable media']
        if any(x in type_lower for x in size_indicators):
            return "", "", ""

        # Exclude lines containing artist name
        if 'aaajiao' in type_lower or '徐文恺' in type_val:
            return "", "", ""

        # Exclude lines with colon followed by long descriptive text
        if ':' in type_val and not re.match(r'^[A-Za-z]+:', type_lower):
            colon_pos = type_val.find(':')
            after_colon = type_val[colon_pos+1:].strip()
            if len(after_colon) > 30:
                return "", "", ""

        # Extract and remove embedded duration from type
        # Pattern 1: Quote-style duration at start (6'00" or 15′00″)
        duration_at_start = re.match(
            r"^(\d+['\u2018\u2019\u2032′'\"]{1,2}\d*['\u2018\u2019\u2032′''\"]*)\s*(.*)$",
            type_val
        )
        if duration_at_start:
            extracted_duration = duration_at_start.group(1).strip()
            remaining = duration_at_start.group(2).strip()
            type_val = remaining.lstrip('"\'"′″\u201c\u201d\u2018\u2019 ')
        else:
            # Pattern 2: minutes/seconds embedded in type
            duration_match = re.search(
                r',?\s*(\d+\s*(?:min(?:utes?)?|seconds?)[^,]*)',
                type_val,
                re.IGNORECASE
            )
            if duration_match:
                extracted_duration = duration_match.group(1).strip()
                type_val = re.sub(
                    r',?\s*\d+\s*(?:min(?:utes?)?|seconds?)[^,]*',
                    '',
                    type_val,
                    flags=re.IGNORECASE
                ).strip().rstrip(',')

        # Extract and remove embedded size from type
        # E.g., "installation / 装置 76cm × 30cm × 280cm"
        size_in_type = re.search(
            r'(\d+\s*(?:cm|mm|m)?\s*[×xX]\s*\d+\s*(?:cm|mm|m)?(?:\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)?)',
            type_val
        )
        if size_in_type:
            extracted_size = size_in_type.group(1).strip()
            type_val = re.sub(
                r'\s*\d+\s*(?:cm|mm|m)?\s*[×xX]\s*\d+\s*(?:cm|mm|m)?(?:\s*[×xX]\s*\d+\s*(?:cm|mm|m)?)?',
                '',
                type_val
            ).strip().rstrip(',').rstrip('/')

        return type_val, extracted_duration, extracted_size

    def _merge_extraction_data(
        self, base_data: Dict[str, Any], llm_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge local data with LLM extraction results.

        Strategy: LLM non-empty fields take priority, but preserve base data's
        images and descriptions which are often lost in LLM extraction.

        Args:
            base_data: Data from BS4 local parsing.
            llm_data: Data from Firecrawl LLM/Schema extraction.

        Returns:
            Merged dictionary with best data from both sources.
        """
        result = base_data.copy()

        # Helper: check if a string looks like credits (not materials)
        def looks_like_credits(text: str) -> bool:
            if not text:
                return False
            text_lower = text.lower()
            # Credits patterns: "concept:", "sound:", "software:", etc.
            credit_indicators = ['concept:', 'sound:', 'software:', 'hardware:',
                                 'photo:', 'video editing:', 'team:', 'director:']
            return any(ci in text_lower for ci in credit_indicators)

        # Helper: check if materials value is actually empty/placeholder
        def is_empty_materials(text: str) -> bool:
            if not text:
                return True
            text_lower = text.lower().strip()
            empty_indicators = ['none', 'n/a', 'not specified', 'none specified',
                                'not available', 'unknown', 'na', '-', '']
            return text_lower in empty_indicators

        # LLM priority fields - these are better extracted by LLM
        llm_priority_fields = [
            'title', 'title_cn', 'year', 'type', 'materials',
            'size', 'duration', 'credits', 'video_link'
        ]
        for field in llm_priority_fields:
            if llm_data.get(field):
                # Special handling for materials field
                if field == 'materials':
                    mat_val = llm_data.get('materials', '')
                    # Skip if LLM confused credits with materials
                    if looks_like_credits(mat_val):
                        logger.debug(f"Skipping LLM materials (looks like credits): {mat_val[:50]}")
                        continue
                    # Skip placeholder values
                    if is_empty_materials(mat_val):
                        continue
                result[field] = llm_data[field]

        # Preserve base data's images and descriptions (often lost in LLM)
        preserve_fields = ['images', 'high_res_images', 'description_en', 'description_cn']
        for field in preserve_fields:
            # Keep base_data value if result doesn't have it or is empty
            if base_data.get(field) and not result.get(field):
                result[field] = base_data[field]

        result['source'] = 'merged_llm'
        return result

    def _get_missing_fields(self, data: Dict[str, Any]) -> List[str]:
        """Determine which important fields are missing based on artwork type.

        Uses type-aware logic to decide if Layer 2 (API) is needed:
        - Video works: need duration
        - Physical installations: need size and/or materials
        - Website/Software: minimal requirements

        Args:
            data: Extracted artwork data with 'type' field.

        Returns:
            List of missing field names that should trigger Layer 2.
        """
        missing = []
        type_val = (data.get('type') or '').lower()

        # Type classification
        is_video = 'video' in type_val or 'film' in type_val or 'animation' in type_val
        is_physical = any(t in type_val for t in [
            'installation', 'sculpture', 'object', 'print', 'painting', 'media'
        ])
        is_digital_only = any(t in type_val for t in [
            'website', 'software', 'app', 'game', 'nft', 'crypto'
        ]) and not is_physical

        # Video works: duration is important
        if is_video and not data.get('duration') and not data.get('video_link'):
            missing.append('duration')

        # Physical works: size and materials are important
        if is_physical:
            # Size: important unless explicitly "variable"
            if not data.get('size'):
                if 'variable' not in type_val and '可变' not in type_val:
                    missing.append('size')
            # Materials: important for understanding the work
            if not data.get('materials'):
                missing.append('materials')

        # Description: important for completeness - count as 2 missing fields
        # This ensures Layer 2 is triggered when only description is missing
        if not data.get('description_en') and not data.get('description_cn'):
            missing.append('description_en')
            missing.append('description_cn')

        return missing

    def _extract_with_schema(self, url: str, max_polls: int = 15) -> Optional[Dict[str, Any]]:
        """Extract using Firecrawl Extract API v2 with Pydantic schema (~5 credits per extract).

        Uses the optimized ArtworkSchema for structured extraction with better
        field descriptions and prompt engineering. The Extract API v2 is async,
        so we submit a job and poll for results.

        Args:
            url: URL to extract from.
            max_polls: Maximum polling attempts (default 15, ~45 seconds).

        Returns:
            Dictionary with extracted fields, or None if extraction fails.
        """
        if not self.firecrawl_key:
            logger.warning("No Firecrawl API key for schema extraction")
            return None

        self.rate_limiter.wait()

        # Track API calls for debugging duplicate issues
        if not hasattr(self, '_extract_call_count'):
            self._extract_call_count = {}
        self._extract_call_count[url] = self._extract_call_count.get(url, 0) + 1
        call_num = self._extract_call_count[url]

        try:
            logger.info(f"🎯 Schema Extract (v2) [call #{call_num}]: {url}")

            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json",
            }

            # Use Pydantic schema for structured extraction
            payload = {
                "urls": [url],
                "schema": ArtworkSchema.model_json_schema(),
                "prompt": ARTWORK_EXTRACT_PROMPT,
            }

            # Step 1: Submit async extraction job (v2 API)
            resp = requests.post(
                "https://api.firecrawl.dev/v2/extract",
                json=payload,
                headers=headers,
                timeout=60,
            )

            if resp.status_code != 200:
                if resp.status_code == 429:
                    logger.warning("Rate limited on schema extract, waiting...")
                    time.sleep(5)
                    return self._extract_with_schema(url)
                logger.warning(f"Schema Extract submit failed: {resp.status_code}")
                return None

            result = resp.json()
            if not result.get("success") or not result.get("id"):
                logger.warning(f"Schema Extract job creation failed: {result}")
                return None

            job_id = result["id"]
            logger.debug(f"Extract job submitted: {job_id}")

            # Step 2: Poll for results (v2 API)
            for poll_attempt in range(max_polls):
                time.sleep(3)  # Wait 3 seconds between polls

                poll_resp = requests.get(
                    f"https://api.firecrawl.dev/v2/extract/{job_id}",
                    headers=headers,
                    timeout=30,
                )

                if poll_resp.status_code != 200:
                    logger.warning(f"Poll failed: {poll_resp.status_code}")
                    continue

                poll_result = poll_resp.json()
                status = poll_result.get("status")

                if status == "completed":
                    data = poll_result.get("data", {})
                    if data:
                        # v2 API may return data as a list
                        if isinstance(data, list) and len(data) > 0:
                            data = data[0]
                        data["url"] = url
                        data["source"] = "schema_extract_v2"
                        logger.info(f"✅ Schema Extract success: {data.get('title', 'Unknown')}")
                        return data
                    else:
                        logger.warning(f"Schema Extract returned empty data for {url}")
                        return None

                elif status == "failed":
                    logger.warning(f"Schema Extract job failed: {poll_result}")
                    return None

                # Still processing, continue polling
                logger.debug(f"Extract job {job_id} status: {status} (poll {poll_attempt + 1}/{max_polls})")

            logger.warning(f"Schema Extract timed out after {max_polls} polls for {url}")
            return None

        except Exception as e:
            logger.error(f"Schema Extract error: {e}")
            return None

    def _batch_extract_with_schema(
        self, urls: List[str], max_polls: int = 30
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Batch extract using Firecrawl Extract API v2 with multiple URLs.

        More efficient than individual extractions when processing many URLs.
        The Extract API v2 accepts multiple URLs in a single request.

        Args:
            urls: List of URLs to extract from (max recommended: 10).
            max_polls: Maximum polling attempts (default 30, ~90 seconds).

        Returns:
            Dictionary mapping URL to extracted data (or None if failed).
        """
        if not self.firecrawl_key or not urls:
            return {url: None for url in urls}

        self.rate_limiter.wait()

        try:
            logger.info(f"🎯 Batch Schema Extract (v2): {len(urls)} URLs")

            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json",
            }

            # Submit batch extraction job (v2 API)
            payload = {
                "urls": urls,
                "schema": ArtworkSchema.model_json_schema(),
                "prompt": ARTWORK_EXTRACT_PROMPT,
            }

            resp = requests.post(
                "https://api.firecrawl.dev/v2/extract",
                json=payload,
                headers=headers,
                timeout=60,
            )

            if resp.status_code != 200:
                if resp.status_code == 429:
                    logger.warning("Rate limited on batch extract, waiting...")
                    time.sleep(10)
                    return self._batch_extract_with_schema(urls, max_polls)
                logger.warning(f"Batch Extract submit failed: {resp.status_code}")
                return {url: None for url in urls}

            result = resp.json()
            if not result.get("success") or not result.get("id"):
                logger.warning(f"Batch Extract job creation failed: {result}")
                return {url: None for url in urls}

            job_id = result["id"]
            logger.debug(f"Batch extract job submitted: {job_id}")

            # Poll for results (v2 API)
            for poll_attempt in range(max_polls):
                time.sleep(3)

                poll_resp = requests.get(
                    f"https://api.firecrawl.dev/v2/extract/{job_id}",
                    headers=headers,
                    timeout=30,
                )

                if poll_resp.status_code != 200:
                    continue

                poll_result = poll_resp.json()
                status = poll_result.get("status")

                if status == "completed":
                    data = poll_result.get("data", {})
                    # Map results back to URLs
                    results = {}
                    if isinstance(data, list):
                        for i, item in enumerate(data):
                            if i < len(urls):
                                item["url"] = urls[i]
                                item["source"] = "batch_schema_extract_v2"
                                results[urls[i]] = item
                    elif isinstance(data, dict):
                        # Single result or keyed by URL
                        for url in urls:
                            if url in data:
                                data[url]["url"] = url
                                data[url]["source"] = "batch_schema_extract_v2"
                                results[url] = data[url]
                            elif len(urls) == 1:
                                data["url"] = url
                                data["source"] = "batch_schema_extract_v2"
                                results[url] = data

                    logger.info(f"✅ Batch Extract success: {len(results)}/{len(urls)} URLs")
                    # Fill in None for missing URLs
                    for url in urls:
                        if url not in results:
                            results[url] = None
                    return results

                elif status == "failed":
                    logger.warning(f"Batch Extract job failed: {poll_result}")
                    return {url: None for url in urls}

                logger.debug(f"Batch job {job_id} status: {status} (poll {poll_attempt + 1}/{max_polls})")

            logger.warning(f"Batch Extract timed out after {max_polls} polls")
            return {url: None for url in urls}

        except Exception as e:
            logger.error(f"Batch Extract error: {e}")
            return {url: None for url in urls}

    def extract_work_details_v2(self, url: str) -> Optional[Dict[str, Any]]:
        """Optimized two-layer extraction strategy for maximum completeness.

        Strategy:
        1. Layer 1: Local BS4 parsing (0 credits) - fast, free
        2. Layer 2: Firecrawl Extract with schema (~20-50 credits, token-based) - if Layer 1 incomplete

        Args:
            url: Artwork page URL to extract from.

        Returns:
            Dictionary with extracted artwork fields, or None if extraction fails.
        """
        # Layer 0: Cache check
        if self.use_cache:
            cached = self._load_cache(url)
            if cached:
                if not is_artwork(cached):
                    logger.debug(f"Cache hit (exhibition, skipped): {url}")
                    return None
                logger.debug(f"Cache hit: {url}")
                return cached

        # Layer 1: BS4 local parsing (0 credits)
        local_data = None
        if hasattr(self, "extract_metadata_bs4"):
            local_data = self.extract_metadata_bs4(url)
            if local_data:
                # Skip exhibitions early
                if not is_artwork(local_data):
                    logger.info(f"⏭️ Skipping exhibition (local): {local_data.get('title', url)}")
                    if self.use_cache:
                        self._save_cache(url, local_data)
                    return None

                # Normalize year
                if local_data.get("year"):
                    local_data["year"] = normalize_year(local_data["year"])

        # Check completeness of Layer 1 result
        # Use type-aware required fields to reduce unnecessary API calls
        if local_data:
            missing = self._get_missing_fields(local_data)
        else:
            missing = ['title', 'year', 'type']  # Minimum required

        # Always use Layer 2 to verify and supplement for 100% data accuracy
        # Even if Layer 1 appears complete, Layer 2 double-checks for correctness
        always_verify = True  # Set to False to only call Layer 2 when fields are missing
        if always_verify or len(missing) >= 1:
            logger.info(f"📝 Calling Layer 2 for verification (missing {len(missing)} field(s))...")
            schema_data = self._extract_with_schema(url)

            if schema_data:
                if local_data:
                    # Field priority:
                    # - Layer 1 authoritative: year, type (from tags, ~100% accurate)
                    # - Layer 1 exclusive: images (from slideshow container)
                    # - Layer 2 authoritative: other text fields (AI more accurate)

                    # Fields where Layer 2 takes priority (override Layer 1)
                    layer2_priority = [
                        'title', 'title_cn',
                        'materials', 'size', 'duration', 'credits',
                        'description_en', 'description_cn'
                    ]
                    for field in layer2_priority:
                        if schema_data.get(field):
                            local_data[field] = schema_data[field]

                    # Fields where Layer 1 takes priority (only fill if empty)
                    # year and type from tags are more reliable than LLM extraction
                    layer1_priority = ['year', 'type']
                    for field in layer1_priority:
                        if not local_data.get(field) and schema_data.get(field):
                            local_data[field] = schema_data[field]

                    local_data['source'] = 'hybrid_verified'
                else:
                    local_data = schema_data
        elif local_data:
            logger.info(f"✅ Layer 1 complete: {local_data.get('title', 'Unknown')}")

        # Cache and return
        if local_data and self.use_cache:
            self._save_cache(url, local_data)

        return local_data

    def _extract_with_llm(self, url: str, retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """Extract data using Firecrawl LLM (~20-50 credits, token-based).

        This is the most expensive extraction method, used as last resort.

        Args:
            url: URL to extract from.
            retry_count: Current retry attempt for rate limiting.

        Returns:
            Extracted work dictionary, or None if extraction fails.
        """
        max_retries = 3

        self.rate_limiter.wait()

        try:
            logger.info(f"[{retry_count+1}/{max_retries}] LLM Extract: {url}")

            fc_endpoint = "https://api.firecrawl.dev/v2/scrape"

            # Schema for LLM extraction
            schema: Dict[str, Any] = {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The English title of the work"},
                    "title_cn": {
                        "type": "string",
                        "description": "The Chinese title of the work. If not explicitly found, leave empty.",
                    },
                    "year": {
                        "type": "string",
                        "description": "Creation year or year range (e.g. 2018-2022)",
                    },
                    "category": {
                        "type": "string",
                        "description": "The art category (e.g. Video Installation, Software, Website, Exhibition)",
                    },
                    "materials": {
                        "type": "string",
                        "description": "Physical materials ONLY (e.g. LED, acrylic, wood, silicone, screen printing). Do NOT include credits or collaborators here.",
                    },
                    "size": {
                        "type": "string",
                        "description": "Physical dimensions (e.g. '180 x 180 cm', 'Dimension variable'). Leave empty if not specified.",
                    },
                    "duration": {
                        "type": "string",
                        "description": "Video duration for video/film works (e.g. '4:30', '2′47′'). Leave empty for non-video works.",
                    },
                    "credits": {
                        "type": "string",
                        "description": "Credits and collaborators (e.g. 'Photo: John', 'concept: aaajiao; sound: yang2'). Separate from materials.",
                    },
                    "video_link": {"type": "string", "description": "Vimeo URL if present"},
                },
                "required": ["title"],
            }

            url_slug = url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ")

            payload = {
                "url": url,
                "formats": [
                    {
                        "type": "json",
                        "schema": schema,
                        "prompt": (
                            f"You are an art archivist. This is a Single Page Application (SPA) portfolio site. "
                            f"IMPORTANT: Extract ONLY the artwork that matches the URL slug '{url_slug}'. "
                            f"The page may show multiple artworks, but you must find and extract the one "
                            f"whose title or ID matches '{url_slug}'. "
                            f"Ignore navigation links and other artworks. "
                            f"The title usually appears as 'English Title / Chinese Title'. Separate them."
                        ),
                    }
                ],
            }

            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json",
            }

            resp = requests.post(fc_endpoint, json=payload, headers=headers, timeout=FC_TIMEOUT)

            if resp.status_code == 200:
                data = resp.json()
                json_data = data.get("data", {}).get("json")
                if json_data:
                    work = {
                        "url": url,
                        "title": json_data.get("title", ""),
                        "title_cn": json_data.get("title_cn", ""),
                        "type": json_data.get("category", "") or json_data.get("type", ""),
                        "materials": json_data.get("materials", ""),
                        "size": json_data.get("size", ""),
                        "duration": json_data.get("duration", ""),
                        "credits": json_data.get("credits", ""),
                        "year": json_data.get("year", ""),
                        "description_cn": json_data.get("description_cn", ""),
                        "description_en": json_data.get("description_en", ""),
                        "video_link": json_data.get("video_link", ""),
                        "tags": [],
                    }

                    # Post-processing: Split bilingual title
                    if not work["title_cn"] and "/" in work["title"]:
                        parts = work["title"].split("/")
                        work["title"] = parts[0].strip()
                        if len(parts) > 1:
                            work["title_cn"] = parts[1].strip()

                    # Normalize year
                    if work["year"]:
                        work["year"] = normalize_year(work["year"])

                    # Check if it's an exhibition
                    if not is_artwork(work):
                        logger.info(f"⏭️ Skipping exhibition (LLM): {work.get('title', url)}")
                        if self.use_cache:
                            self._save_cache(url, work)
                        return None

                    # Save to cache
                    if self.use_cache:
                        self._save_cache(url, work)

                    return work
                else:
                    logger.error(f"Firecrawl returned unexpected format: {data}")

            elif resp.status_code == 429:
                if retry_count >= max_retries:
                    logger.error(f"Max retries exceeded: {url}")
                    return None
                wait_time = 2 ** retry_count
                logger.warning(f"Rate limited, waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                return self._extract_with_llm(url, retry_count + 1)

            else:
                logger.error(f"Firecrawl Error {resp.status_code}: {resp.text[:200]}")

            return None

        except Exception as e:
            logger.error(f"LLM extraction error {url}: {e}")
            return None

    def agent_search(
        self,
        prompt: str,
        urls: Optional[List[str]] = None,
        max_credits: int = 50,
        extraction_level: str = "custom",
    ) -> Optional[Dict[str, Any]]:
        """Intelligent search/extraction entry point for batch or agent mode.
        
        Supports two distinct modes:
        1. **Batch extraction**: When urls parameter is provided, extracts
           structured data from a list of URLs using the /v2/extract endpoint
        2. **Agent search**: When urls is None, performs autonomous web search
           using the /v2/agent endpoint
        
        Args:
            prompt: Extraction instructions or search query.
                For batch: describes what data to extract.
                For agent: describes what to search for.
            urls: Optional list of URLs for batch extraction.
                If None, switches to agent search mode.
            max_credits: Maximum API credits to use. Defaults to 50.
                For batch: limits number of URLs processed.
                For agent: limits search result count.
            extraction_level: Schema mode - 'quick', 'full', 'images_only', or 'custom'.
                Defaults to 'custom'. Determines which predefined schema to use.
        
        Returns:
            Dictionary with extraction results:
                - data: List of extracted items (dicts)
                - cached_count: Number of cache hits (batch mode only)
                - new_count: Number of new extractions (batch mode only)
                - from_cache: True if all results from cache (batch mode only)
            Returns None if extraction/search fails.
            
        Note:
            - Batch mode checks cache first for each URL
            - Uses async job polling (up to 10min timeout)
            - Automatically saves new results to cache
            - Falls back to cached results on API failure
            
        Example:
            >>> # Batch extraction
            >>> result = scraper.agent_search(
            ...     prompt="Extract artwork details",
            ...     urls=["https://example.com/work1", "https://example.com/work2"],
            ...     extraction_level="full"
            ... )
            >>> print(f"Extracted {len(result['data'])} works")
            >>> 
            >>> # Agent search
            >>> result = scraper.agent_search(
            ...     prompt="Find all video installations from 2020",
            ...     extraction_level="quick"
            ... )
        """
        # === Select schema and prompt based on extraction level ===
        schema: Optional[Dict[str, Any]] = None
        if extraction_level == "quick":
            schema = QUICK_SCHEMA
            if not prompt or prompt == PROMPT_TEMPLATES["default"]:
                prompt = PROMPT_TEMPLATES["quick"]
            logger.info("📋 Using Quick mode (core fields)")
        elif extraction_level == "full":
            schema = FULL_SCHEMA
            if not prompt or prompt == PROMPT_TEMPLATES["default"]:
                prompt = PROMPT_TEMPLATES["full"]
            logger.info("📋 Using Full mode (complete fields)")
        elif extraction_level == "images_only":
            if not prompt or prompt == PROMPT_TEMPLATES["default"]:
                prompt = PROMPT_TEMPLATES["images_only"]
            logger.info("🖼️ Using Images Only mode (high-res images)")

        # === Scenario 1: Batch extraction (URLs specified) ===
        if urls and len(urls) > 0:
            # Limit URLs to match max credits
            target_urls = urls[:max_credits]

            # === Cache check: separate cached and uncached URLs ===
            cached_results: List[Dict[str, Any]] = []
            uncached_urls: List[str] = []
            for url in target_urls:
                cached = self._load_extract_cache(url, prompt)
                if cached:
                    cached_results.append(cached)
                else:
                    uncached_urls.append(url)

            logger.info(
                f"🔍 Cache check: {len(cached_results)} hits, {len(uncached_urls)} to extract"
            )

            # If all cached, return immediately
            if not uncached_urls:
                logger.info("✅ All results from cache, saving API calls!")
                return {
                    "data": cached_results,
                    "from_cache": True,
                    "cached_count": len(cached_results),
                }

            logger.info(f"🚀 Starting concurrent extraction (Target: {len(uncached_urls)} URLs, Workers: 3)")

            extract_endpoint = "https://api.firecrawl.dev/v2/extract"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json",
            }

            def extract_single_url(url: str) -> Tuple[str, Optional[Dict[str, Any]]]:
                """Extract data from a single URL with job polling."""
                payload: Dict[str, Any] = {
                    "urls": [url],  # Single URL
                    "prompt": prompt,
                    "enableWebSearch": False,
                }
                if schema:
                    payload["schema"] = schema

                try:
                    # 1. Submit job
                    resp = requests.post(extract_endpoint, json=payload, headers=headers, timeout=FC_TIMEOUT)
                    
                    if resp.status_code != 200:
                        logger.error(f"❌ [{url[:50]}...] Submit failed: {resp.status_code}")
                        return url, {"url": url, "title": "[Error: Submit Failed]", "error": f"HTTP {resp.status_code}"}

                    result = resp.json()
                    if not result.get("success"):
                        logger.error(f"❌ [{url[:50]}...] API error: {result}")
                        return url, {"url": url, "title": "[Error: API Failed]", "error": str(result)}

                    job_id = result.get("id")
                    status_endpoint = f"{extract_endpoint}/{job_id}"

                    # 2. Poll for completion (max 3 min per URL)
                    max_wait = 180
                    poll_interval = 3
                    elapsed = 0

                    while elapsed < max_wait:
                        time.sleep(poll_interval)
                        elapsed += poll_interval

                        status_resp = requests.get(status_endpoint, headers=headers, timeout=FC_TIMEOUT)
                        if status_resp.status_code != 200:
                            continue

                        status_data = status_resp.json()
                        status = status_data.get("status")

                        if status == "completed":
                            data = status_data.get("data", {})
                            # Handle list or single object
                            if isinstance(data, list):
                                item = data[0] if data else {}
                            else:
                                item = data
                            
                            # Ensure URL is set
                            if not item.get("url"):
                                item["url"] = url
                            
                            # Validate: must have title or meaningful content
                            if not item.get("title") and not item.get("description_en") and not item.get("images"):
                                logger.warning(f"⚠️ [{url[:40]}...] Empty extraction result")
                                item["title"] = "[Error: Empty Content]"
                                item["error"] = "Extraction returned empty data"
                            
                            logger.info(f"✅ [{item.get('title', url)[:30]}...] Extracted")
                            return url, item

                        elif status == "failed":
                            logger.error(f"❌ [{url[:50]}...] Job failed")
                            return url, {"url": url, "title": "[Error: Job Failed]", "error": "Extraction job failed"}

                    # Timeout
                    logger.error(f"⏰ [{url[:50]}...] Timeout (3min)")
                    return url, {"url": url, "title": "[Error: Timeout]", "error": "Extraction timeout"}

                except Exception as e:
                    logger.error(f"❌ [{url[:50]}...] Exception: {e}")
                    return url, {"url": url, "title": "[Error: Exception]", "error": str(e)}

            # === Concurrent execution with ThreadPoolExecutor ===
            try:
                new_results: List[Dict[str, Any]] = []
                
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_url = {executor.submit(extract_single_url, url): url for url in uncached_urls}
                    
                    for future in as_completed(future_to_url):
                        url, result = future.result()
                        if result:
                            new_results.append(result)
                            # Save to cache (only successful extractions)
                            if not result.get("error"):
                                self._save_extract_cache(url, prompt, result)

                logger.info(f"✅ Concurrent extraction complete. Total: {len(new_results)} results")

                # Merge cached and new results
                all_data = cached_results + new_results
                return {
                    "data": all_data,
                    "cached_count": len(cached_results),
                    "new_count": len(new_results),
                }

            except Exception as e:
                logger.error(f"Concurrent extraction exception: {e}")
                if cached_results:
                    return {
                        "data": cached_results,
                        "from_cache": True,
                        "cached_count": len(cached_results),
                    }
                raise e


        # === Scenario 2: Open-ended agent search (no URLs) ===
        else:
            logger.info("🤖 Starting Smart Agent task (open search)...")

            agent_endpoint = "https://api.firecrawl.dev/v2/agent"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "query": f"{prompt} site:eventstructure.com",
                "limit": max_credits,
            }

            try:
                # 1. Submit job
                resp = requests.post(agent_endpoint, json=payload, headers=headers, timeout=FC_TIMEOUT)

                if resp.status_code != 200:
                    raise RuntimeError(f"Agent start failed: {resp.status_code} - {resp.text}")

                result = resp.json()
                if not result.get("success"):
                    raise RuntimeError(f"Agent start failed: {result}")

                job_id = result.get("id")

                logger.info(f"   Agent job ID: {job_id}")
                status_endpoint = f"{agent_endpoint}/{job_id}"
                max_wait = 600
                poll_interval = 5
                elapsed = 0

                while elapsed < max_wait:
                    time.sleep(poll_interval)
                    elapsed += poll_interval

                    status_resp = requests.get(
                        status_endpoint, headers=headers, timeout=FC_TIMEOUT
                    )
                    if status_resp.status_code != 200:
                        continue

                    status_data = status_resp.json()
                    status = status_data.get("status")

                    if status == "processing":
                        logger.info(f"   ⏳ Thinking... ({elapsed}s)")
                    elif status == "completed":
                        credits = status_data.get("creditsUsed", "N/A")
                        data = status_data.get("data", [])
                        logger.info(f"✅ Agent task complete (Credits: {credits})")
                        return {"data": data}
                    elif status == "failed":
                        raise RuntimeError("Agent task failed")

                raise TimeoutError("Agent timeout (10min)")

            except Exception as e:
                logger.error(f"Agent exception: {e}")
                raise e

    def discover_urls_with_scroll(
        self, url: str, scroll_mode: str = "auto", use_cache: bool = True
    ) -> List[str]:
        """Discover URLs from infinite-scroll pages using automated scrolling.
        
        Uses Firecrawl's browser automation to trigger JavaScript scroll events
        and discover dynamically loaded content. Particularly useful for
        portfolio pages with horizontal or vertical infinite scroll.
        
        Args:
            url: Page URL to scrape (typically homepage or gallery page).
            scroll_mode: Scrolling strategy - 'auto', 'horizontal', or 'vertical'.
                - 'auto': Combined horizontal + vertical (15+3 scrolls)
                - 'horizontal': Horizontal scrolling only (20 scrolls)
                - 'vertical': Vertical scrolling only (5 scrolls)
                Defaults to 'auto'.
            use_cache: Whether to use cached results if valid (TTL: 24h).
                Defaults to True.
        
        Returns:
            List of discovered artwork URLs. Empty list if discovery fails.
            
        Note:
            - Caches results for 24 hours to avoid repeated expensive operations
            - Uses JavaScript execution to trigger scroll events
            - Waits between scrolls for content to load (1.5s intervals)
            - Returns empty list on error (doesn't raise exceptions)
            
        Example:
            >>> scraper = AaajiaoScraper()
            >>> # Discover from homepage with horizontal scroll
            >>> urls = scraper.discover_urls_with_scroll(
            ...     "https://eventstructure.com",
            ...     scroll_mode="horizontal"
            ... )
            >>> print(f"Found {len(urls)} artworks")
        """
        # === Cache check ===
        cache_path = self._get_discovery_cache_path(url, scroll_mode)
        if use_cache and self._is_discovery_cache_valid(cache_path):
            try:
                with open(cache_path, "r") as f:
                    cached = json.load(f)
                    logger.info(f"✅ Discovery cache hit: {len(cached)} links (TTL: 24h)")
                    return cached
            except Exception:
                pass

        logger.info(f"🕵️  Starting Discovery Phase: {url} (Mode: {scroll_mode})")

        # Build scroll action sequence
        actions: List[Dict[str, Any]] = []
        actions.append({"type": "wait", "milliseconds": 2000})

        if scroll_mode == "horizontal":
            for i in range(20):
                actions.append(
                    {
                        "type": "executeJavascript",
                        "script": (
                            "window.scrollTo(document.documentElement.scrollWidth, 0); "
                            "window.dispatchEvent(new Event('scroll'));"
                        ),
                    }
                )
                actions.append({"type": "wait", "milliseconds": 1500})
        elif scroll_mode == "vertical":
            for _ in range(5):
                actions.append({"type": "scroll", "direction": "down"})
                actions.append({"type": "wait", "milliseconds": 1500})
        else:  # auto
            # Horizontal first
            for i in range(15):
                actions.append(
                    {
                        "type": "executeJavascript",
                        "script": (
                            "window.scrollTo(document.documentElement.scrollWidth, 0); "
                            "window.dispatchEvent(new Event('scroll'));"
                        ),
                    }
                )
                actions.append({"type": "wait", "milliseconds": 1500})
            # Then vertical
            for _ in range(3):
                actions.append({"type": "scroll", "direction": "down"})

        endpoint = "https://api.firecrawl.dev/v2/scrape"
        headers = {
            "Authorization": f"Bearer {self.firecrawl_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "url": url,
            "formats": ["extract"],
            "actions": actions,
            "extract": {
                "prompt": "Extract all artwork URLs from the page. Return ONLY a list of URLs."
            },
        }

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                # Extract URLs from response
                # Note: Actual parsing depends on Firecrawl's response format
                links = [
                    item.get("url")
                    for item in data.get("data", {}).get("extract", {}).get("urls", [])
                    if item.get("url")
                ]

                # Save to cache
                if links:
                    with open(cache_path, "w") as f:
                        json.dump(links, f)
                    logger.info(f"📦 Cached {len(links)} discovered URLs")

                return links
            else:
                logger.error(f"Discovery failed: {resp.status_code} - {resp.text[:200]}")
            return []
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            return []

