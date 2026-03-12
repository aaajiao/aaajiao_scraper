# aaajiao Scraper Repository

This repository is now an umbrella repo with two parallel product surfaces:

1. `portfolio_scraper/`
   Python scraper, Streamlit GUI, batch scripts, examples, and Python tests
2. `macos/`
   Local macOS importer with a workspace, review queue, baseline refresh, and explicit git apply flow

The repository root only keeps repo-level docs, shared data artifacts, and compatibility entrypoints:

- `aaajiao_works.json`
- `aaajiao_portfolio.md`
- `start_gui.command`
- `pyproject.toml`

## Directory Structure

```text
aaajiao_scraper/
├── portfolio_scraper/
│   ├── app.py
│   ├── scraper/
│   ├── scripts/
│   ├── examples/
│   ├── tests/
│   └── README.md
├── macos/
├── tests/
│   └── test_macos_helper.py
├── aaajiao_works.json
├── aaajiao_portfolio.md
├── start_gui.command
├── AGENTS.md
└── pyproject.toml
```

## Quick Start

Python product surface:

```bash
./start_gui.command
python3 -m pytest portfolio_scraper/tests/ -v
python portfolio_scraper/scripts/batch_update_works.py --limit 10 --dry-run
```

macOS product surface:

```bash
./macos/Build/prepare_seed.sh
./macos/Build/build_local_app.sh
python3 -m pytest tests/test_macos_helper.py -v
```

## Documentation

- Python scraper and GUI: [`portfolio_scraper/README.md`](portfolio_scraper/README.md)
- macOS importer: [`macos/README.md`](macos/README.md)
- Agent repository guidance: [`AGENTS.md`](AGENTS.md)

## Shared Artifacts

`aaajiao_works.json` and `aaajiao_portfolio.md` remain at the repository root.

- The Python scraper writes back to these two files by default
- The macOS importer also continues to treat these root-level files as the targets for seed data, baseline refresh, and apply operations
