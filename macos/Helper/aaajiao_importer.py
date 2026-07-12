#!/usr/bin/env python3
"""Local-only importer engine for the macOS menu bar app."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from requests import RequestException
from pydantic import BaseModel, ConfigDict, Field, ValidationError


APP_NAME = "AaajiaoImporter"
DEFAULT_REPO_ROOT = Path("/Users/aaajiao/Documents/aaajiao_scraper")
DEFAULT_OPENAI_MODEL = "gpt-4.1"
REPO_WORKS = "aaajiao_works.json"
REPO_PORTFOLIO = "aaajiao_portfolio.md"
TARGET_FILES = (REPO_WORKS, REPO_PORTFOLIO)
PUBLISH_REPO_DIR = "publish_repo"
BASELINE_REPO_DIR = "baseline_repo"
BASELINE_REMOTE_URL = "https://github.com/aaajiao/aaajiao_scraper.git"
BASELINE_REMOTE_BRANCH = "main"
AUTO_APPLY_CONFIDENCE = 0.85
SEED_MANIFEST_NAME = "seed_manifest.json"
WORKSPACE_MANIFEST_NAME = "workspace_manifest.json"
MANIFEST_VERSION = 1
AI_VALIDATION_NAME = "aaajiao_artwork_validation"
AI_VALIDATION_TIMEOUT = 120
GIT_LOCAL_TIMEOUT_SECONDS = 30
GIT_NETWORK_TIMEOUT_SECONDS = 120
PUBLISH_LOCK_NAME = "publish.lock"
KNOWN_ARTWORK_TYPES = {
    "installation",
    "video",
    "video installation",
    "performance",
    "sculpture",
    "painting",
    "drawing",
    "photography",
    "sound installation",
    "mixed media",
    "single channel video",
    "multi-channel video",
}
NORMALIZED_KNOWN_ARTWORK_TYPES = {
    re.sub(r"[^a-z0-9]+", " ", item.lower()).strip() for item in KNOWN_ARTWORK_TYPES
}
AI_VALIDATION_PROMPT = (
    "You validate one eventstructure.com page for a local artwork importer. "
    "Return structured JSON only. "
    "Classify page_type as artwork, exhibition, or unknown. "
    "Use artwork only when the page is a single artwork page. "
    "Reject sidebar/navigation pollution, wrong-title pages, cross-work contamination, "
    "and incomplete records that require manual review. "
    "Prefer base_data for deterministic fields such as year, type, and images when those fields are present. "
    "If you are unsure, lower confidence and set should_apply=false with a short rejection_reason."
)

RECORD_READY_FOR_REVIEW = "ready_for_review"
RECORD_ACCEPTED = "accepted"
RECORD_REJECTED = "rejected"
RECORD_NEEDS_REVIEW = "needs_review"
RECORD_FAILED = "failed"

BATCH_DRAFT = "draft"
BATCH_REVIEWING = "reviewing"
BATCH_READY_TO_APPLY = "ready_to_apply"
BATCH_WRITING_WORKSPACE = "writing_workspace"
BATCH_SYNCING_REPO = "syncing_repo"
BATCH_SYNCING_GIT = "syncing_git"
BATCH_COMPLETED = "completed"
BATCH_FAILED = "failed"

PENDING_RECORD_STATUSES = (RECORD_READY_FOR_REVIEW, RECORD_ACCEPTED, RECORD_NEEDS_REVIEW)
TERMINAL_BATCH_STATUSES = (BATCH_COMPLETED, BATCH_FAILED)
BASELINE_STATUS_MISSING = "missing"
BASELINE_STATUS_SYNCED = "synced"
BASELINE_STATUS_SEED_FALLBACK = "seed_fallback"
BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW = "sync_skipped_pending_review"
BASELINE_MANIFEST_FIELDS = (
    "baseline_status",
    "baseline_source_url",
    "baseline_branch",
    "baseline_commit",
    "baseline_updated_at",
    "baseline_error",
)
PROPOSED_FIELDS = {
    "title",
    "title_cn",
    "year",
    "type",
    "materials",
    "size",
    "duration",
    "credits",
    "description_en",
    "description_cn",
    "video_link",
    "url",
    "images",
    "high_res_images",
    "source",
}


def _vacuum_db_if_needed() -> None:
    path = db_path()
    if not path.exists():
        return
    conn = sqlite3.connect(path)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


class AIValidationResult(BaseModel):
    """Structured AI validation payload."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    page_type: str = "unknown"
    title: str = ""
    title_cn: str = ""
    year: str = ""
    type: str = ""
    materials: str = ""
    size: str = ""
    duration: str = ""
    credits: str = ""
    description_en: str = ""
    description_cn: str = ""
    video_link: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    should_apply: bool = False
    rejection_reason: str = ""


class AIValidationCallResult(BaseModel):
    """Result of one AI validation attempt."""

    model_config = ConfigDict(extra="forbid")

    payload: AIValidationResult
    available: bool = False
    error_state: str = ""


AIValidationResult.model_rebuild()
AIValidationCallResult.model_rebuild()


def workspace_root() -> Path:
    env_root = os.environ.get("AAAJIAO_IMPORTER_WORKSPACE_ROOT")
    if env_root:
        return Path(env_root)
    return Path.home() / "Library/Application Support" / APP_NAME / "workspace"


def db_path() -> Path:
    return workspace_root() / "jobs.sqlite"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def bundle_root() -> Path:
    env_root = os.environ.get("AAAJIAO_IMPORTER_BUNDLE_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    env_root = os.environ.get("AAAJIAO_REPO_ROOT")
    if env_root:
        return Path(env_root)
    return DEFAULT_REPO_ROOT


def seed_root() -> Path:
    return bundle_root() / "Seed"


def snapshot_root() -> Path:
    return workspace_root() / "scraper_snapshot"


def publish_repo_root() -> Path:
    return workspace_root() / PUBLISH_REPO_DIR


def baseline_repo_root() -> Path:
    return workspace_root() / BASELINE_REPO_DIR


def seed_snapshot_root() -> Path:
    direct = bundle_root() / "python_snapshot"
    if direct.exists():
        return direct
    return bundle_root() / "Vendor" / "python_snapshot"


def seed_manifest_path() -> Path:
    return seed_root() / SEED_MANIFEST_NAME


def workspace_manifest_path() -> Path:
    return workspace_root() / WORKSPACE_MANIFEST_NAME


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def baseline_remote_url() -> str:
    override = _normalize_string(os.environ.get("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL"))
    return override or BASELINE_REMOTE_URL


def baseline_remote_branch() -> str:
    override = _normalize_string(os.environ.get("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH"))
    return override or BASELINE_REMOTE_BRANCH


def _collapse_whitespace(value: Any) -> str:
    return " ".join(_normalize_string(value).split())


def _normalized_page_type(value: Any) -> str:
    normalized = _normalize_string(value).lower()
    if normalized in {"artwork", "exhibition", "unknown"}:
        return normalized
    return "unknown"


def _safe_slug(value: str) -> str:
    slug = value.strip("/").split("/")[-1]
    return re.sub(r"[-_]+", " ", slug).strip().lower()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return payload


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(path)


def _workspace_sitemap_cache_path() -> Path:
    return workspace_root() / ".cache" / "sitemap_lastmod.json"


def _load_workspace_sitemap_cache() -> Dict[str, str]:
    path = _workspace_sitemap_cache_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _remove_urls_from_incremental_baseline(urls: Iterable[str]) -> None:
    unique_urls = [url for url in dict.fromkeys(urls) if _normalize_string(url)]
    if not unique_urls:
        return
    path = _workspace_sitemap_cache_path()
    if not path.exists():
        return
    sitemap_cache = _load_workspace_sitemap_cache()
    changed = False
    for url in unique_urls:
        if url in sitemap_cache:
            sitemap_cache.pop(url, None)
            changed = True
    if changed:
        _write_json_atomic(path, sitemap_cache)


def _fallback_seed_manifest() -> Dict[str, Any]:
    works_path = seed_root() / REPO_WORKS
    portfolio_path = seed_root() / REPO_PORTFOLIO
    works_sha = _file_sha256(works_path)
    portfolio_sha = _file_sha256(portfolio_path)
    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": "",
        "source_commit": "unknown",
        "seed_version": f"fallback-{works_sha[:12]}-{portfolio_sha[:12]}",
        "files": {
            REPO_WORKS: {"sha256": works_sha, "size": works_path.stat().st_size},
            REPO_PORTFOLIO: {"sha256": portfolio_sha, "size": portfolio_path.stat().st_size},
        },
        "snapshot": {
            "scraper_files": len(list((seed_snapshot_root() / "scraper").rglob("*"))),
            "cache_files": len(list((seed_root() / "cache").rglob("*"))),
        },
        "python_runtime": {"mode": "unknown"},
    }


def _load_seed_manifest() -> Dict[str, Any]:
    path = seed_manifest_path()
    if path.exists():
        return _load_json(path)
    return _fallback_seed_manifest()


