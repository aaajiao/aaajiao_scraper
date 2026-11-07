"""Build helper test inputs from tracked sources, without a local app build."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def helper_seed_bundle(tmp_path_factory):
    repo = Path(__file__).resolve().parents[1]
    bundle = tmp_path_factory.mktemp("helper-test-bundle")
    seed = bundle / "Seed"
    (seed / "cache").mkdir(parents=True)
    for name in ("aaajiao_works.json", "aaajiao_portfolio.md"):
        shutil.copy2(repo / name, seed / name)
    (seed / "cache" / "sitemap_lastmod.json").write_text("{}\n", encoding="utf-8")
    shutil.copytree(
        repo / "portfolio_scraper" / "scraper",
        bundle / "python_snapshot" / "scraper",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return bundle


@pytest.fixture(autouse=True)
def isolated_helper_bundle(helper_seed_bundle, monkeypatch):
    monkeypatch.setenv("AAAJIAO_IMPORTER_BUNDLE_ROOT", str(helper_seed_bundle))
