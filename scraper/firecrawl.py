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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import requests

from .constants import FC_TIMEOUT, FULL_SCHEMA, PROMPT_TEMPLATES, QUICK_SCHEMA

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
        """Extract artwork details using Firecrawl AI with caching and retries.
        
        Uses structured LLM extraction to parse artwork metadata from HTML.
        Implements exponential backoff for rate limit errors and automatic
        cache management.
        
        Args:
            url: Artwork page URL to extract from.
            retry_count: Current retry attempt (for internal recursion).
                Defaults to 0. Max 3 retries.
        
        Returns:
            Dictionary with extracted artwork fields:
                - url: Original URL
                - title: English title
                - title_cn: Chinese title (if found)
                - type/category: Art category
                - materials: Materials description
                - year: Creation year
                - description_en/cn: Descriptions
                - video_link: Vimeo URL if present
            Returns None if extraction fails after retries.
            
        Note:
            - Checks cache first to save API credits
            - Automatically splits bilingual titles (format: "English / Chinese")
            - Rate limited to prevent API quota exhaustion
            - Retries with exponential backoff on 429 errors
            
        Example:
            >>> scraper = AaajiaoScraper()
            >>> details = scraper.extract_work_details("https://eventstructure.com/work/title")
            >>> print(details['title'], details['year'])
        """
        max_retries = 3

        # 1. Cache priority
        if self.use_cache:
            cached = self._load_cache(url)
            if cached:
                logger.debug(f"Cache hit: {url}")
                return cached

        # 2. Rate limiting
        self.rate_limiter.wait()

        try:
            logger.info(f"[{retry_count+1}/{max_retries}] Scraping: {url}")

            fc_endpoint = "https://api.firecrawl.dev/v2/scrape"

            # Use inline schema for compatibility
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
                        "description": "The art category (e.g. Video Installation, Software, Website)",
                    },
                    "materials": {
                        "type": "string",
                        "description": "Materials list (e.g. LED screen, 3D printing)",
                    },
                    "description_en": {
                        "type": "string",
                        "description": "Detailed work description in English. Exclude navigation text.",
                    },
                    "description_cn": {
                        "type": "string",
                        "description": "Detailed work description in Chinese. Exclude navigation text.",
                    },
                    "video_link": {"type": "string", "description": "Vimeo URL if present"},
                },
                "required": ["title"],
            }

            payload = {
                "url": url,
                "formats": [
                    {
                        "type": "json",
                        "schema": schema,
                        "prompt": (
                            "You are an art archivist. Extract the artwork metadata from the portfolio page. "
                            "Ignore navigation links like 'Previous/Next project'. "
                            "The title usually appears as 'English Title / Chinese Title'. Separate them."
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
                # v2 API with formats: [{type: "json", ...}] returns data in data["data"]["json"]
                json_data = data.get("data", {}).get("json")
                if json_data:
                    result = json_data

                    work = {
                        "url": url,
                        "title": result.get("title", ""),
                        "title_cn": result.get("title_cn", ""),
                        "type": result.get("category", "") or result.get("type", ""),
                        "materials": result.get("materials", ""),
                        "year": result.get("year", ""),
                        "description_cn": result.get("description_cn", ""),
                        "description_en": result.get("description_en", ""),
                        "video_link": result.get("video_link", ""),
                        "size": "",
                        "duration": "",
                        "tags": [],
                    }

                    # Post-processing: Split bilingual title if AI didn't
                    if not work["title_cn"] and "/" in work["title"]:
                        parts = work["title"].split("/")
                        work["title"] = parts[0].strip()
                        if len(parts) > 1:
                            work["title_cn"] = parts[1].strip()

                    # Save to cache
                    if self.use_cache:
                        self._save_cache(url, work)

                    return work
                else:
                    logger.error(f"Firecrawl returned unexpected format: {data}")

            elif resp.status_code == 429:
                # Rate limit - exponential backoff retry
                if retry_count >= max_retries:
                    logger.error(f"Max retries exceeded: {url}")
                    return None
                wait_time = 2**retry_count  # 1s, 2s, 4s
                logger.warning(f"Rate limited, waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                return self.extract_work_details(url, retry_count + 1)

            else:
                logger.error(f"Firecrawl Error {resp.status_code}: {resp.text[:200]}")

            return None

        except Exception as e:
            logger.error(f"API request error {url}: {e}")
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

