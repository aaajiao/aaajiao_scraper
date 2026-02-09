# CLAUDE.md

This file provides guidance for Claude Code when working with this repository.

## Project Overview

**aaajiao Portfolio Scraper** (v6.6.0) - A Python-based web scraper for extracting artwork metadata from eventstructure.com. It implements a two-layer hybrid extraction strategy (Strategy B) with SPA content validation and cross-contamination detection, combining local parsing with AI-powered schema extraction.

## Tech Stack

- **Language**: Python 3.9+
- **Web Framework**: Streamlit (GUI in `app.py`)
- **Web Scraping**: BeautifulSoup4 (local parsing), Firecrawl API v2 (AI extraction)
- **Schema Validation**: Pydantic v2 (structured extraction schemas)
- **Dependencies**: requests, tqdm, pandas, python-dotenv, pydantic
- **Testing**: pytest with coverage (106 tests, 55%+ coverage)
- **Linting**: ruff, black, mypy

## Project Structure

```
aaajiao_scraper/
├── scraper/                      # Core scraper package
│   ├── __init__.py              # Main entry - exports AaajiaoScraper + cross-contamination cleanup
│   ├── core.py                  # RateLimiter, CoreScraper base class
│   ├── basic.py                 # HTML parsing, sitemap, URL validation
│   ├── firecrawl.py             # Firecrawl API integration (LLM extraction)
│   ├── cache.py                 # Multi-level caching system
│   ├── report.py                # JSON/Markdown/agent report generation
│   └── constants.py             # Schemas, prompts, SPA config, configuration
├── app.py                       # Streamlit GUI (Chinese interface)
├── tests/                       # Test suite
│   ├── conftest.py             # pytest fixtures
│   ├── test_core.py            # Core functionality tests
│   ├── test_cache.py           # Cache system tests
│   ├── test_basic.py           # HTML parsing tests
│   ├── test_firecrawl.py       # API integration tests (incl. Map, Scrape+JSON, contamination)
│   └── test_report.py          # Report generation tests
├── scripts/                     # Utility scripts
│   ├── batch_update_works.py   # Bulk two-layer extraction (supports dry-run, --force)
│   ├── clean_size_materials.py # Extract size/duration from materials
│   ├── clean_materials_credits.py # Clean materials and credits fields
│   ├── generate_web_report.py  # Web report generation
│   ├── firecrawl_test.py       # Firecrawl API testing
│   ├── update_scraper.py       # Scraper update utilities
│   └── verify_portfolio.py     # Data validation
├── reports/                     # Generated markdown reports
├── examples/                    # Usage examples
│   ├── quick_start.py
│   ├── batch_extraction.py
│   └── incremental_scrape.py
├── pyproject.toml              # Project config, dependencies
├── .ruff.toml                  # Ruff linting config
└── .env.example                # Environment template
```

## Common Commands

### Running the Application

```bash
# Start Streamlit GUI
streamlit run app.py

# Or use the convenience script
./start_gui.command
```

### Testing

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage report
python3 -m pytest tests/ --cov=scraper --cov-report=html

# Run specific test file
python3 -m pytest tests/test_core.py -v
```

### Code Quality

```bash
# Format code
ruff format .

# Lint check
ruff check .

# Type checking
mypy scraper/
```

### Installation

```bash
# Install package in editable mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

## Architecture

### Mixin Pattern

`AaajiaoScraper` combines functionality through multiple mixins:

```
AaajiaoScraper
├── CoreScraper          # Session management, retries, API key loading
├── BasicScraperMixin    # Sitemap parsing, BS4 extraction, URL validation
├── FirecrawlMixin       # Firecrawl API, agent search, batch extraction
├── CacheMixin           # Multi-level caching (sitemap, extract, discovery)
└── ReportMixin          # JSON, Markdown, agent report generation
```

### Two-Layer Hybrid Extraction Strategy (Strategy B)

The extraction strategy maximizes accuracy through mandatory AI verification with SPA content validation:

1. **Layer 0**: Cache check (free) — also applies title validation and type-as-title fix to stale cached data
2. **Layer 1**: Local BeautifulSoup parsing (0 credits) - filtering non-artwork pages + extracting authoritative fields + title baseline for validation
3. **Layer 2**: Firecrawl Extract API **v2** with Pydantic schema (~5 credits/extract) - provides content fields, with fallback to Scrape+JSON
4. **Post-pipeline**: Cross-contamination cleanup - deduplicates leaked materials/descriptions across works

