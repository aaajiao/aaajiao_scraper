#!/usr/bin/env python3
"""Local-only importer engine for the macOS menu bar app."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


APP_NAME = "AaajiaoImporter"
DEFAULT_REPO_ROOT = Path("/Users/aaajiao/Documents/aaajiao_scraper")
REPO_WORKS = "aaajiao_works.json"
REPO_PORTFOLIO = "aaajiao_portfolio.md"


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


def seed_snapshot_root() -> Path:
    return bundle_root() / "python_snapshot"


def ensure_workspace() -> None:
    root = workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    snapshot_root().mkdir(parents=True, exist_ok=True)

    if not (snapshot_root() / "scraper").exists():
        shutil.copytree(seed_snapshot_root() / "scraper", snapshot_root() / "scraper", dirs_exist_ok=True)

    if not (root / ".cache").exists():
        shutil.copytree(seed_root() / "cache", root / ".cache", dirs_exist_ok=True)

    for name in (REPO_WORKS, REPO_PORTFOLIO):
        target = root / name
        if not target.exists():
            shutil.copy2(seed_root() / name, target)

    init_db()


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
            applied_commit_sha TEXT
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


@contextlib.contextmanager
def workspace_cwd() -> Iterable[None]:
    prev = Path.cwd()
    os.chdir(workspace_root())
    try:
        yield
    finally:
        os.chdir(prev)


def _load_snapshot_modules() -> Dict[str, Any]:
    sys.path.insert(0, str(snapshot_root()))
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
    with open(workspace_root() / REPO_WORKS, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_workspace_works(works: List[Dict[str, Any]]) -> None:
    temp = workspace_root() / f"{REPO_WORKS}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(works, f, ensure_ascii=False, indent=2)
    temp.replace(workspace_root() / REPO_WORKS)


def _generate_workspace_markdown(works: List[Dict[str, Any]]) -> None:
    modules = _load_snapshot_modules()
    scraper_cls = modules["AaajiaoScraper"]
    with workspace_cwd():
        scraper = scraper_cls(use_cache=True)
        scraper.works = works
        scraper.generate_markdown(REPO_PORTFOLIO)


def _repo_is_clean(root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return not result.stdout.strip()


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _sync_workspace_to_repo(batch_id: int) -> str:
    root = repo_root()
    if not _repo_is_clean(root):
        raise RuntimeError("Repository worktree is not clean")

    head_before = _git_head(root)
    shutil.copy2(workspace_root() / REPO_WORKS, root / REPO_WORKS)
    shutil.copy2(workspace_root() / REPO_PORTFOLIO, root / REPO_PORTFOLIO)

    try:
        subprocess.run(["git", "add", REPO_WORKS, REPO_PORTFOLIO], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", f"data: import batch {batch_id}"], cwd=root, check=True)
        subprocess.run(["git", "push"], cwd=root, check=True)
        return _git_head(root)
    except Exception:
        subprocess.run(["git", "reset", "--hard", head_before], cwd=root, check=True)
        raise


def _create_batch(mode: str) -> int:
    with connect_db() as conn:
        now = now_iso()
        cur = conn.execute(
            "INSERT INTO batches(mode, status, created_at, updated_at, total_records) VALUES(?, ?, ?, ?, 0)",
            (mode, "draft", now, now),
        )
        return int(cur.lastrowid)


def _touch_batch(conn: sqlite3.Connection, batch_id: int, status: str, total_records: Optional[int] = None, sha: Optional[str] = None) -> None:
    parts = ["status = ?", "updated_at = ?"]
    values: List[Any] = [status, now_iso()]
    if total_records is not None:
        parts.append("total_records = ?")
        values.append(total_records)
    if sha is not None:
        parts.append("applied_commit_sha = ?")
        values.append(sha)
    values.append(batch_id)
    conn.execute(f"UPDATE batches SET {', '.join(parts)} WHERE id = ?", values)


def _insert_record(batch_id: int, url: str, status: str, page_type: str, confidence: float, is_update: bool, proposed: Optional[Dict[str, Any]], error: Optional[str]) -> None:
    with connect_db() as conn:
        now = now_iso()
        conn.execute(
            """
            INSERT INTO records(batch_id, url, slug, status, page_type, confidence, is_update, proposed_record_json, error_message, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
            ),
        )


def _record_rows(statuses: Optional[List[str]] = None, batch_id: Optional[int] = None) -> List[sqlite3.Row]:
    with connect_db() as conn:
        query = "SELECT * FROM records"
        where = []
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
        return list(conn.execute(query, values))


def _existing_urls() -> set[str]:
    return {work.get("url", "") for work in _load_workspace_works()}


