# CLAUDE.md

This file provides guidance for Claude Code when working with this repository.

## Project Overview

**aaajiao Portfolio Scraper** (v6.3.0) - A Python-based web scraper for extracting artwork metadata from eventstructure.com. It implements a two-layer hybrid extraction strategy combining local parsing with AI-powered schema extraction for 100% data accuracy.

## Tech Stack

- **Language**: Python 3.9+
- **Web Framework**: Streamlit (GUI in `app.py`)
- **Web Scraping**: BeautifulSoup4 (local parsing), Firecrawl API v2 (AI extraction)
- **Schema Validation**: Pydantic v2 (structured extraction schemas)
- **Dependencies**: requests, tqdm, pandas, python-dotenv, pydantic
- **Testing**: pytest with coverage (70+ tests, 90%+ coverage target)
- **Linting**: ruff, black, mypy

## Project Structure

```
aaajiao_scraper/
├── scraper/                      # Core scraper package
│   ├── __init__.py              # Main entry - exports AaajiaoScraper
│   ├── core.py                  # RateLimiter, CoreScraper base class
│   ├── basic.py                 # HTML parsing, sitemap, URL validation
│   ├── firecrawl.py             # Firecrawl API integration (LLM extraction)
│   ├── cache.py                 # Multi-level caching system
│   ├── report.py                # JSON/Markdown/agent report generation
│   └── constants.py             # Schemas, prompts, configuration
├── app.py                       # Streamlit GUI (Chinese interface)
├── tests/                       # Test suite
│   ├── conftest.py             # pytest fixtures
│   ├── test_core.py            # Core functionality tests
│   ├── test_cache.py           # Cache system tests
│   ├── test_basic.py           # HTML parsing tests
│   ├── test_firecrawl.py       # API integration tests
│   └── test_report.py          # Report generation tests
├── scripts/                     # Utility scripts
│   ├── batch_update_works.py   # Bulk markdown scraping (1 credit/page)
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

### Two-Layer Hybrid Extraction Strategy

The extraction strategy ensures 100% data accuracy through mandatory AI verification:

1. **Layer 0**: Cache check (free)
2. **Layer 1**: Local BeautifulSoup parsing (0 credits) - filtering non-artwork pages + extracting authoritative fields
3. **Layer 2**: Firecrawl Extract API **v2** with Pydantic schema (~5 credits/extract) - AI verification for ALL artworks

**IMPORTANT: All Firecrawl API calls use v2 endpoints:**
- Extract: `https://api.firecrawl.dev/v2/extract`
- Scrape: `https://api.firecrawl.dev/v2/scrape`
- Agent: `https://api.firecrawl.dev/v2/agent`

**Field Priority:**
- **Layer 1 authoritative**: `year`, `type` (from tags, ~100% accurate), `images` (from slideshow container)
- **Layer 2 authoritative**: `title`, `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`

All artworks go through Layer 2 verification. Layer 1 filters out non-artwork pages (exhibitions, catalogs) to save API costs.

### Key Methods

- **`run_full_pipeline()`** - Main one-click extraction with incremental support
- **`extract_work_details_v2(url)`** - Optimized two-layer hybrid extraction (recommended)
- **`extract_work_details(url)`** - [LEGACY] Old three-tier extraction (deprecated)
- **`scrape_markdown(url)`** - Low-cost Firecrawl scrape (1 credit)
- **`agent_search(urls)`** - Batch/agent mode intelligent search
- **`discover_urls_with_scroll()`** - Infinite-scroll URL discovery

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

## Important Notes

- The GUI interface is in Chinese (Simplified)
- Firecrawl API key is required for AI-powered extraction
- Local BS4 extraction works without API key but with limited accuracy
- Always prefer incremental mode for regular updates to minimize API costs

## API Cost Reference (Firecrawl v2)

| API | Cost | Notes |
|-----|------|-------|
| Scrape (markdown) | 1 credit/page | Raw content only |
| Extract v2 (schema) | ~5 credits/page | 10x cheaper than v1, higher accuracy |
| Agent v2 | Variable | For complex navigation scenarios |
| Estimated total | ~1,000 credits | For ~166 artworks (using v2) |

**Note:** All API calls use Firecrawl v2 endpoints. v1 endpoints are deprecated and should not be used.