def _baseline_manifest_defaults() -> Dict[str, str]:
    return {
        "baseline_status": BASELINE_STATUS_SEED_FALLBACK,
        "baseline_source_url": baseline_remote_url(),
        "baseline_branch": baseline_remote_branch(),
        "baseline_commit": "",
        "baseline_updated_at": "",
        "baseline_error": "",
    }


def _baseline_manifest_state(
    existing_manifest: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    state = _baseline_manifest_defaults()
    if existing_manifest:
        for field in BASELINE_MANIFEST_FIELDS:
            value = existing_manifest.get(field)
            if value is not None:
                state[field] = _normalize_string(value)
    if overrides:
        for field, value in overrides.items():
            if field in BASELINE_MANIFEST_FIELDS and value is not None:
                state[field] = _normalize_string(value)
    if not state["baseline_source_url"]:
        state["baseline_source_url"] = baseline_remote_url()
    if not state["baseline_branch"]:
        state["baseline_branch"] = baseline_remote_branch()
    return state


def _workspace_manifest_or_empty() -> Dict[str, Any]:
    path = workspace_manifest_path()
    if path.exists():
        return _load_json(path)
    return {}


def _copy_file_atomic(source: Path, target: Path) -> None:
    temp_target = target.with_suffix(f"{target.suffix}.tmp")
    shutil.copy2(source, temp_target)
    temp_target.replace(target)


def _restore_workspace_targets_from_seed() -> None:
    for name in TARGET_FILES:
        _copy_file_atomic(seed_root() / name, workspace_root() / name)


def _validate_works_file(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"{path.name} must contain a JSON array")


def _reset_baseline_repo(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    root.parent.mkdir(parents=True, exist_ok=True)


def _git_error_message(exc: subprocess.CalledProcessError) -> str:
    """Render a CalledProcessError as readable text, since str(exc) drops stderr/stdout."""
    stderr = _normalize_string(exc.stderr)
    stdout = _normalize_string(exc.stdout)
    if stderr:
        return stderr
    if stdout:
        return stdout
    return str(exc)


def _clone_remote_baseline_repo() -> Tuple[Path, str]:
    root = baseline_repo_root()
    _reset_baseline_repo(root)
    try:
        _run_git(
            root.parent,
            [
                "clone",
                "--branch",
                baseline_remote_branch(),
                "--single-branch",
                baseline_remote_url(),
                root.name,
            ],
            timeout=GIT_NETWORK_TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to clone GitHub baseline: {_git_error_message(exc)}") from exc
    return root, _git_head(root)


def _sync_remote_baseline_into_workspace() -> Dict[str, str]:
    root, commit_sha = _clone_remote_baseline_repo()
    works_path = root / REPO_WORKS
    portfolio_path = root / REPO_PORTFOLIO
    if not works_path.exists():
        raise RuntimeError(f"Remote baseline is missing {REPO_WORKS}")
    if not portfolio_path.exists():
        raise RuntimeError(f"Remote baseline is missing {REPO_PORTFOLIO}")
    _validate_works_file(works_path)
    for source, name in ((works_path, REPO_WORKS), (portfolio_path, REPO_PORTFOLIO)):
        _copy_file_atomic(source, workspace_root() / name)
    return {
        "baseline_status": BASELINE_STATUS_SYNCED,
        "baseline_source_url": baseline_remote_url(),
        "baseline_branch": baseline_remote_branch(),
        "baseline_commit": commit_sha,
        "baseline_updated_at": now_iso(),
        "baseline_error": "",
    }


def _seed_target_needs_restore(name: str, target: Path) -> bool:
    # Only the works JSON has an integrity contract worth checking here; a corrupt
    # (but present) file would otherwise slip past the plain exists() check and crash
    # every later json.load. The portfolio markdown has no such structural invariant.
    if name != REPO_WORKS:
        return False
    try:
        _validate_works_file(target)
    except RuntimeError:
        return True
    return False


def _copy_seed_payload(*, overwrite: bool = False) -> None:
    snapshot_path = snapshot_root()
    cache_path = workspace_root() / ".cache"
    if overwrite:
        shutil.rmtree(snapshot_path, ignore_errors=True)
        shutil.rmtree(cache_path, ignore_errors=True)
        for name in TARGET_FILES:
            (workspace_root() / name).unlink(missing_ok=True)

    snapshot_path.mkdir(parents=True, exist_ok=True)
    if overwrite or not (snapshot_path / "scraper").exists():
        shutil.copytree(seed_snapshot_root() / "scraper", snapshot_path / "scraper", dirs_exist_ok=True)
    if overwrite or not cache_path.exists():
        seed_cache = seed_root() / "cache"
        if seed_cache.exists():
            shutil.copytree(seed_cache, cache_path, dirs_exist_ok=True)
        else:
            # The seed cache is optional (a fresh clone or CI may not carry one);
            # create an empty cache dir instead of crashing every helper command.
            cache_path.mkdir(parents=True, exist_ok=True)
    for name in TARGET_FILES:
        target = workspace_root() / name
        # Restore when the file is missing *or* an existing works JSON is corrupt, so
        # ensure_workspace() self-heals a damaged copy instead of deferring the failure
        # to the next json.load with no recovery path.
        if overwrite or not target.exists() or _seed_target_needs_restore(name, target):
            shutil.copy2(seed_root() / name, target)


def _workspace_has_local_activity() -> bool:
    # sqlite3.connect() as a context manager only commits/rolls back the transaction; it
    # never closes the connection, so wrap it in closing() to avoid leaking the handle.
    with contextlib.closing(sqlite3.connect(db_path())) as conn:
        batches = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        records = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    return bool(batches or records)


def _workspace_has_active_review_state() -> bool:
    # A draft batch is the transient pre-reviewing state; if creation aborted before it
    # reached reviewing it is a ghost, not pending review work, and must not block a
    # baseline refresh. Genuine pending review work is still caught by the record check.
    with contextlib.closing(sqlite3.connect(db_path())) as conn:
        active_batches = conn.execute(
            "SELECT COUNT(*) FROM batches WHERE status NOT IN (?, ?, ?)",
            (BATCH_COMPLETED, BATCH_FAILED, BATCH_DRAFT),
        ).fetchone()[0]
        pending_records = conn.execute(
            "SELECT COUNT(*) FROM records WHERE status IN (?, ?, ?)",
            PENDING_RECORD_STATUSES,
        ).fetchone()[0]
    return bool(active_batches or pending_records)


def _write_workspace_manifest(
    seed_manifest: Dict[str, Any],
    *,
    workspace_status: str,
    workspace_seed_version: str,
    initialized_at: Optional[str] = None,
    previous_manifest: Optional[Dict[str, Any]] = None,
    baseline_updates: Optional[Dict[str, Any]] = None,
    update_bootstrap_time: bool = True,
) -> None:
    existing_manifest = previous_manifest or _workspace_manifest_or_empty()
    baseline_state = _baseline_manifest_state(existing_manifest, baseline_updates)
    last_bootstrap_at = _normalize_string(existing_manifest.get("last_bootstrap_at"))
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "app_name": APP_NAME,
        "workspace_root": str(workspace_root()),
        "initialized_at": initialized_at
        or _normalize_string(existing_manifest.get("initialized_at"))
        or now_iso(),
        "last_bootstrap_at": now_iso() if update_bootstrap_time or not last_bootstrap_at else last_bootstrap_at,
        "workspace_status": workspace_status,
        "workspace_seed_version": workspace_seed_version,
        "bundle_seed_version": _normalize_string(seed_manifest.get("seed_version")),
        "source_commit": _normalize_string(seed_manifest.get("source_commit")),
        "tracked_files": [REPO_WORKS, REPO_PORTFOLIO],
    }
    manifest.update(baseline_state)
    _write_json_atomic(workspace_manifest_path(), manifest)


def ensure_workspace() -> str:
    root = workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    seed_manifest = _load_seed_manifest()
    if not workspace_manifest_path().exists():
        _copy_seed_payload()
        init_db()
        _write_workspace_manifest(
            seed_manifest,
            workspace_status="ready",
            workspace_seed_version=_normalize_string(seed_manifest.get("seed_version")),
            baseline_updates={
                "baseline_status": BASELINE_STATUS_SEED_FALLBACK,
                "baseline_source_url": baseline_remote_url(),
                "baseline_branch": baseline_remote_branch(),
                "baseline_updated_at": now_iso(),
                "baseline_error": "",
            },
        )
        return "initialized"

    _copy_seed_payload()
    init_db()
    workspace_manifest = _workspace_manifest_or_empty()
    workspace_seed_version = _normalize_string(workspace_manifest.get("workspace_seed_version"))
    bundle_seed_version = _normalize_string(seed_manifest.get("seed_version"))
    if not workspace_seed_version:
        workspace_seed_version = bundle_seed_version
    workspace_status = "ready" if workspace_seed_version == bundle_seed_version else "seed_version_mismatch"
    if workspace_status == "seed_version_mismatch" and not _workspace_has_local_activity():
        _copy_seed_payload(overwrite=True)
        workspace_seed_version = bundle_seed_version
        workspace_status = "ready"
    _write_workspace_manifest(
        seed_manifest,
        workspace_status=workspace_status,
        workspace_seed_version=workspace_seed_version,
        initialized_at=_normalize_string(workspace_manifest.get("initialized_at")) or now_iso(),
        previous_manifest=workspace_manifest,
    )
    return workspace_status


def _synchronize_workspace_baseline(
    *,
    fallback_to_seed: bool,
    allow_skip_if_reviewing: bool,
    block_if_reviewing: bool,
    update_bootstrap_time: bool,
) -> Dict[str, str]:
    seed_manifest = _load_seed_manifest()
    workspace_manifest = _workspace_manifest_or_empty()
    initialized_at = _normalize_string(workspace_manifest.get("initialized_at")) or now_iso()
    workspace_status = _normalize_string(workspace_manifest.get("workspace_status")) or "ready"
    workspace_seed_version = (
        _normalize_string(workspace_manifest.get("workspace_seed_version"))
        or _normalize_string(seed_manifest.get("seed_version"))
    )
    if _workspace_has_active_review_state():
        message = "Pending review results prevent refreshing the workspace baseline"
        if block_if_reviewing:
            _write_workspace_manifest(
                seed_manifest,
                workspace_status=workspace_status,
                workspace_seed_version=workspace_seed_version,
                initialized_at=initialized_at,
                previous_manifest=workspace_manifest,
                baseline_updates={
                    "baseline_status": BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW,
                    "baseline_source_url": baseline_remote_url(),
                    "baseline_branch": baseline_remote_branch(),
                    "baseline_error": message,
                },
                update_bootstrap_time=update_bootstrap_time,
            )
            raise RuntimeError(message)
        if allow_skip_if_reviewing:
            result = {
                "baseline_status": BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW,
                "baseline_source_url": baseline_remote_url(),
                "baseline_branch": baseline_remote_branch(),
                "baseline_error": message,
            }
            _write_workspace_manifest(
                seed_manifest,
                workspace_status=workspace_status,
                workspace_seed_version=workspace_seed_version,
                initialized_at=initialized_at,
                previous_manifest=workspace_manifest,
                baseline_updates=result,
                update_bootstrap_time=update_bootstrap_time,
            )
            return result

    try:
        result = _sync_remote_baseline_into_workspace()
    except Exception as exc:
        error_message = _normalize_string(exc)
        if not fallback_to_seed:
            _write_workspace_manifest(
                seed_manifest,
                workspace_status=workspace_status,
                workspace_seed_version=workspace_seed_version,
                initialized_at=initialized_at,
                previous_manifest=workspace_manifest,
                baseline_updates={
                    "baseline_source_url": baseline_remote_url(),
                    "baseline_branch": baseline_remote_branch(),
                    "baseline_error": error_message,
                },
                update_bootstrap_time=update_bootstrap_time,
            )
            raise RuntimeError(error_message) from exc
        _restore_workspace_targets_from_seed()
        result = {
            "baseline_status": BASELINE_STATUS_SEED_FALLBACK,
            "baseline_source_url": baseline_remote_url(),
            "baseline_branch": baseline_remote_branch(),
            "baseline_commit": "",
            "baseline_updated_at": now_iso(),
            "baseline_error": error_message,
        }
    _write_workspace_manifest(
        seed_manifest,
        workspace_status=workspace_status,
        workspace_seed_version=workspace_seed_version,
        initialized_at=initialized_at,
        previous_manifest=workspace_manifest,
        baseline_updates=result,
        update_bootstrap_time=update_bootstrap_time,
    )
    return result


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    conn = sqlite3.connect(db_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            total_records INTEGER NOT NULL DEFAULT 0,
            applied_commit_sha TEXT,
            last_error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            slug TEXT NOT NULL,
            status TEXT NOT NULL,
            page_type TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            is_update INTEGER NOT NULL DEFAULT 0,
            proposed_record_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES batches(id)
        )
        """
    )
    _ensure_column(conn, "batches", "last_error", "TEXT")
    conn.commit()
    conn.close()


@contextlib.contextmanager
def connect_db() -> Iterable[sqlite3.Connection]:
    ensure_workspace()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def cleanup_batch(batch_id: int) -> int:
    with connect_db() as conn:
        deleted_records = conn.execute(
            "SELECT COUNT(*) FROM records WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()[0]
        conn.execute("DELETE FROM records WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
    if deleted_records:
        _vacuum_db_if_needed()
    return int(deleted_records)


def prune_terminal_batches() -> int:
    path = db_path()
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        # A failed apply keeps its accepted records around so the user can retry
        # the sync; leave those batches alone until the retry succeeds (or the
        # user deletes the batch) instead of silently erasing the retry window.
        # Completed batches are safe to prune regardless: apply already merged
        # their accepted records into the shared artifacts.
        batch_ids = [
            row["id"]
            for row in conn.execute(
                """
                SELECT batches.id AS id
                FROM batches
                WHERE batches.status = ?
                   OR (
                       batches.status = ?
                       AND NOT EXISTS (
                           SELECT 1 FROM records
                           WHERE records.batch_id = batches.id
                             AND records.status = ?
                       )
                   )
                """,
                (BATCH_COMPLETED, BATCH_FAILED, RECORD_ACCEPTED),
            )
        ]
        # A draft batch that never carried a record is a ghost left behind when batch
        # creation aborted before reaching the reviewing state (e.g. process killed
        # mid-setup); prune it so it cannot masquerade as pending work indefinitely.
        batch_ids.extend(
            row["id"]
            for row in conn.execute(
                """
                SELECT batches.id AS id
                FROM batches
                LEFT JOIN records ON records.batch_id = batches.id
                WHERE batches.status = ?
                GROUP BY batches.id
                HAVING COUNT(records.id) = 0
                """,
                (BATCH_DRAFT,),
            )
        )
        if not batch_ids:
            return 0
        deleted_records = conn.execute(
            f"SELECT COUNT(*) FROM records WHERE batch_id IN ({','.join('?' for _ in batch_ids)})",
            batch_ids,
        ).fetchone()[0]
        conn.execute(
            f"DELETE FROM records WHERE batch_id IN ({','.join('?' for _ in batch_ids)})",
            batch_ids,
        )
        conn.execute(
            f"DELETE FROM batches WHERE id IN ({','.join('?' for _ in batch_ids)})",
            batch_ids,
        )
        conn.commit()
    finally:
        conn.close()
    if deleted_records or batch_ids:
        _vacuum_db_if_needed()
    return len(batch_ids)


@contextlib.contextmanager
def workspace_cwd() -> Iterable[None]:
    prev = Path.cwd()
    os.chdir(workspace_root())
    try:
        yield
    finally:
        os.chdir(prev)


def _load_snapshot_modules() -> Dict[str, Any]:
    snapshot_path = str(snapshot_root())
    if snapshot_path not in sys.path:
        sys.path.insert(0, snapshot_path)
    scraper_pkg = importlib.import_module("scraper")
    basic_mod = importlib.import_module("scraper.basic")
    return {
        "scraper_pkg": scraper_pkg,
        "AaajiaoScraper": scraper_pkg.AaajiaoScraper,
        "is_artwork": basic_mod.is_artwork,
        "normalize_year": basic_mod.normalize_year,
    }


def _slug(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _load_workspace_works() -> List[Dict[str, Any]]:
    with open(workspace_root() / REPO_WORKS, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_workspace_works(works: List[Dict[str, Any]]) -> None:
    temp = workspace_root() / f"{REPO_WORKS}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(works, handle, ensure_ascii=False, indent=2)
    temp.replace(workspace_root() / REPO_WORKS)


def _generate_workspace_markdown(works: List[Dict[str, Any]]) -> None:
    modules = _load_snapshot_modules()
    scraper_cls = modules["AaajiaoScraper"]
    with workspace_cwd():
        scraper = scraper_cls(use_cache=True)
        scraper.works = works
        scraper.generate_markdown(REPO_PORTFOLIO)


def _validate_workspace_outputs() -> None:
    works_path = workspace_root() / REPO_WORKS
    markdown_path = workspace_root() / REPO_PORTFOLIO
    works = json.loads(works_path.read_text(encoding="utf-8"))
    if not isinstance(works, list) or not works:
        raise RuntimeError("Generated works JSON is empty")
    markdown = markdown_path.read_text(encoding="utf-8")
    if not markdown.strip():
        raise RuntimeError("Generated portfolio markdown is empty")


def _run_git(
    root: Path,
    args: List[str],
    *,
    env: Optional[Dict[str, str]] = None,
    capture_output: bool = True,
    timeout: Optional[float] = GIT_LOCAL_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    # GIT_TERMINAL_PROMPT=0 stops git from blocking on an interactive credential
    # prompt; timeout guards against a hung/stalled network op (clone, push).
    merged_env = dict(env if env is not None else os.environ)
    merged_env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            env=merged_env,
            capture_output=capture_output,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {' '.join(args)} timed out after {timeout}s") from exc


def _git_output(root: Path, args: List[str], *, env: Optional[Dict[str, str]] = None) -> str:
    return _run_git(root, args, env=env).stdout.strip()


def _git_output_or_empty(root: Path, args: List[str]) -> str:
    try:
        return _git_output(root, args)
    except subprocess.CalledProcessError:
        return ""


def _git_head(root: Path) -> str:
    return _git_output(root, ["rev-parse", "HEAD"])


def _repo_publish_config(root: Path) -> Dict[str, str]:
    # `git symbolic-ref` exits non-zero (not empty output) on detached HEAD, and
    # `git rev-parse @{u}` exits non-zero (not empty output) with no upstream, so
    # both failure modes must be caught explicitly rather than checked as falsy output.
    try:
        branch = _git_output(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Repository is in detached HEAD state") from exc
    if not branch:
        raise RuntimeError("Repository is in detached HEAD state")

    try:
        upstream = _git_output(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Current branch '{branch}' has no upstream configured") from exc
    if "/" not in upstream:
        raise RuntimeError(f"Current branch '{branch}' has no upstream configured")
    remote_name, remote_branch = upstream.split("/", 1)

    expected_branch = baseline_remote_branch()
    if branch != expected_branch or remote_branch != expected_branch:
        raise RuntimeError(
            f"Current branch '{branch}' (tracking '{upstream}') does not match the "
            f"baseline branch '{expected_branch}'; switch to '{expected_branch}' before syncing"
        )

    try:
        remote_url = _git_output(root, ["remote", "get-url", remote_name])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Remote '{remote_name}' has no configured URL") from exc
    if not remote_url:
        raise RuntimeError(f"Remote '{remote_name}' has no configured URL")
    user_name = _git_output_or_empty(root, ["config", "--get", "user.name"])
    user_email = _git_output_or_empty(root, ["config", "--get", "user.email"])
    return {
        "branch": branch,
        "upstream": upstream,
        "remote_name": remote_name,
        "remote_branch": remote_branch,
        "remote_url": remote_url,
        "user_name": user_name,
        "user_email": user_email,
    }


def _publish_lock_path() -> Path:
    return workspace_root() / PUBLISH_LOCK_NAME


@contextlib.contextmanager
def _publish_repo_lock():
    """Serialize access to publish_repo_root() across concurrent apply calls.

    _ensure_publish_repo() destroys and re-clones a single shared directory, so two
    overlapping applyAcceptedRecords invocations would race on the same path (one
    process's rmtree/clone landing mid-way through another's git commands).
    """
    lock_path = _publish_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another sync to the repository is already in progress") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _reset_publish_repo(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    root.parent.mkdir(parents=True, exist_ok=True)


def _ensure_publish_repo(git_state: Dict[str, str]) -> Path:
    root = publish_repo_root()
    _reset_publish_repo(root)
    _run_git(
        root.parent,
        [
            "clone",
            "--branch",
            git_state["remote_branch"],
            "--single-branch",
            git_state["remote_url"],
            root.name,
        ],
        timeout=GIT_NETWORK_TIMEOUT_SECONDS,
    )
    user_name = git_state.get("user_name") or "Aaajiao Importer"
    user_email = git_state.get("user_email") or "importer@localhost"
    _run_git(root, ["config", "user.name", user_name])
    _run_git(root, ["config", "user.email", user_email])
    return root


def _copy_workspace_targets_to_publish_repo(root: Path) -> None:
    for target_file in TARGET_FILES:
        shutil.copy2(workspace_root() / target_file, root / target_file)


def _has_staged_changes(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=GIT_LOCAL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git diff --cached timed out after {GIT_LOCAL_TIMEOUT_SECONDS}s") from exc
    return result.returncode == 1


def _create_commit_from_publish_repo(root: Path, batch_id: int) -> str:
    _run_git(root, ["add", *TARGET_FILES])
    if not _has_staged_changes(root):
        return _git_head(root)
    _run_git(root, ["commit", "-m", f"data: import batch {batch_id}"])
    return _git_head(root)


def _sync_workspace_to_repo(batch_id: int) -> str:
    git_state = _repo_publish_config(repo_root())
    try:
        with _publish_repo_lock():
            root = _ensure_publish_repo(git_state)
            _copy_workspace_targets_to_publish_repo(root)
            commit_sha = _create_commit_from_publish_repo(root, batch_id)
            _run_git(
                root,
                [
                    "push",
                    "origin",
                    f"{commit_sha}:refs/heads/{git_state['remote_branch']}",
                ],
                timeout=GIT_NETWORK_TIMEOUT_SECONDS,
            )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to publish workspace changes to GitHub: {_git_error_message(exc)}") from exc
    return commit_sha


def _create_batch(mode: str) -> int:
    with connect_db() as conn:
        now = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO batches(mode, status, created_at, updated_at, total_records, last_error)
            VALUES(?, ?, ?, ?, 0, '')
            """,
            (mode, BATCH_DRAFT, now, now),
        )
        return int(cursor.lastrowid)


def _touch_batch(
    conn: sqlite3.Connection,
    batch_id: int,
    *,
    status: Optional[str] = None,
    total_records: Optional[int] = None,
    sha: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    updates = ["updated_at = ?"]
    values: List[Any] = [now_iso()]
    if status is not None:
        updates.append("status = ?")
        values.append(status)
    if total_records is not None:
        updates.append("total_records = ?")
        values.append(total_records)
    if sha is not None:
        updates.append("applied_commit_sha = ?")
        values.append(sha)
    if last_error is not None:
        updates.append("last_error = ?")
        values.append(last_error)
    values.append(batch_id)
    conn.execute(f"UPDATE batches SET {', '.join(updates)} WHERE id = ?", values)


def _insert_record(
    batch_id: int,
    url: str,
    status: str,
    page_type: str,
    confidence: float,
    is_update: bool,
    proposed: Optional[Dict[str, Any]],
    error: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    now = now_iso()
    params = (
        batch_id,
        url,
        _slug(url),
        status,
        page_type,
        confidence,
        1 if is_update else 0,
        json.dumps(proposed, ensure_ascii=False) if proposed else None,
        error,
        now,
        now,
    )
    statement = """
        INSERT INTO records(
            batch_id,
            url,
            slug,
            status,
            page_type,
            confidence,
            is_update,
            proposed_record_json,
            error_message,
            created_at,
            updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    # Accept an already-open connection so callers looping over many URLs (e.g. an
    # incremental sync batch) can reuse one connection instead of paying for a fresh
    # connect_db() (and the ensure_workspace() self-heal it triggers) per record.
    if conn is not None:
        conn.execute(statement, params)
        return
    with connect_db() as owned_conn:
        owned_conn.execute(statement, params)


def _record_rows(
    statuses: Optional[List[str]] = None,
    batch_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[sqlite3.Row]:
    query = "SELECT * FROM records"
    where: List[str] = []
    values: List[Any] = []
    if statuses:
        where.append(f"status IN ({','.join('?' for _ in statuses)})")
        values.extend(statuses)
    if batch_id is not None:
        where.append("batch_id = ?")
        values.append(batch_id)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id DESC"
    if conn is not None:
        return list(conn.execute(query, values))
    with connect_db() as owned_conn:
        return list(owned_conn.execute(query, values))


def _existing_urls() -> set[str]:
    return {work.get("url", "") for work in _load_workspace_works()}


def _normalize_base_data(modules: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(data)
    if normalized.get("year"):
        normalized["year"] = modules["normalize_year"](normalized["year"])
    return normalized


def _blank_ai_validation(base_data: Dict[str, Any], rejection_reason: str) -> AIValidationResult:
    return AIValidationResult(
        page_type="unknown",
        title=_normalize_string(base_data.get("title")),
        title_cn=_normalize_string(base_data.get("title_cn")),
        year=_normalize_string(base_data.get("year")),
        type=_normalize_string(base_data.get("type")),
        materials=_normalize_string(base_data.get("materials")),
        size=_normalize_string(base_data.get("size")),
        duration=_normalize_string(base_data.get("duration")),
        credits=_normalize_string(base_data.get("credits")),
        description_en=_normalize_string(base_data.get("description_en")),
        description_cn=_normalize_string(base_data.get("description_cn")),
        video_link=_normalize_string(base_data.get("video_link")),
        confidence=0.0,
        should_apply=False,
        rejection_reason=rejection_reason,
    )


def _openai_model() -> str:
    return _normalize_string(os.environ.get("OPENAI_MODEL")) or DEFAULT_OPENAI_MODEL


def _openai_model_source() -> str:
    source = _normalize_string(os.environ.get("OPENAI_MODEL_SOURCE")).lower()
    if source in {"default", "preset", "custom"}:
        return source
    return "default" if _openai_model() == DEFAULT_OPENAI_MODEL else "custom"


def _validation_response_format() -> Dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page_type",
            "title",
            "title_cn",
            "year",
            "type",
            "materials",
            "size",
            "duration",
            "credits",
            "description_en",
            "description_cn",
            "video_link",
            "confidence",
            "should_apply",
            "rejection_reason",
        ],
        "properties": {
            "page_type": {"type": "string", "enum": ["artwork", "exhibition", "unknown"]},
            "title": {"type": "string"},
            "title_cn": {"type": "string"},
            "year": {"type": "string"},
            "type": {"type": "string"},
            "materials": {"type": "string"},
            "size": {"type": "string"},
            "duration": {"type": "string"},
            "credits": {"type": "string"},
            "description_en": {"type": "string"},
            "description_cn": {"type": "string"},
            "video_link": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "should_apply": {"type": "boolean"},
            "rejection_reason": {"type": "string"},
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": AI_VALIDATION_NAME,
            "strict": True,
            "schema": schema,
        },
    }


def _post_openai_validation(
    *,
    api_key: str,
    model: str,
    payload: Dict[str, Any],
    response_format: Dict[str, Any],
) -> requests.Response:
    return requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "response_format": response_format,
            "messages": [
                {"role": "system", "content": AI_VALIDATION_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        },
        timeout=AI_VALIDATION_TIMEOUT,
    )


def _openai_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = _normalize_string(error.get("message"))
            error_type = _normalize_string(error.get("type"))
            error_param = _normalize_string(error.get("param"))
            detail = message or _normalize_string(response.text)
            extras = []
            if error_type:
                extras.append(f"type={error_type}")
            if error_param:
                extras.append(f"param={error_param}")
            if extras:
                return f"{detail} [{' '.join(extras)}]".strip()
            return detail
    return _normalize_string(response.text) or f"HTTP {response.status_code}"


def _should_retry_with_json_object(response: requests.Response) -> bool:
    if response.status_code != 400:
        return False
    detail = _openai_error_detail(response).lower()
    if "json_schema" not in detail and "structured outputs" not in detail:
        return False
    return any(
        needle in detail
        for needle in (
            "not supported",
            "unsupported",
            "not compatible",
            "does not support",
            "only supports",
        )
    )


def _call_openai_validation(
    url: str,
    base_data: Dict[str, Any],
    content_block: Dict[str, Any],
) -> AIValidationCallResult:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return AIValidationCallResult(
            payload=_blank_ai_validation(base_data, "AI unavailable: missing OPENAI_API_KEY"),
            available=False,
            error_state="ai_unavailable",
        )

    model = _openai_model()
    payload = {
        "url": url,
        "slug": _slug(url),
        "base_data": base_data,
        "content": {
            "main_text": content_block.get("main_text", ""),
            "images": content_block.get("images", []),
            "tags_footer": content_block.get("tags_footer", {}),
            "image_count": len(content_block.get("images", [])),
        },
    }
    try:
        response = _post_openai_validation(
            api_key=api_key,
            model=model,
            payload=payload,
            response_format=_validation_response_format(),
        )
        if _should_retry_with_json_object(response):
            response = _post_openai_validation(
                api_key=api_key,
                model=model,
                payload=payload,
                response_format={"type": "json_object"},
            )
        if response.status_code >= 400:
            detail = _openai_error_detail(response)
            raise RequestException(f"AI validation failed [{model}]: {detail}")
        content = response.json()["choices"][0]["message"]["content"]
        parsed = AIValidationResult.model_validate_json(content)
        return AIValidationCallResult(payload=parsed, available=True, error_state="")
    except ValidationError as exc:
        return AIValidationCallResult(
            payload=_blank_ai_validation(
                base_data,
                f"AI validation failed [{model}]: invalid structured output ({exc.errors()[0]['type']})",
            ),
            available=False,
            error_state="ai_invalid_output",
        )
    except (RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        return AIValidationCallResult(
            payload=_blank_ai_validation(base_data, str(exc)),
            available=False,
            error_state="ai_request_failed",
        )


def _normalize_compare_text(value: str) -> str:
    # Keep any Unicode letter/digit, not just ASCII [a-z0-9], so CJK titles (which have no
    # ASCII form) still normalize to non-empty text instead of being stripped to nothing.
    parts: List[str] = []
    current: List[str] = []
    for char in value.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return " ".join(parts)


def _slug_matches_title(url: str, title: str) -> bool:
    normalized_slug = _normalize_compare_text(_safe_slug(url))
    normalized_title = _normalize_compare_text(title)
    if not normalized_slug or not normalized_title:
        return False
    if normalized_slug in normalized_title or normalized_title in normalized_slug:
        return True
    slug_tokens = set(normalized_slug.split())
    title_tokens = set(normalized_title.split())
    return len(slug_tokens & title_tokens) >= min(2, max(1, len(slug_tokens)))


def _titles_are_similar(left: str, right: str) -> bool:
    left_normalized = _normalize_compare_text(left)
    right_normalized = _normalize_compare_text(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    overlap = len(left_tokens & right_tokens)
    return overlap >= min(len(left_tokens), len(right_tokens), 2)


def _looks_like_type_string(title: str) -> bool:
    normalized = _normalize_compare_text(title)
    return normalized in NORMALIZED_KNOWN_ARTWORK_TYPES


def _looks_like_contaminated_text(text: str, current_title: str, url: str) -> bool:
    normalized = _normalize_string(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if "related projects" in lowered or "selected works" in lowered:
        return True
    other_url_match = re.search(r"https?://\S+", lowered)
    if other_url_match and _slug(url) not in lowered:
        return True
    if current_title and not _titles_are_similar(current_title, normalized) and _slug(url).replace("-", " ") not in lowered:
        header_lines = [line.strip() for line in normalized.splitlines()[:3] if line.strip()]
        if header_lines and any(len(line.split()) <= 6 and line.istitle() for line in header_lines):
            return True
    return False


def _has_required_artwork_fields(record: Dict[str, Any]) -> bool:
    if not _normalize_string(record.get("title")):
        return False
    if not _normalize_string(record.get("type")):
        return False
    signal_fields = (
        _normalize_string(record.get("year")),
        _normalize_string(record.get("materials")),
        _normalize_string(record.get("description_en")),
        _normalize_string(record.get("description_cn")),
    )
    return any(signal_fields) or bool(record.get("images"))


def _sanitize_proposed_record(data: Dict[str, Any], url: str) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {
        "url": url,
        "source": _normalize_string(data.get("source")) or "macos_local",
    }
    for field in PROPOSED_FIELDS:
        if field in {"images", "high_res_images"}:
            image_values = data.get(field, [])
            sanitized[field] = image_values if isinstance(image_values, list) else []
        elif field in {"url", "source"}:
            continue
        else:
            sanitized[field] = _normalize_string(data.get(field))
    return sanitized


def _is_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_is_meaningful_value(item) for item in value)
    return True


def _merge_existing_work_with_proposed(existing: Dict[str, Any], proposed: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    for key, value in proposed.items():
        current = merged.get(key)
        if isinstance(current, str) and isinstance(value, str):
            if _is_meaningful_value(current) and _collapse_whitespace(current) == _collapse_whitespace(value):
                continue
        if _is_meaningful_value(value) or key not in merged:
            merged[key] = value
    return merged


def _gate_record(
    *,
    url: str,
    base_data: Dict[str, Any],
    validated: AIValidationResult,
    ai_available: bool,
    is_artwork: bool,
    proposed: Dict[str, Any],
) -> Tuple[str, bool, str]:
    page_type = _normalized_page_type(validated.page_type)
    if not is_artwork:
        return "exhibition", False, "Local parser marked page as non-artwork"
    if page_type != "artwork":
        reason = validated.rejection_reason or f"AI classified page as {page_type}"
        return page_type, False, reason
    if not ai_available:
        return "artwork", False, validated.rejection_reason or "AI unavailable"
    if _looks_like_type_string(proposed.get("title", "")):
        return "artwork", False, "Title looks like an artwork type, not a title"
    if not _slug_matches_title(url, proposed.get("title", "")):
        return "artwork", False, "Title does not match URL slug"
    base_title = _normalize_string(base_data.get("title"))
    if base_title and not _titles_are_similar(base_title, proposed.get("title", "")):
        return "artwork", False, "AI title does not match the local parser title"
    if _looks_like_contaminated_text(proposed.get("materials", ""), proposed.get("title", ""), url):
        return "artwork", False, "Materials field looks contaminated by unrelated page content"
    if _looks_like_contaminated_text(proposed.get("description_en", ""), proposed.get("title", ""), url):
        return "artwork", False, "English description looks contaminated by unrelated page content"
    if _looks_like_contaminated_text(proposed.get("description_cn", ""), proposed.get("title", ""), url):
        return "artwork", False, "Chinese description looks contaminated by unrelated page content"
    if not _has_required_artwork_fields(proposed):
        return "artwork", False, "Artwork record is missing required fields"
    if not validated.should_apply:
        return "artwork", False, validated.rejection_reason or "AI did not approve this record"
    if validated.confidence < AUTO_APPLY_CONFIDENCE:
        return "artwork", False, f"Confidence below threshold ({validated.confidence:.2f})"
    if base_title and not _slug_matches_title(url, base_title):
        return "artwork", False, "Base extraction title does not match URL slug"
    return "artwork", True, ""


def _import_url(url: str, modules: Dict[str, Any]) -> Dict[str, Any]:
    scraper_cls = modules["AaajiaoScraper"]
    with workspace_cwd():
        scraper = scraper_cls(use_cache=True)
        base_data = scraper.extract_metadata_bs4(url)
        # extract_work_details_v2() independently re-runs extract_metadata_bs4(url) as its
        # own "Layer 1" step on a cache miss, which would issue a second HTTP GET for the
        # exact same url on this same scraper instance. Patch the instance method so that
        # repeat call reuses the result already fetched above instead of hitting the network
        # again; any other url (there shouldn't be one) still falls through to a real fetch.
        original_extract_metadata_bs4 = scraper.extract_metadata_bs4

        def _reuse_base_data(fetch_url: str) -> Optional[Dict[str, Any]]:
            if fetch_url == url:
                return base_data
            return original_extract_metadata_bs4(fetch_url)

        scraper.extract_metadata_bs4 = _reuse_base_data
        hybrid_data = scraper.extract_work_details_v2(url)
    if not base_data and not hybrid_data:
        raise RuntimeError("No extraction data returned")

    if base_data:
        base_data = _normalize_base_data(modules, base_data)
    if hybrid_data:
        hybrid_data = _normalize_base_data(modules, hybrid_data)

    validation_base = base_data or hybrid_data or {}
    content_source = hybrid_data or base_data or {}
    is_work = modules["is_artwork"](validation_base)
    content_block = {
        "main_text": "\n\n".join(
            part
            for part in [
                _normalize_string(content_source.get("title")),
                _normalize_string(content_source.get("title_cn")),
                _normalize_string(content_source.get("materials")),
                _normalize_string(content_source.get("description_en")),
                _normalize_string(content_source.get("description_cn")),
            ]
            if part
        )[:12000],
        "images": (
            content_source.get("high_res_images")
            if isinstance(content_source.get("high_res_images"), list) and content_source.get("high_res_images")
            else content_source.get("images", [])
        ),
        "tags_footer": {
            "type": _normalize_string(content_source.get("type")),
            "year": _normalize_string(content_source.get("year")),
            "video_link": _normalize_string(content_source.get("video_link")),
        },
    }
    ai_result = _call_openai_validation(url, validation_base, content_block)
    validated = ai_result.payload
    merged = _merge_existing_work_with_proposed(content_source, validated.model_dump())
    merged["url"] = url
    if not isinstance(merged.get("images"), list):
        merged["images"] = []
    if not isinstance(merged.get("high_res_images"), list):
        merged["high_res_images"] = merged.get("images", []) if isinstance(merged.get("images"), list) else []
    merged["source"] = _normalize_string(content_source.get("source")) or "macos_local"
    proposed = _sanitize_proposed_record(merged, url)
    page_type, should_apply, rejection_reason = _gate_record(
        url=url,
        base_data=validation_base,
        validated=validated,
        ai_available=ai_result.available,
        is_artwork=is_work,
        proposed=proposed,
    )
    rejection_reason = rejection_reason or validated.rejection_reason
    if not ai_result.available and ai_result.error_state:
        rejection_reason = rejection_reason or f"AI validation unavailable ({ai_result.error_state})"
    return {
        "proposed": proposed,
        "page_type": page_type,
        "confidence": float(validated.confidence),
        "should_apply": should_apply,
        "rejection_reason": rejection_reason,
        "ai_available": ai_result.available,
        "ai_error_state": ai_result.error_state,
    }


def _refresh_batch_status(conn: sqlite3.Connection, batch_id: int) -> None:
    row = conn.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if row is None or row["status"] in TERMINAL_BATCH_STATUSES:
        return
    accepted_records = conn.execute(
        "SELECT COUNT(*) FROM records WHERE batch_id = ? AND status = ?",
        (batch_id, RECORD_ACCEPTED),
    ).fetchone()[0]
    total_records = conn.execute(
        "SELECT COUNT(*) FROM records WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()[0]
    next_status = BATCH_READY_TO_APPLY if accepted_records else BATCH_REVIEWING
    _touch_batch(
        conn,
        batch_id,
        status=next_status,
        total_records=int(total_records),
        last_error="",
    )


def _record_to_dto(row: sqlite3.Row) -> Dict[str, Any]:
    proposed = json.loads(row["proposed_record_json"]) if row["proposed_record_json"] else {}
    images = proposed.get("images", [])
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "url": row["url"],
        "slug": row["slug"],
        "status": row["status"],
        "page_type": row["page_type"],
        "confidence": row["confidence"],
        "is_update": bool(row["is_update"]),
        "title": _normalize_string(proposed.get("title")),
        "title_cn": _normalize_string(proposed.get("title_cn")),
        "year": _normalize_string(proposed.get("year")),
        "type": _normalize_string(proposed.get("type")),
        "materials": _normalize_string(proposed.get("materials")),
        "size": _normalize_string(proposed.get("size")),
        "duration": _normalize_string(proposed.get("duration")),
        "credits": _normalize_string(proposed.get("credits")),
        "description_en": _normalize_string(proposed.get("description_en")),
        "description_cn": _normalize_string(proposed.get("description_cn")),
        "video_link": _normalize_string(proposed.get("video_link")),
        "images": images if isinstance(images, list) else [],
        "high_res_images": (
            proposed.get("high_res_images", [])
            if isinstance(proposed.get("high_res_images", []), list)
            else []
        ),
        "error_message": row["error_message"],
    }


def _batch_detail(conn: sqlite3.Connection, batch_id: int) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"Batch {batch_id} not found")
    records = [
        _record_to_dto(record_row)
        for record_row in conn.execute(
            "SELECT * FROM records WHERE batch_id = ? ORDER BY id DESC",
            (batch_id,),
        )
    ]
    accepted_count = sum(1 for record in records if record["status"] == RECORD_ACCEPTED)
    deleted_count = sum(1 for record in records if record["status"] == RECORD_REJECTED)
    failed_count = sum(1 for record in records if record["status"] == RECORD_FAILED)
    ready_count = sum(
        1
        for record in records
        if record["status"] in {RECORD_READY_FOR_REVIEW, RECORD_NEEDS_REVIEW}
    )
    return {
        "batch": {
            "id": row["id"],
            "mode": row["mode"],
            "status": row["status"],
            "total_records": row["total_records"],
            "accepted_records": accepted_count,
            "ready_records": sum(
                1 for record in records if record["status"] == RECORD_READY_FOR_REVIEW
            ),
            "last_error": row["last_error"] or "",
        },
        "records": records,
        "total_records": len(records),
        "accepted_count": accepted_count,
        "deleted_count": deleted_count,
        "failed_count": failed_count,
        "syncable_count": accepted_count,
        "pending_count": ready_count,
    }


def _batch_summaries(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    batches: List[Dict[str, Any]] = []
    for row in conn.execute("SELECT * FROM batches ORDER BY id DESC LIMIT 20"):
        batches.append(
            {
                "id": row["id"],
                "mode": row["mode"],
                "status": row["status"],
                "total_records": row["total_records"],
                "accepted_records": conn.execute(
                    "SELECT COUNT(*) FROM records WHERE batch_id = ? AND status = ?",
                    (row["id"], RECORD_ACCEPTED),
                ).fetchone()[0],
                "ready_records": conn.execute(
                    "SELECT COUNT(*) FROM records WHERE batch_id = ? AND status = ?",
                    (row["id"], RECORD_READY_FOR_REVIEW),
                ).fetchone()[0],
                "last_error": row["last_error"] or "",
            }
        )
    return batches


def _settings_payload() -> Dict[str, Any]:
    workspace_manifest: Dict[str, Any] = {}
    if workspace_manifest_path().exists():
        workspace_manifest = _load_json(workspace_manifest_path())
    seed_manifest = _load_seed_manifest()
    baseline_state = _baseline_manifest_state(workspace_manifest)
    return {
        "workspace_path": str(workspace_root()),
        "repo_path": str(repo_root()),
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "openai_model": _openai_model(),
        "openai_model_source": _openai_model_source(),
        "workspace_status": _normalize_string(workspace_manifest.get("workspace_status")) or "missing",
        "workspace_seed_version": _normalize_string(workspace_manifest.get("workspace_seed_version")),
        "bundle_seed_version": _normalize_string(seed_manifest.get("seed_version")),
        "baseline_status": baseline_state["baseline_status"] or BASELINE_STATUS_MISSING,
        "baseline_source_url": baseline_state["baseline_source_url"],
        "baseline_branch": baseline_state["baseline_branch"],
        "baseline_commit": baseline_state["baseline_commit"],
        "baseline_updated_at": baseline_state["baseline_updated_at"],
        "baseline_error": baseline_state["baseline_error"],
    }


def _merge_accepted_records(batch_id: int) -> Tuple[List[Dict[str, Any]], int, int]:
    rows = list(reversed(_record_rows(statuses=[RECORD_ACCEPTED], batch_id=batch_id)))
    if not rows:
        raise RuntimeError("No accepted records in batch")

    works = _load_workspace_works()
    by_url = {work.get("url"): work for work in works}
    new_count = 0
    updated_count = 0
    for row in rows:
        proposed = json.loads(row["proposed_record_json"])
        if proposed["url"] in by_url:
            updated_count += 1
            by_url[proposed["url"]] = _merge_existing_work_with_proposed(
                by_url[proposed["url"]],
                proposed,
            )
        else:
            new_count += 1
            by_url[proposed["url"]] = proposed

    merged = list(by_url.values())
    modules = _load_snapshot_modules()
    deduplicate = importlib.import_module("scraper.core").deduplicate_works
    clean_contamination = modules["scraper_pkg"]._clean_cross_contamination
    merged = deduplicate(merged)
    clean_contamination(merged)
    return merged, new_count, updated_count


def bootstrap_workspace() -> Dict[str, Any]:
    initial_status = ensure_workspace()
    prune_terminal_batches()
    baseline_result = _synchronize_workspace_baseline(
        fallback_to_seed=True,
        allow_skip_if_reviewing=initial_status != "initialized",
        block_if_reviewing=False,
        update_bootstrap_time=True,
    )
    if initial_status == "initialized":
        status = (
            "initialized_synced"
            if baseline_result["baseline_status"] == BASELINE_STATUS_SYNCED
            else "initialized_seed_fallback"
        )
    elif baseline_result["baseline_status"] == BASELINE_STATUS_SYNCED:
        status = "baseline_synced"
    elif baseline_result["baseline_status"] == BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW:
        status = "baseline_sync_skipped_pending_review"
    else:
        status = "baseline_seed_fallback"
    return {"settings": _settings_payload(), "status": status}


def reset_workspace() -> Dict[str, Any]:
    root = workspace_root()
    if root.exists():
        shutil.rmtree(root)
    ensure_workspace()
    baseline_result = _synchronize_workspace_baseline(
        fallback_to_seed=True,
        allow_skip_if_reviewing=False,
        block_if_reviewing=False,
        update_bootstrap_time=True,
    )
    status = "reset_synced" if baseline_result["baseline_status"] == BASELINE_STATUS_SYNCED else "reset_seed_fallback"
    return {"settings": _settings_payload(), "status": status}


def refresh_workspace_baseline() -> Dict[str, Any]:
    ensure_workspace()
    _synchronize_workspace_baseline(
        fallback_to_seed=False,
        allow_skip_if_reviewing=False,
        block_if_reviewing=True,
        update_bootstrap_time=False,
    )
    status = "baseline_synced"
    return {"settings": _settings_payload(), "status": status}


def _report_progress(completed: int, total: int, url: str) -> None:
    """Emit a machine-readable progress line on stderr for HelperClient's
    stderr stream parser. Format is intentionally minimal (single line, no
    JSON) so it's cheap to parse incrementally: `PROGRESS <completed>/<total> <url>`.
    Never raises: a broken stderr pipe should not abort the sync itself.
    """
    try:
        print(f"PROGRESS {completed}/{total} {url}", file=sys.stderr, flush=True)
    except OSError:
        pass


def start_incremental_sync() -> Dict[str, Any]:
    ensure_workspace()
    batch_id = _create_batch("incremental")
    # Everything from here until the batch is fully processed must be guarded: a failure
    # while loading modules, reading existing works, or fetching the sitemap would
    # otherwise leave the batch stuck in the non-terminal draft/reviewing state forever,
    # permanently blocking baseline refresh. Mark it failed (a terminal, prunable state)
    # instead. Per-URL import failures are still handled inline and do not abort the batch.
    try:
        modules = _load_snapshot_modules()
        existing = _existing_urls()
        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_REVIEWING, last_error="")

        scraper_cls = modules["AaajiaoScraper"]
        with workspace_cwd():
            scraper = scraper_cls(use_cache=True)
            urls = scraper.get_all_work_links(incremental=True)

        # Reuse one connection across the whole insert loop instead of letting each
        # _insert_record() open (and self-heal via ensure_workspace()) its own; that cost
        # was previously paid once per URL. Commit after each record so a crash mid-batch
        # still keeps the records already processed, matching the prior per-record durability.
        total = len(urls)
        with connect_db() as conn:
            for index, url in enumerate(urls, start=1):
                try:
                    result = _import_url(url, modules)
                    status = RECORD_READY_FOR_REVIEW if result["should_apply"] else RECORD_NEEDS_REVIEW
                    _insert_record(
                        batch_id=batch_id,
                        url=url,
                        status=status,
                        page_type=result["page_type"],
                        confidence=result["confidence"],
                        is_update=url in existing,
                        proposed=result["proposed"],
                        error=result["rejection_reason"] or None,
                        conn=conn,
                    )
                except Exception as exc:
                    _insert_record(
                        batch_id=batch_id,
                        url=url,
                        status=RECORD_FAILED,
                        page_type="unknown",
                        confidence=0.0,
                        is_update=url in existing,
                        proposed=None,
                        error=str(exc),
                        conn=conn,
                    )
                conn.commit()
                _report_progress(index, total, url)
            _refresh_batch_status(conn, batch_id)
    except Exception as exc:
        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_FAILED, last_error=_fatal_error_message(exc))
        raise
    return {"batch_id": batch_id, "urls_processed": len(urls)}


def submit_manual_url(url: str) -> Dict[str, Any]:
    ensure_workspace()
    batch_id = _create_batch("manual")
    # Guard the setup phase (module load, existing-works read) so an abort before the
    # batch reaches reviewing marks it failed rather than leaving a ghost draft that
    # blocks baseline refresh forever. The inner try still records a single failed URL.
    try:
        modules = _load_snapshot_modules()
        existing = _existing_urls()
        # Reuse one connection across touch/insert/refresh instead of letting each open
        # (and self-heal via ensure_workspace()) its own for a single URL.
        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_REVIEWING, last_error="")
            conn.commit()

            try:
                result = _import_url(url, modules)
                status = RECORD_READY_FOR_REVIEW if result["should_apply"] else RECORD_NEEDS_REVIEW
                _insert_record(
                    batch_id=batch_id,
                    url=url,
                    status=status,
                    page_type=result["page_type"],
                    confidence=result["confidence"],
                    is_update=url in existing,
                    proposed=result["proposed"],
                    error=result["rejection_reason"] or None,
                    conn=conn,
                )
            except Exception as exc:
                _insert_record(
                    batch_id=batch_id,
                    url=url,
                    status=RECORD_FAILED,
                    page_type="unknown",
                    confidence=0.0,
                    is_update=url in existing,
                    proposed=None,
                    error=str(exc),
                    conn=conn,
                )
            conn.commit()
            _refresh_batch_status(conn, batch_id)
    except Exception as exc:
        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_FAILED, last_error=_fatal_error_message(exc))
        raise
    return {"batch_id": batch_id, "url": url}


def _set_record_status(record_id: int, status: str) -> Dict[str, Any]:
    if status not in {RECORD_ACCEPTED, RECORD_REJECTED}:
        raise RuntimeError(f"Unsupported status: {status}")
    deleted_url = ""
    batch_mode = ""
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT records.batch_id, records.url, batches.mode
            FROM records
            JOIN batches ON batches.id = records.batch_id
            WHERE records.id = ?
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Record {record_id} not found")
        conn.execute(
            "UPDATE records SET status = ?, updated_at = ?, error_message = COALESCE(error_message, '') WHERE id = ?",
            (status, now_iso(), record_id),
        )
        _refresh_batch_status(conn, int(row["batch_id"]))
        deleted_url = _normalize_string(row["url"])
        batch_mode = _normalize_string(row["mode"])
    if status == RECORD_REJECTED and batch_mode == "incremental":
        _remove_urls_from_incremental_baseline([deleted_url])
    return {"id": record_id, "status": status}


def accept_record(record_id: int) -> Dict[str, Any]:
    return _set_record_status(record_id, RECORD_ACCEPTED)


def reject_record(record_id: int) -> Dict[str, Any]:
    return _set_record_status(record_id, RECORD_REJECTED)


def get_batch_detail(batch_id: int) -> Dict[str, Any]:
    with connect_db() as conn:
        return _batch_detail(conn, batch_id)


def _compute_apply_preview(batch_id: int) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]]]:
    """Build the apply preview and, as a side effect, the merged works list it required.

    Returns the merged list alongside the preview so a subsequent real apply (see
    apply_accepted_records) can write it out directly instead of recomputing the same
    dedupe/contamination-clean merge a second time. merged is None only when there were
    no accepted records to merge (accepted_count == 0).
    """
    accepted_rows = _record_rows(statuses=[RECORD_ACCEPTED], batch_id=batch_id)
    preview = {
        "batch_id": batch_id,
        "accepted_count": len(accepted_rows),
        "new_count": 0,
        "updated_count": 0,
        "target_files": [str(repo_root() / name) for name in TARGET_FILES],
        "will_push": False,
        "error_message": "",
    }
    if not accepted_rows:
        preview["error_message"] = "No accepted records in batch"
        return preview, None
    merged, new_count, updated_count = _merge_accepted_records(batch_id)
    preview["new_count"] = new_count
    preview["updated_count"] = updated_count
    try:
        _repo_publish_config(repo_root())
        preview["will_push"] = True
    except Exception as exc:
        preview["error_message"] = str(exc)
    return preview, merged


def get_apply_preview(batch_id: int) -> Dict[str, Any]:
    preview, _ = _compute_apply_preview(batch_id)
    return preview


def _restore_unreviewed_incremental_urls(batch_id: int) -> None:
    """Keep unreviewed URLs rediscoverable before a partially-applied batch is cleaned up.

    apply only requires at least one accepted record, so a batch can still hold
    needs_review/ready_for_review records the user never resolved. cleanup_batch would
    delete them outright, and for incremental batches their URLs stay in the sitemap
    cache (recorded during discovery), so they would never resurface — silent data loss.
    Drop those URLs from the cache so the next incremental sync re-proposes them. Accepted
    records are excluded (already persisted) and rejected ones were pruned at reject time.
    """
    with connect_db() as conn:
        row = conn.execute("SELECT mode FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None or _normalize_string(row["mode"]) != "incremental":
            return
        unreviewed_urls = [
            _normalize_string(record_row["url"])
            for record_row in conn.execute(
                "SELECT url FROM records WHERE batch_id = ? AND status IN (?, ?)",
                (batch_id, RECORD_READY_FOR_REVIEW, RECORD_NEEDS_REVIEW),
            )
        ]
    if unreviewed_urls:
        _remove_urls_from_incremental_baseline(unreviewed_urls)


def apply_accepted_records(batch_id: int, dry_run: bool = False) -> Dict[str, Any]:
    ensure_workspace()
    # Reuse the merge _compute_apply_preview() already had to do to answer new/updated
    # counts, instead of calling _merge_accepted_records() a second time for the same batch.
    preview, merged = _compute_apply_preview(batch_id)
    if preview["accepted_count"] == 0 or merged is None:
        raise RuntimeError(preview["error_message"] or "No accepted records in batch")
    if not dry_run and not preview["will_push"]:
        raise RuntimeError(preview["error_message"] or "Repository preflight failed")

    with connect_db() as conn:
        _touch_batch(conn, batch_id, status=BATCH_WRITING_WORKSPACE, last_error="")

    try:
        _write_workspace_works(merged)
        _generate_workspace_markdown(merged)
        _validate_workspace_outputs()

        if dry_run:
            with connect_db() as conn:
                _touch_batch(
                    conn,
                    batch_id,
                    status=BATCH_READY_TO_APPLY,
                    total_records=len(merged),
                    last_error="",
                )
            return {
                "batch_id": batch_id,
                "applied_commit_sha": "",
                "preview": preview,
                "dry_run": True,
            }

        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_SYNCING_REPO, total_records=len(merged))

        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_SYNCING_GIT)
        sha = _sync_workspace_to_repo(batch_id)
    except Exception as exc:
        with connect_db() as conn:
            _touch_batch(conn, batch_id, status=BATCH_FAILED, last_error=str(exc))
        raise

    with connect_db() as conn:
        _touch_batch(
            conn,
            batch_id,
            status=BATCH_COMPLETED,
            total_records=len(merged),
            sha=sha,
            last_error="",
        )
    # Free any unreviewed URLs from the incremental cache before the whole batch is
    # deleted, so a partial apply does not silently drop records the user never resolved.
    _restore_unreviewed_incremental_urls(batch_id)
    cleanup_batch(batch_id)
    return {"batch_id": batch_id, "applied_commit_sha": sha, "preview": preview, "dry_run": False}


def delete_batch(batch_id: int) -> Dict[str, Any]:
    urls_to_restore: List[str] = []
    with connect_db() as conn:
        row = conn.execute("SELECT id, mode FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"Batch {batch_id} not found")
        if _normalize_string(row["mode"]) == "incremental":
            urls_to_restore = [
                _normalize_string(record_row["url"])
                for record_row in conn.execute("SELECT url FROM records WHERE batch_id = ?", (batch_id,))
            ]
    deleted_records = cleanup_batch(batch_id)
    if urls_to_restore:
        _remove_urls_from_incremental_baseline(urls_to_restore)
    return {"batch_id": batch_id, "deleted_records": deleted_records}


def list_pending_records() -> Dict[str, Any]:
    # connect_db() already runs the full ensure_workspace() self-heal on open; calling it
    # again beforehand (and letting _record_rows() open a third connection of its own) ran
    # that same manifest read/rewrite + schema check up to 3x for one listing. One shared
    # connection covers prune + both reads.
    with connect_db() as conn:
        prune_terminal_batches()
        batches = _batch_summaries(conn)
        pending_records = [
            _record_to_dto(row)
            for row in _record_rows(statuses=list(PENDING_RECORD_STATUSES), conn=conn)
        ]
    return {
        "settings": _settings_payload(),
        "batches": batches,
        "pending_records": pending_records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrapWorkspace", aliases=["bootstrap"])
    sub.add_parser("resetWorkspace")
    sub.add_parser("refreshWorkspaceBaseline", aliases=["refresh-baseline"])
    sub.add_parser("listPendingRecords", aliases=["overview"])
    sub.add_parser("startIncrementalSync", aliases=["start-incremental-sync"])

    submit = sub.add_parser("submitManualURL", aliases=["submit-url"])
    submit.add_argument("--url", required=True)

    accept = sub.add_parser("acceptRecord")
    accept.add_argument("--id", type=int, required=True)

    reject = sub.add_parser("rejectRecord")
    reject.add_argument("--id", type=int, required=True)

    batch_detail = sub.add_parser("getBatchDetail")
    batch_detail.add_argument("--batch-id", type=int, required=True)

    preview = sub.add_parser("getApplyPreview")
    preview.add_argument("--batch-id", type=int, required=True)

    delete_batch_parser = sub.add_parser("deleteBatch")
    delete_batch_parser.add_argument("--batch-id", type=int, required=True)

    apply_batch = sub.add_parser("applyAcceptedRecords", aliases=["apply-accepted"])
    apply_batch.add_argument("--batch-id", type=int, required=True)
    apply_batch.add_argument("--dry-run", action="store_true")

    legacy_status = sub.add_parser("set-record-status")
    legacy_status.add_argument("--id", type=int, required=True)
    legacy_status.add_argument("--status", required=True)
    return parser.parse_args()


def _fatal_error_message(exc: BaseException) -> str:
    """Render a single-line error for the CLI boundary: no traceback, no local paths.

    HelperClient.swift surfaces stderr verbatim as the user-facing error message, so a
    raw traceback (with this machine's absolute file paths and line numbers) would leak
    straight into the app UI.
    """
    if isinstance(exc, subprocess.CalledProcessError):
        message = _git_error_message(exc)
    else:
        message = str(exc) or exc.__class__.__name__
    message = " ".join(message.split())
    home = str(Path.home())
    if home:
        message = message.replace(home, "~")
    return message


def main() -> None:
    args = parse_args()
    if args.command in {"bootstrapWorkspace", "bootstrap"}:
        result = bootstrap_workspace()
    elif args.command == "resetWorkspace":
        result = reset_workspace()
    elif args.command in {"refreshWorkspaceBaseline", "refresh-baseline"}:
        result = refresh_workspace_baseline()
    elif args.command in {"listPendingRecords", "overview"}:
        result = list_pending_records()
    elif args.command in {"startIncrementalSync", "start-incremental-sync"}:
        result = start_incremental_sync()
    elif args.command in {"submitManualURL", "submit-url"}:
        result = submit_manual_url(args.url)
    elif args.command == "acceptRecord":
        result = accept_record(args.id)
    elif args.command == "rejectRecord":
        result = reject_record(args.id)
    elif args.command == "getBatchDetail":
        result = get_batch_detail(args.batch_id)
    elif args.command == "getApplyPreview":
        result = get_apply_preview(args.batch_id)
    elif args.command == "deleteBatch":
        result = delete_batch(args.batch_id)
    elif args.command in {"applyAcceptedRecords", "apply-accepted"}:
        result = apply_accepted_records(args.batch_id, dry_run=bool(args.dry_run))
    elif args.command == "set-record-status":
        if args.status == RECORD_ACCEPTED:
            result = accept_record(args.id)
        elif args.status == RECORD_REJECTED:
            result = reject_record(args.id)
        else:
            raise RuntimeError(f"Unsupported status: {args.status}")
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # top-level CLI boundary: never leak a raw traceback to Swift
        print(f"Error: {_fatal_error_message(exc)}", file=sys.stderr)
        sys.exit(1)