def _normalize_base_data(modules: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(data)
    if normalized.get("year"):
        normalized["year"] = modules["normalize_year"](normalized["year"])
    return normalized


def _call_openai_validation(url: str, base_data: Dict[str, Any], page_text: str) -> Dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "page_type": "unknown",
            "title": base_data.get("title", ""),
            "title_cn": base_data.get("title_cn", ""),
            "year": base_data.get("year", ""),
            "type": base_data.get("type", ""),
            "materials": base_data.get("materials", ""),
            "size": base_data.get("size", ""),
            "duration": base_data.get("duration", ""),
            "credits": base_data.get("credits", ""),
            "description_en": base_data.get("description_en", ""),
            "description_cn": base_data.get("description_cn", ""),
            "confidence": 0.0,
            "should_apply": False,
            "rejection_reason": "Missing OPENAI_API_KEY",
        }

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    schema_hint = {
        "page_type": "artwork|exhibition|unknown",
        "title": "string",
        "title_cn": "string",
        "year": "string",
        "type": "string",
        "materials": "string",
        "size": "string",
        "duration": "string",
        "credits": "string",
        "description_en": "string",
        "description_cn": "string",
        "confidence": "number between 0 and 1",
        "should_apply": "boolean",
        "rejection_reason": "string",
    }
    prompt = (
        "Validate and enrich one eventstructure.com record. "
        "Return JSON only. Prefer the base extraction for deterministic fields. "
        "Reject exhibition pages, related-work contamination, and records whose title does not "
        "match the page URL slug. Use page_type='artwork' only for a single artwork page."
    )
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "url": url,
                            "slug": _slug(url),
                            "base_data": base_data,
                            "page_text": page_text[:12000],
                            "schema": schema_hint,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _import_url(url: str, modules: Dict[str, Any]) -> Dict[str, Any]:
    scraper_cls = modules["AaajiaoScraper"]
    with workspace_cwd():
        scraper = scraper_cls(use_cache=True)
        base_data = scraper.extract_metadata_bs4(url)
    if not base_data:
        raise RuntimeError("Local extraction returned no data")
    base_data = _normalize_base_data(modules, base_data)
    is_work = modules["is_artwork"](base_data)
    content_parts = [
        base_data.get("title", ""),
        base_data.get("title_cn", ""),
        base_data.get("materials", ""),
        base_data.get("description_en", ""),
        base_data.get("description_cn", ""),
        "\n".join(base_data.get("images", [])),
    ]
    validated = _call_openai_validation(url, base_data, "\n\n".join(part for part in content_parts if part))
    merged = dict(base_data)
    merged.update({k: v for k, v in validated.items() if k in merged or k in {
        "title_cn", "materials", "size", "duration", "credits",
        "description_en", "description_cn", "type", "year", "title"
    }})
    page_type = validated.get("page_type", "unknown")
    confidence = float(validated.get("confidence", 0) or 0)
    should_apply = bool(validated.get("should_apply", False))
    if not is_work:
        page_type = "exhibition"
        should_apply = False
    merged["url"] = url
    merged["source"] = "macos_local"
    return {
        "proposed": merged,
        "page_type": page_type,
        "confidence": confidence,
        "should_apply": should_apply and page_type == "artwork" and confidence >= 0.85,
        "rejection_reason": validated.get("rejection_reason", ""),
    }


def start_incremental_sync() -> Dict[str, Any]:
    ensure_workspace()
    batch_id = _create_batch("incremental")
    modules = _load_snapshot_modules()
    scraper_cls = modules["AaajiaoScraper"]
    with workspace_cwd():
        scraper = scraper_cls(use_cache=True)
        urls = scraper.get_all_work_links(incremental=True)
    existing = _existing_urls()
    for url in urls:
        try:
            result = _import_url(url, modules)
            status = "ready_for_review" if result["should_apply"] else "failed"
            _insert_record(
                batch_id=batch_id,
                url=url,
                status=status,
                page_type=result["page_type"],
                confidence=result["confidence"],
                is_update=url in existing,
                proposed=result["proposed"],
                error=None if status == "ready_for_review" else result["rejection_reason"] or "Record did not pass validation",
            )
        except Exception as exc:
            _insert_record(
                batch_id=batch_id,
                url=url,
                status="failed",
                page_type="unknown",
                confidence=0.0,
                is_update=url in existing,
                proposed=None,
                error=str(exc),
            )
    with connect_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0]
        _touch_batch(conn, batch_id, "ready_to_apply", total_records=int(total))
    return {"batch_id": batch_id, "urls_processed": len(urls)}


