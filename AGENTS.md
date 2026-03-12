# AGENTS.md

This file provides guidance for Codex when working with this repository.

## Repository Snapshot

As of 2026-03-12, this repo is an umbrella repository with two parallel product surfaces:

1. `portfolio_scraper/`
   The Python scraper, Streamlit GUI, scripts, examples, and Python-side tests.
2. `macos/`
   The local-only macOS importer app with bundled Python helper, review queue, baseline refresh, and explicit git apply flow.

Shared data artifacts remain at the repository root:

- `aaajiao_works.json`
- `aaajiao_portfolio.md`

Recent work has been concentrated in `macos/`, but the Python scraper remains an active product surface rather than legacy code.

## Project Structure

```text
aaajiao_scraper/
├── portfolio_scraper/
│   ├── app.py                          # Streamlit GUI in Chinese
│   ├── scraper/                        # Core Python scraper package
│   ├── scripts/                        # Cleanup, verification, batch scripts
│   ├── examples/                       # Example usage
│   ├── tests/                          # Python scraper tests
│   └── README.md                       # Python product-line docs
├── macos/                              # Local-only macOS importer app
│   ├── App/
│   ├── Helper/
│   ├── HelperBridge/
│   ├── Shared/
│   ├── Build/
│   ├── Seed/
│   ├── Vendor/wheelhouse/
│   └── README.md
├── tests/
│   └── test_macos_helper.py            # macOS helper regression suite
├── aaajiao_works.json                  # Shared artwork dataset
├── aaajiao_portfolio.md                # Shared Markdown portfolio
├── README.md                           # Umbrella repo overview
├── CLAUDE.md                           # Entry point to shared agent guidance
└── pyproject.toml                      # Root packaging/tool config
```

## Python Scraper Notes

Core package import path remains `scraper`, even though the product root moved under `portfolio_scraper/`.

Important entrypoints:

- `run_full_pipeline()`
- `extract_work_details_v2(url)`
- `scrape_with_json(url)`
- `discover_urls_with_map()`
- `agent_search(urls)`
- `get_credit_usage()`

Path handling was normalized during the umbrella-repo refactor:

- shared artifacts resolve to the repository root through `portfolio_scraper/scraper/paths.py`
- scripts under `portfolio_scraper/scripts/` should not assume the current working directory is the repo root
- `portfolio_scraper/output/` and `portfolio_scraper/reports/` stay inside the Python product surface

## macOS Importer Notes

The macOS app still uses:

- root-level `aaajiao_works.json`
- root-level `aaajiao_portfolio.md`
- a seed snapshot of the Python package copied from `portfolio_scraper/scraper/`

Do not change importer behavior to write into the repo automatically outside the explicit apply flow.

If you change seed/build/apply behavior in `macos/`, update:

- `macos/README.md`
- `macos/Build/RELEASE_CHECKLIST.md`

## Common Commands

### Python product surface

```bash
./start_gui.command
python3 -m streamlit run portfolio_scraper/app.py
python3 -m pytest portfolio_scraper/tests/ -v
python3 -m pytest portfolio_scraper/tests/ --cov=portfolio_scraper/scraper --cov-report=html
ruff format portfolio_scraper
ruff check portfolio_scraper
mypy portfolio_scraper/scraper/
pip install -e .
pip install -e ".[dev]"
```

### macOS product surface

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
python3 -m pytest tests/test_macos_helper.py -v
```

## Testing Notes

- `pyproject.toml` still injects coverage arguments via `addopts`, so plain `pytest` expects `pytest-cov`.
- Python-side tests live in `portfolio_scraper/tests/`.
- `tests/test_macos_helper.py` is the main regression suite for workspace lifecycle, baseline sync, review queues, and git apply behavior.
- A quick non-coverage run can still use:

```bash
python3 -m pytest portfolio_scraper/tests/ tests/test_macos_helper.py -o addopts=
```

## Important Constraints

- Prefer `extract_work_details_v2()` over the legacy extraction path.
- Keep Firecrawl usage on v2 endpoints.
- The Streamlit GUI is in Simplified Chinese.
- The macOS app is intentionally local-only and should not mutate the repo outside explicit apply flows.
- Root shared artifacts should stay at the repository root unless the importer contract is intentionally redesigned.
