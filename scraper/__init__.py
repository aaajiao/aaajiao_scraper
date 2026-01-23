import json
import concurrent.futures
from typing import Any, Callable, Dict, List, Optional

from .core import CoreScraper, RateLimiter, deduplicate_works
from .basic import (
    BasicScraperMixin,
    is_artwork,
    normalize_year,
    parse_size_duration,
    is_extraction_complete,
    EXCLUDED_TYPES,
)
from .firecrawl import FirecrawlMixin
from .cache import CacheMixin
from .report import ReportMixin
from .constants import CACHE_DIR, PROMPT_TEMPLATES, QUICK_SCHEMA, FULL_SCHEMA


class AaajiaoScraper(CoreScraper, BasicScraperMixin, FirecrawlMixin, CacheMixin, ReportMixin):
    """
    Facade class combining all scraper functionalities.
    Inherits from:
    - CoreScraper: Session, Config
    - BasicScraperMixin: Sitemap, HTML parsing
    - FirecrawlMixin: extract_work_details, agent_search, discovery
    - CacheMixin: Caching utilities
    - ReportMixin: Markdown/JSON generation
    """

    # Re-expose constants for external access if needed (e.g. app.py access to PROMPT_TEMPLATES)
    PROMPT_TEMPLATES = PROMPT_TEMPLATES
    QUICK_SCHEMA = QUICK_SCHEMA
    FULL_SCHEMA = FULL_SCHEMA

    def __init__(self, use_cache: bool = True):
        super().__init__(use_cache=use_cache)

    def run_full_pipeline(
        self,
        incremental: bool = True,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> Dict[str, Any]:
        """Run the complete scraping pipeline: fetch → extract → filter → save.

        This is the main entry point for one-click scraping. It handles:
        1. Fetching URLs from sitemap (incremental or full)
        2. Concurrent extraction with three-tier cost optimization
        3. Automatic filtering of exhibitions and catalogs
        4. Deduplication and saving to JSON/Markdown

        Args:
            incremental: If True, only process new/updated URLs based on sitemap lastmod.
                Defaults to True.
            max_workers: Number of concurrent workers for extraction.
                Defaults to 4.
            progress_callback: Optional callback function(message: str, progress: float).
                Progress is a float from 0.0 to 1.0.

        Returns:
            Dictionary with:
                - works: List of extracted artwork dictionaries
                - stats: Statistics dictionary with counts
                - files: List of generated file paths

        Example:
            >>> scraper = AaajiaoScraper()
            >>> result = scraper.run_full_pipeline(incremental=True)
            >>> print(f"Scraped {result['stats']['total']} works")
        """
        import logging

        logger = logging.getLogger(__name__)

        def _progress(msg: str, pct: float) -> None:
            logger.info(f"[{pct*100:.0f}%] {msg}")
            if progress_callback:
                progress_callback(msg, pct)

        stats = {
            "urls_found": 0,
            "extracted": 0,
            "skipped_exhibitions": 0,
            "failed": 0,
            "from_cache": 0,
            "total": 0,
        }

        # ===== Step 1: Get URLs =====
        _progress("Fetching sitemap...", 0.0)
        urls = self.get_all_work_links(incremental=incremental)
        stats["urls_found"] = len(urls)

        if not urls:
            _progress("No URLs to process", 0.1)
            # Load existing works if incremental mode found nothing new
            if incremental:
                try:
                    with open("aaajiao_works.json", "r", encoding="utf-8") as f:
                        self.works = json.load(f)
                        stats["total"] = len(self.works)
                        stats["from_cache"] = len(self.works)
                except FileNotFoundError:
                    pass

            return {
                "works": self.works,
                "stats": stats,
                "files": [],
            }

        _progress(f"Found {len(urls)} URLs to process", 0.1)

        # ===== Step 2: Concurrent Extraction =====
        extracted_works: List[Dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(self.extract_work_details, url): url for url in urls
            }

            completed = 0
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                completed += 1
                progress = 0.1 + 0.7 * (completed / len(urls))

                try:
                    data = future.result()
                    if data:
                        extracted_works.append(data)
                        stats["extracted"] += 1
                        _progress(f"[{completed}/{len(urls)}] ✅ {data.get('title', 'Unknown')[:30]}", progress)
                    else:
                        # None means exhibition/catalog or failed
                        stats["skipped_exhibitions"] += 1
                        _progress(f"[{completed}/{len(urls)}] ⏭️ Skipped: {url.split('/')[-1][:30]}", progress)
                except Exception as e:
                    stats["failed"] += 1
                    logger.error(f"Error extracting {url}: {e}")
                    _progress(f"[{completed}/{len(urls)}] ❌ Failed: {url.split('/')[-1][:30]}", progress)

        # ===== Step 3: Merge with existing data (incremental mode) =====
        _progress("Merging and deduplicating...", 0.85)

        if incremental:
            try:
                with open("aaajiao_works.json", "r", encoding="utf-8") as f:
                    existing_works = json.load(f)
                    # Merge: new works take precedence
                    existing_urls = {w.get("url") for w in extracted_works}
                    for work in existing_works:
                        if work.get("url") not in existing_urls:
                            extracted_works.append(work)
            except FileNotFoundError:
                pass

        # Deduplicate
        self.works = deduplicate_works(extracted_works)
        stats["total"] = len(self.works)

        # ===== Step 4: Save outputs =====
        _progress("Saving files...", 0.9)
        output_files = []

        # Save JSON
        self.save_to_json()
        output_files.append("aaajiao_works.json")

        # Generate Markdown
        self.generate_markdown()
        output_files.append("aaajiao_portfolio.md")

        _progress(f"Complete! {stats['total']} works saved", 1.0)

        return {
            "works": self.works,
            "stats": stats,
            "files": output_files,
        }