**IMPORTANT: All Firecrawl API calls use v2 endpoints:**
- Extract: `https://api.firecrawl.dev/v2/extract`
- Scrape: `https://api.firecrawl.dev/v2/scrape`
- Map: `https://api.firecrawl.dev/v2/map`
- Agent: `https://api.firecrawl.dev/v2/agent`

**Field Priority (Strategy B):**
- **Layer 1 authoritative**: `year`, `type` (from tags, ~100% accurate), `images` (from slideshow container)
- **Layer 1 validation**: `title` (used as baseline to validate Layer 2's title)
- **Layer 2 authoritative**: `title` (if validated), `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`
- **Layer 2 gated**: If title validation fails, materials and descriptions are also rejected (SPA contamination)

**SPA Content Validation Chain:**
Layer 2 data must pass validation before being accepted:
1. `_is_type_string()` - Reject type strings like "video installation" as titles
2. `_is_known_sidebar_title()` - Reject sidebar navigation items on wrong pages
3. `_validate_title_against_url()` - Validate title matches URL slug
4. `_titles_are_similar()` - Fuzzy match with Layer 1 title
5. **Content gating** - If title rejected, materials + descriptions also rejected
6. `_is_description_contaminated()` - Detect cross-work description pollution
7. **Post-pipeline** `_clean_cross_contamination()` - Deduplicate leaked fields across all works

If title validation fails, Layer 1 title is kept and Layer 2 content fields (except size/duration) are discarded to prevent SPA contamination.

### SPA-Aware Scraping

All Firecrawl API calls include SPA-aware parameters (configured in `constants.py`):
- **`waitFor`** (3000ms) - Wait for dynamic content to render before extraction
- **`excludeTags`** - Filter out sidebar navigation: `nav`, `.project_thumb:not(.active)`, `.sidebar`, `.menu`, `#navigation`, `.tags`
- **`onlyMainContent`** - Focus on the main content area
- **`actions`** - Wait actions for SPA content loading

### Key Methods

- **`run_full_pipeline()`** - Main one-click extraction with incremental support + cross-contamination cleanup
- **`extract_work_details_v2(url)`** - Optimized two-layer hybrid extraction with SPA content validation (recommended)
- **`extract_work_details(url)`** - [LEGACY] Old three-tier extraction (deprecated)
- **`scrape_markdown(url)`** - Low-cost Firecrawl scrape with SPA params (1 credit)
- **`scrape_with_json(url)`** - Synchronous structured extraction via Scrape+JSON format (no polling)
- **`discover_urls_with_map()`** - Fast URL discovery using Map API (~2-3 seconds)
- **`discover_urls_with_scroll()`** - Infinite-scroll URL discovery (legacy, slower)
- **`agent_search(urls)`** - Batch/agent mode intelligent search
- **`get_credit_usage()`** - Check Firecrawl API credit balance

### Title Validation Methods

- **`_is_type_string(title)`** - Check if title is actually an artwork type (e.g., "video installation")
- **`_is_known_sidebar_title(title, url)`** - Detect sidebar navigation pollution
- **`_validate_title_against_url(title, url)`** - Validate title matches URL slug
- **`_titles_are_similar(title1, title2)`** - Fuzzy title comparison
- **`_clean_duplicate_title(title, title_cn)`** - Clean up duplicate bilingual title patterns

### Content Validation Methods

- **`_is_description_contaminated(desc, url, local_data)`** - Detect cross-work description pollution (e.g., "Guard" description appearing on "Sacpe.data" page)
- **`_clean_cross_contamination(works)`** - Post-pipeline: detect identical materials in 3+ works or identical descriptions in 2+ works, keep originals, clear copies

### Data Validation Methods

- **`is_description_not_materials(text)`** - Detect descriptions misclassified as materials
- **`looks_like_credits(text)`** - Detect credits misclassified as materials
- **`is_valid_materials_line(line)`** - Validate materials field content

### Fallback Chain

The Extract API has a built-in fallback to Scrape+JSON:
1. **Extract API** (`/v2/extract`) - Async with polling, primary method
2. **Scrape+JSON** (`/v2/scrape` with JSON format) - Synchronous fallback on Extract failure/timeout
3. Both use the same `ArtworkSchema` and `ARTWORK_EXTRACT_PROMPT`

### Caching System

Four-level caching in `.cache/` directory:
- **General cache** - URL-based pickle caching
- **Sitemap cache** - JSON-based lastmod timestamps
- **Extract cache** - Prompt-specific extraction results
- **Discovery cache** - Discovered URLs with 24h TTL

## Environment Variables

Required in `.env`:
```
FIRECRAWL_API_KEY=your_api_key_here
```

Optional:
```
CACHE_ENABLED=true
RATE_LIMIT_CALLS_PER_MINUTE=10
```

## Streamlit GUI Features

1. **Status Dashboard** - Total works, size completion %, duration count
2. **One-Click Scraping** - Full pipeline with incremental mode and concurrency control
3. **File Downloads** - JSON and Markdown exports
4. **Data Preview** - DataFrame display of extracted works
5. **Image Tools** - Image enrichment and web report generation

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `batch_update_works.py` | Bulk update works using two-layer extraction (supports dry-run) |
| `fix_problematic_works.py` | Fix data issues: type null, duplicate titles, invalid materials |
| `verify_layer2.py` | Test Layer 2 (Firecrawl Extract) extraction quality |
| `clean_size_materials.py` | Extract size/duration from materials field |
| `clean_materials_credits.py` | Clean up materials and credits fields |
| `generate_web_report.py` | Generate web-based reports |
| `firecrawl_test.py` | Test Firecrawl API integration |
| `update_scraper.py` | Update scraper utilities |
| `verify_portfolio.py` | Validate portfolio data integrity |

## Output Files

Generated files (gitignored, can be regenerated):
- `aaajiao_works.json` - Structured artwork data
- `aaajiao_portfolio.md` - Markdown portfolio document
- `.cache/` - Multi-level cache directory
- `output/` - Basic scraper output
- `output/images/` - Downloaded artwork images
- `reports/` - Generated markdown reports

## Code Style

- Line length: 100 characters
- Google-style docstrings
- Full type annotations
- Imports sorted with isort (via ruff)

## Key Patterns

- **Incremental Updates** - Uses sitemap `lastmod` to skip unchanged works
- **Rate Limiting** - Thread-safe limiter (default 10 calls/min)
- **Retry Logic** - Automatic retries with exponential backoff (3x)
- **Concurrent Processing** - ThreadPoolExecutor for parallel extraction
- **Silent Failure** - Cache operations fail silently to avoid blocking
- **SPA Content Validation** - Title + materials + description validation chain prevents navigation pollution
- **Cross-Contamination Detection** - Post-pipeline deduplication of leaked fields
- **Materials Validation** - Filters out descriptions, credits, and invalid data from materials field
- **Title Deduplication** - Automatically cleans duplicate bilingual title patterns
- **Title-as-Type Fix** - Detects type strings used as titles, restores from URL slug
- **Fallback Extraction** - Extract API → Scrape+JSON on failure/timeout

## Known SPA Issues

eventstructure.com is built with Cargo Collective as a Single Page Application. This causes:

1. **Title pollution** - Sidebar navigation titles extracted instead of main content title. Mitigated by 4-step title validation chain.
2. **Content contamination** - Materials/descriptions from adjacent works (especially "Guard, I...", "One ritual", "Absurd Reality Check") leak into other works. Mitigated by:
   - Layer 2 content gating (reject content when title fails validation)
   - `_is_description_contaminated()` per-field validation
   - `_clean_cross_contamination()` post-pipeline deduplication
3. **SPA rendering** - Content loads dynamically. Mitigated by `waitFor` (3s) and `excludeTags` on all Firecrawl API calls.

## Important Notes

- The GUI interface is in Chinese (Simplified)
- Firecrawl API key is required for AI-powered extraction
- Local BS4 extraction works without API key but with limited accuracy
- Always prefer incremental mode for regular updates to minimize API costs

## API Cost Reference (Firecrawl v2)

| API | Cost | Notes |
|-----|------|-------|
| Scrape (markdown) | 1 credit/page | Raw content with SPA params |
| Scrape+JSON (structured) | ~5 credits/page | Synchronous, no polling |
| Extract v2 (schema) | ~5 credits/page | Async with polling, primary method |
| Map (URL discovery) | 1 credit | Fast (~2-3s), replaces scroll discovery |
| Agent v2 | Variable | For complex navigation scenarios |
| Estimated total | ~1,000 credits | For ~166 artworks (using v2) |

**Note:** All API calls use Firecrawl v2 endpoints. v1 endpoints are deprecated and should not be used.