def submit_url(url: str) -> Dict[str, Any]:
    ensure_workspace()
    batch_id = _create_batch("manual")
    modules = _load_snapshot_modules()
    existing = _existing_urls()
    try:
        result = _import_url(url, modules)
        status = "ready_for_review" if result["should_apply"] else "failed"
        _insert_record(
            batch_id=batch_id,
            url=url,
            status=status,
            page_type=result["page_type"],
            confidence=result["confidence"],
            is_update=url in existing,
            proposed=result["proposed"],
            error=None if status == "ready_for_review" else result["rejection_reason"] or "Record did not pass validation",
        )
    except Exception as exc:
        _insert_record(
            batch_id=batch_id,
            url=url,
            status="failed",
            page_type="unknown",
            confidence=0.0,
            is_update=url in existing,
            proposed=None,
            error=str(exc),
        )
    with connect_db() as conn:
        _touch_batch(conn, batch_id, "ready_to_apply", total_records=1)
    return {"batch_id": batch_id, "url": url}


def set_record_status(record_id: int, status: str) -> Dict[str, Any]:
    if status not in {"accepted", "rejected"}:
        raise RuntimeError(f"Unsupported status: {status}")
    with connect_db() as conn:
        conn.execute(
            "UPDATE records SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), record_id),
        )
    return {"id": record_id, "status": status}


def apply_accepted(batch_id: int) -> Dict[str, Any]:
    ensure_workspace()
    rows = _record_rows(statuses=["accepted"], batch_id=batch_id)
    if not rows:
        raise RuntimeError("No accepted records in batch")

    works = _load_workspace_works()
    existing = {work.get("url"): work for work in works}
    for row in rows:
        proposed = json.loads(row["proposed_record_json"])
        existing[proposed["url"]] = proposed

    merged = list(existing.values())
    modules = _load_snapshot_modules()
    deduplicate = importlib.import_module("scraper.core").deduplicate_works
    clean_contamination = modules["scraper_pkg"]._clean_cross_contamination
    merged = deduplicate(merged)
    clean_contamination(merged)

    _write_workspace_works(merged)
    _generate_workspace_markdown(merged)
    sha = _sync_workspace_to_repo(batch_id)

    with connect_db() as conn:
        _touch_batch(conn, batch_id, "completed", total_records=len(merged), sha=sha)
    return {"batch_id": batch_id, "applied_commit_sha": sha}


def overview() -> Dict[str, Any]:
    ensure_workspace()
    with connect_db() as conn:
        batches = [
            {
                "id": row["id"],
                "mode": row["mode"],
                "status": row["status"],
                "total_records": row["total_records"],
                "accepted_records": conn.execute(
                    "SELECT COUNT(*) FROM records WHERE batch_id = ? AND status = 'accepted'",
                    (row["id"],),
                ).fetchone()[0],
                "ready_records": conn.execute(
                    "SELECT COUNT(*) FROM records WHERE batch_id = ? AND status = 'ready_for_review'",
                    (row["id"],),
                ).fetchone()[0],
            }
            for row in conn.execute("SELECT * FROM batches ORDER BY id DESC LIMIT 20")
        ]

    pending = []
    for row in _record_rows(statuses=["ready_for_review", "accepted"], batch_id=None):
        proposed = json.loads(row["proposed_record_json"]) if row["proposed_record_json"] else {}
        pending.append(
            {
                "id": row["id"],
                "batch_id": row["batch_id"],
                "url": row["url"],
                "slug": row["slug"],
                "status": row["status"],
                "page_type": row["page_type"],
                "confidence": row["confidence"],
                "is_update": bool(row["is_update"]),
                "title": proposed.get("title", ""),
                "title_cn": proposed.get("title_cn", ""),
                "year": proposed.get("year", ""),
                "type": proposed.get("type", ""),
                "materials": proposed.get("materials", ""),
                "size": proposed.get("size", ""),
                "duration": proposed.get("duration", ""),
                "credits": proposed.get("credits", ""),
                "description_en": proposed.get("description_en", ""),
                "description_cn": proposed.get("description_cn", ""),
                "error_message": row["error_message"],
            }
        )

    return {
        "workspace": str(workspace_root()),
        "batches": batches,
        "pending_records": pending,
    }


def bootstrap() -> Dict[str, Any]:
    ensure_workspace()
    return {"workspace": str(workspace_root()), "status": "ok"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("overview")
    sub.add_parser("start-incremental-sync")

    submit = sub.add_parser("submit-url")
    submit.add_argument("--url", required=True)

    set_status = sub.add_parser("set-record-status")
    set_status.add_argument("--id", type=int, required=True)
    set_status.add_argument("--status", required=True)

    apply_batch = sub.add_parser("apply-accepted")
    apply_batch.add_argument("--batch-id", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "bootstrap":
        result = bootstrap()
    elif args.command == "overview":
        result = overview()
    elif args.command == "start-incremental-sync":
        result = start_incremental_sync()
    elif args.command == "submit-url":
        result = submit_url(args.url)
    elif args.command == "set-record-status":
        result = set_record_status(args.id, args.status)
    elif args.command == "apply-accepted":
        result = apply_accepted(args.batch_id)
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
