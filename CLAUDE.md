# CLAUDE.md

This file provides guidance for Claude Code when working with this repository.

## Project Overview

**aaajiao Portfolio Scraper** (v6.1.0) - A Python-based web scraper for extracting artwork metadata from eventstructure.com. It implements a multi-tiered extraction strategy to minimize API costs while maintaining data quality, with intelligent caching and structured output generation.

## Tech Stack

- **Language**: Python 3.9+
- **Web Framework**: Streamlit (GUI in `app.py`)
- **Web Scraping**: BeautifulSoup4 (local parsing), Firecrawl API v2 (AI extraction)
- **Dependencies**: requests, tqdm, pandas, python-dotenv
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
│   ├── generate_web_report.py  # Web report generation
│   └── verify_portfolio.py     # Data validation
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

### Three-Tier Extraction Strategy (Cost Optimization)

1. **Layer 0**: Cache check (free)
2. **Layer 1**: Local BeautifulSoup parsing (0 credits)
3. **Layer 2**: Markdown scrape + regex enrichment (1 credit)
4. **Layer 3**: LLM extraction via Firecrawl (2 credits, last resort)

### Key Methods

- **`run_full_pipeline()`** - Main one-click extraction with incremental support
- **`extract_work_details(url)`** - Multi-layer extraction with automatic fallback
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
| `batch_update_works.py` | Bulk markdown scraping with regex parsing (supports dry-run) |
| `clean_size_materials.py` | Extract size/duration from materials field |
| `generate_web_report.py` | Generate web-based reports |
| `verify_portfolio.py` | Validate portfolio data integrity |

## Output Files

Generated files (gitignored, can be regenerated):
- `aaajiao_works.json` - Structured artwork data
- `aaajiao_portfolio.md` - Markdown portfolio document
- `.cache/` - Multi-level cache directory
- `output/` - Basic scraper output
- `output/images/` - Downloaded artwork images

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
