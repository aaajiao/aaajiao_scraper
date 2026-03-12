# AGENTS.md

This file provides guidance for Codex when working with this repository.

## Repository Snapshot

As of 2026-03-12, this repository is no longer just the Python scraper. It now has two active product surfaces:

1. `aaajiao Portfolio Scraper` (`v6.6.0`) - the Python scraper and Streamlit GUI.
2. `aaajiao Importer for macOS` - a local-only menu bar app with a bundled Python helper, review queue, and explicit git writeback flow.

Recent work has been concentrated in `macos/`:

- workspace bootstrap/reset and baseline refresh from GitHub `main`
- stricter OpenAI validation and local re-validation gates
- simpler review/apply workflow in the menu bar app
- managed publish repo flow when the source repo is dirty
- image URL review support
- offline wheelhouse packaging and acceptance/release checks

Current repository state worth keeping in mind:

- `main` is clean at the time of this snapshot
- the test suite contains about 136 test cases across scraper and macOS helper paths
- local test execution requires project dependencies plus `pytest-cov`; without them, `pytest` fails during argument parsing or import collection

## Project Overview

**aaajiao Portfolio Scraper** is a Python-based extractor for artwork metadata from `eventstructure.com`.
It uses a two-layer hybrid extraction strategy with SPA-aware validation, contamination cleanup, caching,
and report generation.

**aaajiao Importer for macOS** wraps the scraper in a local-only review workflow:

- bootstrap a dedicated workspace from bundled seed data
- refresh the data baseline from GitHub when safe
- run incremental sync or manual URL import
- review `ready_for_review` and `needs_review` records
- preview and explicitly confirm the git writeback transaction

## Tech Stack

- **Python**: 3.9+
- **Python UI**: Streamlit (`app.py`)
- **Scraping**: `requests`, BeautifulSoup4, Firecrawl API v2
- **Validation**: Pydantic v2
- **macOS app**: Swift, AppKit, SwiftUI
- **macOS helper runtime**: bundled Python engine in `macos/Helper/aaajiao_importer.py`
- **Storage**: JSON, Markdown, SQLite (`jobs.sqlite` in importer workspace), `.cache/`
- **Tooling**: pytest, pytest-cov, ruff, black, mypy

## Project Structure

```text
aaajiao_scraper/
├── scraper/                        # Core Python scraper package
│   ├── __init__.py                 # AaajiaoScraper + pipeline entrypoints
│   ├── core.py                     # Session, retries, rate limiter, credit usage
│   ├── basic.py                    # Sitemap parsing, BS4 extraction, URL filtering
│   ├── firecrawl.py                # Firecrawl v2 extraction, Map, Scrape+JSON, validation
│   ├── cache.py                    # General/sitemap/extract/discovery caches
│   ├── report.py                   # JSON/Markdown/agent report generation
│   └── constants.py                # Schemas, prompts, SPA config, defaults
├── app.py                          # Streamlit GUI in Chinese
├── macos/                          # Local-only macOS importer app
│   ├── App/                        # Swift menu bar UI
│   ├── Helper/                     # Bundled Python importer engine
│   ├── HelperBridge/               # Swift bridge executable for helper calls
│   ├── Shared/                     # DTOs shared across Swift targets
│   ├── Build/                      # Build, smoke, acceptance, release scripts
│   ├── Seed/                       # Seed data + seed manifest for workspace bootstrap
│   ├── Vendor/wheelhouse/          # Offline Python wheels for app runtime
│   └── README.md                   # macOS workflow and packaging notes
├── scripts/                        # Data cleanup, verification, update scripts
├── tests/                          # Python scraper + macOS helper tests
├── examples/                       # Example usage
├── aaajiao_works.json              # Generated artwork dataset
├── aaajiao_portfolio.md            # Generated Markdown portfolio
├── README.md                       # User-facing project readme
├── CLAUDE.md                       # Entry point that shares AGENTS guidance
└── pyproject.toml                  # Dependencies and tool configuration
```

## Main Workflows

