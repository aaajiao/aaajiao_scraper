"""Shared path helpers for the Python product surface."""

from __future__ import annotations

from pathlib import Path
from typing import Union

PathLike = Union[str, Path]

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCT_ROOT.parent

WORKS_JSON_NAME = "aaajiao_works.json"
PORTFOLIO_MARKDOWN_NAME = "aaajiao_portfolio.md"

WORKS_JSON_PATH = REPO_ROOT / WORKS_JSON_NAME
PORTFOLIO_MARKDOWN_PATH = REPO_ROOT / PORTFOLIO_MARKDOWN_NAME
OUTPUT_DIR = PRODUCT_ROOT / "output"
REPORTS_DIR = PRODUCT_ROOT / "reports"


def resolve_repo_path(path: PathLike) -> Path:
    """Resolve a repo-relative path while preserving absolute paths."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def resolve_product_path(path: PathLike) -> Path:
    """Resolve a product-relative path while preserving absolute paths."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PRODUCT_ROOT / candidate


def resolve_shared_artifact_path(path: PathLike) -> Path:
    """Resolve shared repo artifacts and other relative repo paths."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.as_posix() == WORKS_JSON_NAME:
        return WORKS_JSON_PATH
    if candidate.as_posix() == PORTFOLIO_MARKDOWN_NAME:
        return PORTFOLIO_MARKDOWN_PATH
    return REPO_ROOT / candidate
