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


def _clean_cross_contamination(works: List[Dict[str, Any]]) -> int:
    """Detect and clean cross-contaminated fields across works.

    In SPA sites, the LLM sometimes extracts materials/descriptions from
    adjacent works. This manifests as identical materials or descriptions
    appearing in multiple unrelated works.

    Detection: If the same non-trivial materials string appears in 3+ works,
    it's likely contamination from one source work. We keep it on the work
    whose title/URL best matches, and clear it from the rest.

    Same logic applies to descriptions.

    Args:
        works: List of work dictionaries to clean.

    Returns:
        Number of fields that were cleaned.
    """
    import logging
    from collections import Counter

    logger = logging.getLogger(__name__)
    cleaned = 0

    # --- Materials deduplication ---
    materials_counter: Dict[str, List[int]] = {}
    for idx, work in enumerate(works):
        mat = (work.get("materials") or "").strip()
        if mat and len(mat) > 15:  # Only check non-trivial materials
            materials_counter.setdefault(mat, []).append(idx)

    for mat, indices in materials_counter.items():
        if len(indices) >= 3:
            # Same materials in 3+ works = contamination
            # Find which work it actually belongs to (best URL/title match)
            best_idx = None
            best_score = -1
            mat_lower = mat.lower()
            for idx in indices:
                work = works[idx]
                title = (work.get("title") or "").lower()
                url = (work.get("url") or "").lower()
                # Heuristic: if description also exists and is unique, it's the real work
                desc = (work.get("description_en") or "").strip()
                score = 0
                if desc and len(desc) > 50:
                    # Check if this description is unique to this work
                    desc_count = sum(
                        1 for w in works
                        if (w.get("description_en") or "").strip() == desc
                    )
                    if desc_count == 1:
                        score += 10  # Strong signal: unique description
                # Check if materials keyword matches the work type/title
                if any(kw in mat_lower for kw in title.split() if len(kw) > 3):
                    score += 5
                if score > best_score:
                    best_score = score
                    best_idx = idx

            # Clear materials from all except the best match
            for idx in indices:
                if idx != best_idx:
                    logger.info(
                        f"🧹 Cleaning contaminated materials from "
                        f"'{works[idx].get('title', 'Unknown')}': {mat[:40]}..."
                    )
                    works[idx]["materials"] = ""
                    cleaned += 1

    # --- Description deduplication ---
    for desc_field in ("description_en", "description_cn"):
        desc_counter: Dict[str, List[int]] = {}
        for idx, work in enumerate(works):
            desc = (work.get(desc_field) or "").strip()
            if desc and len(desc) > 30:  # Only check non-trivial descriptions
                desc_counter.setdefault(desc, []).append(idx)

        for desc, indices in desc_counter.items():
            if len(indices) >= 2:
                # Same description in 2+ works = contamination
                # Find which work it belongs to by checking title mention in desc
                desc_lower = desc.lower()
                best_idx = None
                best_score = -1

                for idx in indices:
                    work = works[idx]
                    title = (work.get("title") or "").lower()
                    url_slug = (work.get("url") or "").rstrip("/").split("/")[-1]
                    slug = url_slug.replace("-", " ").replace("_", " ").lower()
                    score = 0

                    # Description mentions this work's title
                    if title and len(title) > 2 and title in desc_lower:
                        score += 10
                    # Description mentions this work's URL slug
                    if slug and len(slug) > 3 and slug in desc_lower:
                        score += 8
                    # Work has unique materials (not contaminated)
                    mat = (work.get("materials") or "").strip()
                    if mat:
                        mat_count = sum(
                            1 for w in works
                            if (w.get("materials") or "").strip() == mat
                        )
                        if mat_count == 1:
                            score += 5

                    if score > best_score:
                        best_score = score
                        best_idx = idx

                for idx in indices:
                    if idx != best_idx:
                        logger.info(
                            f"🧹 Cleaning contaminated {desc_field} from "
                            f"'{works[idx].get('title', 'Unknown')}': {desc[:40]}..."
                        )
                        works[idx][desc_field] = ""
                        cleaned += 1

    return cleaned


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
        2. Concurrent extraction with two-layer hybrid strategy
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

        # Ensure URLs are unique (safety check)
        unique_urls = list(dict.fromkeys(urls))  # Preserves order, removes duplicates
        if len(unique_urls) != len(urls):
            logger.warning(f"⚠️ Removed {len(urls) - len(unique_urls)} duplicate URLs")
        urls = unique_urls

        _progress(f"Found {len(urls)} URLs to process", 0.1)

        # ===== Step 2: Concurrent Extraction =====
        extracted_works: List[Dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all jobs and build mapping
            future_to_url = {}
            for url in urls:
                future = executor.submit(self.extract_work_details_v2, url)
                future_to_url[future] = url

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

        # ===== Step 3.5: Cross-contamination cleanup =====
        _progress("Checking for cross-contamination...", 0.88)
        contamination_count = _clean_cross_contamination(self.works)
        if contamination_count:
            stats["contamination_cleaned"] = contamination_count
            logger.info(f"🧹 Cleaned {contamination_count} cross-contaminated fields")

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