### Python scraper workflow

1. Discover URLs from sitemap or Firecrawl Map.
2. Run Layer 1 local extraction for authoritative structural fields.
3. Run Layer 2 Firecrawl Extract v2 with schema validation.
4. Accept or reject Layer 2 content via title and contamination validation.
5. Deduplicate leaked materials and descriptions post-pipeline.
6. Save JSON/Markdown reports and optional image reports.

### macOS importer workflow

1. Build a local app bundle from the repo snapshot and wheelhouse.
2. Bootstrap a workspace from bundled seed data.
3. Refresh `aaajiao_works.json` and `aaajiao_portfolio.md` baseline from GitHub `main` when no review is pending.
4. Submit incremental sync or a manual artwork URL.
5. Review records in the app.
6. Preview the apply transaction.
7. Apply accepted records back to the repo or managed publish repo via explicit git operations.

## Architecture

### Python scraper mixin pattern

`AaajiaoScraper` combines behavior through multiple mixins:

```text
AaajiaoScraper
├── CoreScraper
├── BasicScraperMixin
├── FirecrawlMixin
├── CacheMixin
└── ReportMixin
```

### Two-layer hybrid extraction strategy

The main extraction path is `extract_work_details_v2(url)`.

1. **Layer 0**: cache hit, plus cleanup of stale title issues
2. **Layer 1**: local BeautifulSoup parsing for `year`, `type`, `images`, and title baseline
3. **Layer 2**: Firecrawl Extract API v2 with Pydantic schema, with fallback to Scrape+JSON
4. **Post-pipeline**: cross-contamination cleanup over the full work set

Authoritative field split:

- **Layer 1 authoritative**: `year`, `type`, `images`
- **Layer 1 validation baseline**: `title`
- **Layer 2 authoritative when validated**: `title`, `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`

### SPA content validation chain

Layer 2 output must pass:

1. `_is_type_string()`
2. `_is_known_sidebar_title()`
3. `_validate_title_against_url()`
4. `_titles_are_similar()`
5. content gating for materials and descriptions when title fails
6. `_is_description_contaminated()`
7. `_clean_cross_contamination()` after the pipeline completes

### macOS importer validation flow

The macOS helper uses a two-stage gate before a record becomes reviewable:

1. OpenAI returns a strict structured validation payload for `artwork`, `exhibition`, or `unknown`.
2. The local helper re-checks slug/title consistency, type-as-title mistakes, contamination signals,
   and required-field completeness.

The helper maintains workspace state in SQLite and JSON manifests. It intentionally avoids mutating
the repository until the user confirms the apply step.

## Key Entry Points

### Python

- `run_full_pipeline()` - end-to-end extraction and save flow
- `extract_work_details_v2(url)` - current recommended artwork extraction path
- `scrape_with_json(url)` - synchronous structured fallback
- `discover_urls_with_map()` - fast URL discovery with Firecrawl Map v2
- `agent_search(urls)` - agent/batch extraction mode
- `get_credit_usage()` - Firecrawl credit balance lookup

### macOS helper commands

The helper currently exposes:

- `bootstrapWorkspace`
- `resetWorkspace`
- `refreshWorkspaceBaseline`
- `startIncrementalSync`
- `submitManualURL`
- `listPendingRecords`
- `acceptRecord`
- `rejectRecord`
- `getApplyPreview`
- `applyAcceptedRecords`
- `deleteBatch`

These map to functions such as `bootstrap_workspace()`, `reset_workspace()`,
`refresh_workspace_baseline()`, `submit_manual_url()`, `list_pending_records()`,
`accept_record()`, `reject_record()`, `get_apply_preview()`, `apply_accepted_records()`,
and `delete_batch()`.

## Common Commands

### Python app and scraper

```bash
streamlit run app.py
./start_gui.command
python3 -m pytest tests/ -v
python3 -m pytest tests/ --cov=scraper --cov-report=html
ruff format .
ruff check .
mypy scraper/
pip install -e .
pip install -e ".[dev]"
```

### macOS build and validation

```bash
./macos/Build/refresh_wheelhouse.sh
./macos/Build/verify_wheelhouse.sh
./macos/Build/prepare_seed.sh
./macos/Build/build_local_app.sh
./macos/Build/smoke_test_app.sh
./macos/Build/run_acceptance_checks.sh
./macos/Build/run_git_transaction_checks.sh
./macos/Build/run_live_import_check.sh
./macos/Build/check_repo_apply_prereqs.sh
```

Release process reference:

```bash
open macos/Build/RELEASE_CHECKLIST.md
```

## Environment Variables

### Python scraper

Required for AI extraction:

```bash
FIRECRAWL_API_KEY=your_api_key_here
```

Optional:

```bash
CACHE_ENABLED=true
RATE_LIMIT_CALLS_PER_MINUTE=10
```

### macOS importer

Common variables:

```bash
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1
AAAJIAO_IMPORTER_WORKSPACE_ROOT=/path/to/workspace
AAAJIAO_IMPORTER_BUNDLE_ROOT=/path/to/bundle/resources
AAAJIAO_REPO_ROOT=/Users/aaajiao/Documents/aaajiao_scraper
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL=https://github.com/aaajiao/aaajiao_scraper.git
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH=main
```

Notes:

- missing `OPENAI_API_KEY` does not block imports entirely; records can still land in `needs_review`
- default OpenAI model in the helper is `gpt-4.1`

## Testing Notes

- `pyproject.toml` injects coverage arguments via `addopts`, so plain `pytest` expects `pytest-cov` to be installed.
- A bare system Python without `requests`, `beautifulsoup4`, and other runtime deps will fail during test collection.
- The expected setup for local validation is `pip install -e ".[dev]"`.
- If you need a quick run without coverage flags, use `python3 -m pytest tests/ -o addopts=`, but runtime deps still need to be present.
- `tests/test_macos_helper.py` is the main regression suite for workspace lifecycle, baseline sync, review queues, and git apply behavior.

## Key Patterns

- **Incremental updates**: use sitemap `lastmod` and cache metadata to skip unchanged pages
- **Rate limiting**: thread-safe limiter, default 10 calls per minute
- **Retry logic**: exponential backoff for HTTP/API operations
- **Silent cache failure**: cache issues should not block scraping
- **SPA-aware extraction**: `waitFor`, `excludeTags`, `onlyMainContent`, and actions are part of Firecrawl requests
- **Validation before acceptance**: title validation gates content acceptance
- **Cross-contamination cleanup**: repeated leaked materials/descriptions are cleared post-pipeline
- **Workspace isolation**: macOS app performs processing in a separate workspace until explicit apply
- **Managed publish repo fallback**: macOS helper can publish through a dedicated workspace repo when the source repo is dirty
- **Offline packaging**: wheelhouse-backed runtime is required for distributable macOS builds

## Output and Generated Artifacts

Generated or regenerated artifacts include:

- `aaajiao_works.json`
- `aaajiao_portfolio.md`
- `.cache/`
- `reports/`
- `output/`
- `output/images/`
- `macos/Seed/seed_manifest.json`
- importer workspace `workspace_manifest.json`
- importer workspace `jobs.sqlite`

## Known Site-Specific Risks

`eventstructure.com` is a Cargo Collective SPA. Main failure modes are:

1. sidebar title pollution
2. cross-work materials/description contamination
3. delayed SPA rendering

The repository already contains mitigation for all three, so new extraction changes should preserve
the validation chain unless there is a strong reason to rework it.

## Important Notes

- The Streamlit GUI is in Simplified Chinese.
- Prefer `extract_work_details_v2()` over the legacy `extract_work_details()`.
- All Firecrawl endpoints should stay on v2.
- The macOS app is intentionally local-only and should not mutate the repo automatically outside explicit apply flows.
- If you change seed, workspace, build, or apply behavior in `macos/`, update `macos/README.md` and `macos/Build/RELEASE_CHECKLIST.md` together.
