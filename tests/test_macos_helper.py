import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from requests import Response

HELPER_PATH = Path(__file__).resolve().parents[1] / "macos" / "Helper" / "aaajiao_importer.py"


@pytest.fixture(autouse=True)
def current_scraper_source(monkeypatch):
    # Exercise checked-out code, including the real renderer, rather than whichever
    # generated Vendor snapshot happened to be present after the last app build.
    monkeypatch.syspath_prepend(str(HELPER_PATH.parents[2] / "portfolio_scraper"))
    importlib.import_module("scraper")
    monkeypatch.delenv("AAAJIAO_IMPORTER_SITE_ORDER_FILE", raising=False)


def _load_helper_module():
    spec = importlib.util.spec_from_file_location("aaajiao_importer", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_response(status_code: int, body: bytes) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = body
    response.headers["Content-Type"] = "application/json"
    return response


def _find_defaults(value):
    if isinstance(value, dict):
        if "default" in value:
            return True
        return any(_find_defaults(item) for item in value.values())
    if isinstance(value, list):
        return any(_find_defaults(item) for item in value)
    return False


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _commit_baseline_files(repo: Path, *, title: str, markdown: str) -> str:
    works = [
        {
            "title": title,
            "title_cn": "",
            "year": "2026",
            "type": "installation",
            "materials": "steel",
            "size": "100 x 100 cm",
            "duration": "",
            "credits": "",
            "description_en": f"{title} description",
            "description_cn": "",
            "video_link": "",
            "url": f"https://eventstructure.com/{title.lower().replace(' ', '-')}",
            "images": [],
            "high_res_images": [],
            "source": "baseline_fixture",
        }
    ]
    (repo / "aaajiao_works.json").write_text(
        json.dumps(works, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (repo / "aaajiao_portfolio.md").write_text(markdown, encoding="utf-8")
    _run_git(repo, "add", "aaajiao_works.json", "aaajiao_portfolio.md")
    status = _run_git(repo, "status", "--short")
    if status:
        _run_git(repo, "commit", "-m", f"baseline: {title}")
    return _run_git(repo, "rev-parse", "HEAD")


def _prepare_baseline_remote(tmp_path: Path, *, title: str = "Remote Baseline Work", markdown: str = "# Remote\n"):
    remote_repo = tmp_path / "baseline.git"
    working_repo = tmp_path / "baseline_work"
    subprocess.run(["git", "init", "--bare", str(remote_repo)], check=True, capture_output=True, text=True)
    working_repo.mkdir()
    _run_git(working_repo, "init", "-b", "main")
    _run_git(working_repo, "config", "user.name", "Tester")
    _run_git(working_repo, "config", "user.email", "tester@example.com")
    commit_sha = _commit_baseline_files(working_repo, title=title, markdown=markdown)
    _run_git(working_repo, "remote", "add", "origin", str(remote_repo))
    _run_git(working_repo, "push", "-u", "origin", "main")
    return remote_repo, working_repo, commit_sha


def test_validation_response_format_uses_strict_required_schema():
    helper = _load_helper_module()

    response_format = helper._validation_response_format()
    schema = response_format["json_schema"]["schema"]

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
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
    }
    assert schema["properties"]["page_type"]["enum"] == ["artwork", "exhibition", "unknown"]
    assert _find_defaults(schema) is False


def test_openai_error_detail_includes_type_and_param():
    helper = _load_helper_module()
    response = _make_response(
        400,
        b'{"error":{"message":"Invalid schema for response_format","type":"invalid_request_error","param":"response_format"}}',
    )

    detail = helper._openai_error_detail(response)

    assert "Invalid schema for response_format" in detail
    assert "type=invalid_request_error" in detail
    assert "param=response_format" in detail


def test_retry_with_json_object_only_for_unsupported_schema_models():
    helper = _load_helper_module()
    unsupported = _make_response(
        400,
        b'{"error":{"message":"This model does not support response_format json_schema structured outputs.","type":"invalid_request_error","param":"response_format"}}',
    )
    invalid_schema = _make_response(
        400,
        b'{"error":{"message":"Invalid schema for response_format json_schema","type":"invalid_request_error","param":"response_format"}}',
    )

    assert helper._should_retry_with_json_object(unsupported) is True
    assert helper._should_retry_with_json_object(invalid_schema) is False


def test_delete_batch_removes_records_and_batch(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/test-work",
        status=helper.RECORD_REJECTED,
        page_type="artwork",
        confidence=0.0,
        is_update=False,
        proposed={"title": "Test Work", "url": "https://eventstructure.com/test-work"},
        error="Rejected for test",
    )

    response = helper.delete_batch(batch_id)

    assert response == {"batch_id": batch_id, "deleted_records": 1}
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (batch_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0] == 0


def test_ensure_workspace_auto_realigns_seed_when_no_activity(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))

    original_load_seed_manifest = helper._load_seed_manifest
    helper.ensure_workspace()

    def old_manifest():
        manifest = original_load_seed_manifest()
        manifest["seed_version"] = "seed-old"
        return manifest

    def new_manifest():
        manifest = original_load_seed_manifest()
        manifest["seed_version"] = "seed-new"
        return manifest

    helper._load_seed_manifest = old_manifest
    helper.ensure_workspace()
    helper._load_seed_manifest = new_manifest

    status = helper.ensure_workspace()
    workspace_manifest = helper._load_json(helper.workspace_manifest_path())

    assert status == "ready"
    assert workspace_manifest["workspace_status"] == "ready"
    assert workspace_manifest["workspace_seed_version"] == "seed-new"


def test_bootstrap_workspace_syncs_remote_baseline(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, _, commit_sha = _prepare_baseline_remote(tmp_path, title="Remote Bootstrap Work")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    response = helper.bootstrap_workspace()

    works = json.loads((workspace_root / "aaajiao_works.json").read_text(encoding="utf-8"))
    manifest = helper._load_json(helper.workspace_manifest_path())
    assert response["status"] == "initialized_synced"
    assert works[0]["title"] == "Remote Bootstrap Work"
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SYNCED
    assert manifest["baseline_commit"] == commit_sha
    assert manifest["baseline_source_url"] == str(remote_repo)


def test_reset_workspace_syncs_latest_remote_baseline(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, working_repo, _ = _prepare_baseline_remote(tmp_path, title="Remote Reset Old")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    helper.bootstrap_workspace()
    latest_commit = _commit_baseline_files(working_repo, title="Remote Reset New", markdown="# Reset New\n")
    _run_git(working_repo, "push", "origin", "main")

    response = helper.reset_workspace()

    works = json.loads((workspace_root / "aaajiao_works.json").read_text(encoding="utf-8"))
    manifest = helper._load_json(helper.workspace_manifest_path())
    assert response["status"] == "reset_synced"
    assert works[0]["title"] == "Remote Reset New"
    assert manifest["baseline_commit"] == latest_commit


def test_bootstrap_workspace_falls_back_to_seed_when_remote_unavailable(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(tmp_path / "missing.git"))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    response = helper.bootstrap_workspace()

    manifest = helper._load_json(helper.workspace_manifest_path())
    seed_works = json.loads((helper.seed_root() / helper.REPO_WORKS).read_text(encoding="utf-8"))
    works = json.loads((workspace_root / "aaajiao_works.json").read_text(encoding="utf-8"))
    assert response["status"] == "initialized_seed_fallback"
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SEED_FALLBACK
    assert manifest["baseline_error"]
    assert works[0]["title"] == seed_works[0]["title"]


def test_reset_workspace_falls_back_to_seed_when_remote_unavailable(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, _, _ = _prepare_baseline_remote(tmp_path, title="Remote Reset Source")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    helper.bootstrap_workspace()
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(tmp_path / "missing.git"))

    response = helper.reset_workspace()

    manifest = helper._load_json(helper.workspace_manifest_path())
    seed_works = json.loads((helper.seed_root() / helper.REPO_WORKS).read_text(encoding="utf-8"))
    works = json.loads((workspace_root / "aaajiao_works.json").read_text(encoding="utf-8"))
    assert response["status"] == "reset_seed_fallback"
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SEED_FALLBACK
    assert manifest["baseline_error"]
    assert works[0]["title"] == seed_works[0]["title"]


def test_bootstrap_workspace_skips_remote_refresh_when_review_is_pending(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, working_repo, _ = _prepare_baseline_remote(tmp_path, title="Pending Review Baseline")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    helper.bootstrap_workspace()
    original_works = (workspace_root / "aaajiao_works.json").read_text(encoding="utf-8")
    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/pending-review-work",
        status=helper.RECORD_READY_FOR_REVIEW,
        page_type="artwork",
        confidence=0.95,
        is_update=False,
        proposed={"title": "Pending Review Work", "url": "https://eventstructure.com/pending-review-work"},
        error=None,
    )
    _commit_baseline_files(working_repo, title="Should Not Overwrite", markdown="# Pending\n")
    _run_git(working_repo, "push", "origin", "main")

    response = helper.bootstrap_workspace()

    manifest = helper._load_json(helper.workspace_manifest_path())
    assert response["status"] == "baseline_sync_skipped_pending_review"
    assert (workspace_root / "aaajiao_works.json").read_text(encoding="utf-8") == original_works
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW


def test_refresh_workspace_baseline_updates_only_target_files(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, working_repo, _ = _prepare_baseline_remote(tmp_path, title="Refresh Old")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    helper.bootstrap_workspace()
    snapshot_before = (helper.snapshot_root() / "scraper" / "__init__.py").read_text(encoding="utf-8")
    cache_path = helper.workspace_root() / ".cache" / "sitemap_lastmod.json"
    cache_before = cache_path.read_text(encoding="utf-8")
    latest_commit = _commit_baseline_files(working_repo, title="Refresh New", markdown="# Refresh New\n")
    _run_git(working_repo, "push", "origin", "main")

    response = helper.refresh_workspace_baseline()

    works = json.loads((workspace_root / "aaajiao_works.json").read_text(encoding="utf-8"))
    manifest = helper._load_json(helper.workspace_manifest_path())
    assert response["status"] == "baseline_synced"
    assert works[0]["title"] == "Refresh New"
    assert (helper.snapshot_root() / "scraper" / "__init__.py").read_text(encoding="utf-8") == snapshot_before
    assert cache_path.read_text(encoding="utf-8") == cache_before
    assert manifest["baseline_commit"] == latest_commit


def test_refresh_workspace_baseline_rejects_active_review_state(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, _, _ = _prepare_baseline_remote(tmp_path, title="Refresh Blocked")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    helper.bootstrap_workspace()
    original_works = (workspace_root / "aaajiao_works.json").read_text(encoding="utf-8")
    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/blocked-refresh-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.95,
        is_update=False,
        proposed={"title": "Blocked Refresh Work", "url": "https://eventstructure.com/blocked-refresh-work"},
        error=None,
    )

    with pytest.raises(RuntimeError, match="Pending review results prevent refreshing the workspace baseline"):
        helper.refresh_workspace_baseline()

    manifest = helper._load_json(helper.workspace_manifest_path())
    assert (workspace_root / "aaajiao_works.json").read_text(encoding="utf-8") == original_works
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW


def test_get_batch_detail_returns_all_record_states(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    batch_id = helper._create_batch("incremental")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/accepted-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.95,
        is_update=False,
        proposed={"title": "Accepted Work", "url": "https://eventstructure.com/accepted-work"},
        error=None,
    )
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/deleted-work",
        status=helper.RECORD_REJECTED,
        page_type="artwork",
        confidence=0.40,
        is_update=False,
        proposed={"title": "Deleted Work", "url": "https://eventstructure.com/deleted-work"},
        error="Rejected",
    )
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/failed-work",
        status=helper.RECORD_FAILED,
        page_type="unknown",
        confidence=0.0,
        is_update=False,
        proposed=None,
        error="Import failed",
    )

    detail = helper.get_batch_detail(batch_id)

    assert detail["batch"]["id"] == batch_id
    assert detail["accepted_count"] == 1
    assert detail["deleted_count"] == 1
    assert detail["failed_count"] == 1
    assert detail["syncable_count"] == 1
    assert detail["total_records"] == 3
    assert {record["status"] for record in detail["records"]} == {
        helper.RECORD_ACCEPTED,
        helper.RECORD_REJECTED,
        helper.RECORD_FAILED,
    }
    accepted_record = next(record for record in detail["records"] if record["status"] == helper.RECORD_ACCEPTED)
    assert accepted_record["images"] == []


def test_get_batch_detail_includes_image_urls(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/image-work",
        status=helper.RECORD_READY_FOR_REVIEW,
        page_type="artwork",
        confidence=0.91,
        is_update=False,
        proposed={
            "title": "Image Work",
            "url": "https://eventstructure.com/image-work",
            "images": [
                "https://cdn.example.com/work-1.jpg",
                "https://cdn.example.com/work-2.jpg",
            ],
        },
        error=None,
    )

    detail = helper.get_batch_detail(batch_id)

    assert detail["records"][0]["images"] == [
        "https://cdn.example.com/work-1.jpg",
        "https://cdn.example.com/work-2.jpg",
    ]


def test_import_url_prefers_hybrid_extraction_and_preserves_richer_fields(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    helper.ensure_workspace()

    class FakeScraper:
        def __init__(self, use_cache: bool = True):
            self.use_cache = use_cache

        def extract_metadata_bs4(self, url: str):
            return {
                "url": url,
                "title": "One ritual",
                "title_cn": "一个仪式",
                "year": "2025",
                "type": "Video",
                "images": ["https://cdn.example.com/basic.jpg"],
                "high_res_images": ["https://cdn.example.com/basic.jpg"],
                "video_link": "",
                "materials": "",
                "size": "",
                "duration": "",
                "credits": "",
                "description_en": "",
                "description_cn": "",
                "source": "local",
            }

        def extract_work_details_v2(self, url: str):
            return {
                "url": url,
                "title": "One ritual",
                "title_cn": "一个仪式",
                "year": "2025",
                "type": "Video",
                "images": ["https://cdn.example.com/basic.jpg"],
                "high_res_images": ["https://cdn.example.com/highres.jpg"],
                "video_link": "https://vimeo.com/example",
                "materials": "",
                "size": "Dimension variable / 尺寸可变",
                "duration": "12'00''",
                "credits": "",
                "description_en": "English description\n\nSecond paragraph",
                "description_cn": "中文描述",
                "source": "hybrid_layer2",
            }

    helper._call_openai_validation = lambda url, base_data, content_block: helper.AIValidationCallResult(
        payload=helper.AIValidationResult(
            page_type="artwork",
            title="One ritual",
            title_cn="一个仪式",
            year="2025",
            type="Video",
            materials="",
            size="Dimension variable / 尺寸可变",
            duration="12'00''",
            credits="",
            description_en="English description Second paragraph",
            description_cn="中文描述",
            video_link="",
            confidence=0.96,
            should_apply=True,
            rejection_reason="",
        ),
        available=True,
        error_state="",
    )

    result = helper._import_url(
        "https://eventstructure.com/One-ritual",
        {
            "AaajiaoScraper": FakeScraper,
            "is_artwork": lambda data: True,
            "normalize_year": lambda value: value,
        },
    )

    assert result["should_apply"] is True
    assert result["proposed"]["source"] == "hybrid_layer2"
    assert result["proposed"]["video_link"] == "https://vimeo.com/example"
    assert result["proposed"]["high_res_images"] == ["https://cdn.example.com/highres.jpg"]
    assert result["proposed"]["description_en"] == "English description\n\nSecond paragraph"


def test_merge_existing_work_with_proposed_keeps_stronger_existing_fields():
    helper = _load_helper_module()

    existing = {
        "url": "https://eventstructure.com/One-ritual",
        "title": "One ritual",
        "video_link": "https://vimeo.com/original",
        "high_res_images": ["https://cdn.example.com/highres.jpg"],
        "description_en": "Existing description",
    }
    proposed = {
        "url": "https://eventstructure.com/One-ritual",
        "title": "One ritual",
        "video_link": "",
        "high_res_images": [],
        "description_en": "Updated description",
    }

    merged = helper._merge_existing_work_with_proposed(existing, proposed)

    assert merged["video_link"] == "https://vimeo.com/original"
    assert merged["high_res_images"] == ["https://cdn.example.com/highres.jpg"]
    assert merged["description_en"] == "Updated description"


def test_merge_existing_work_with_proposed_preserves_existing_paragraph_formatting():
    helper = _load_helper_module()

    existing = {
        "url": "https://eventstructure.com/One-ritual",
        "description_en": "First paragraph.\n\nSecond paragraph.",
    }
    proposed = {
        "url": "https://eventstructure.com/One-ritual",
        "description_en": "First paragraph. Second paragraph.",
    }

    merged = helper._merge_existing_work_with_proposed(existing, proposed)

    assert merged["description_en"] == "First paragraph.\n\nSecond paragraph."


def test_apply_accepted_records_cleans_up_applied_batch(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/test-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.99,
        is_update=False,
        proposed={"title": "Test Work", "url": "https://eventstructure.com/test-work", "images": []},
        error=None,
    )

    monkeypatch.setattr(
        helper,
        "_repo_publish_config",
        lambda root: {
            "branch": "main",
            "upstream": "origin/main",
            "remote_name": "origin",
            "remote_branch": "main",
            "remote_url": "git@example.com:test/repo.git",
            "user_name": "Tester",
            "user_email": "tester@example.com",
        },
    )
    monkeypatch.setattr(helper, "_merge_accepted_records", lambda _: ([{"title": "Test Work", "url": "https://eventstructure.com/test-work", "images": []}], 1, 0))
    monkeypatch.setattr(helper, "_write_workspace_works", lambda works: None)
    monkeypatch.setattr(helper, "_generate_workspace_markdown", lambda works: None)
    monkeypatch.setattr(helper, "_validate_workspace_outputs", lambda: None)
    monkeypatch.setattr(helper, "_sync_workspace_to_repo", lambda _: "abc123")
    monkeypatch.setattr(helper, "_copy_published_baseline_to_workspace", lambda batch_id, sha: None)

    response = helper.apply_accepted_records(batch_id)

    assert response["batch_id"] == batch_id
    assert response["applied_commit_sha"] == "abc123"
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (batch_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0] == 0


def test_prune_terminal_batches_keeps_failed_imports_for_retry(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    active_batch = helper._create_batch("manual")
    completed_batch = helper._create_batch("manual")
    failed_batch = helper._create_batch("manual")

    with helper.connect_db() as conn:
        helper._touch_batch(conn, active_batch, status=helper.BATCH_REVIEWING)
        helper._touch_batch(conn, completed_batch, status=helper.BATCH_COMPLETED)
        helper._touch_batch(conn, failed_batch, status=helper.BATCH_FAILED)

    helper._insert_record(
        batch_id=active_batch,
        url="https://eventstructure.com/active-work",
        status=helper.RECORD_READY_FOR_REVIEW,
        page_type="artwork",
        confidence=0.9,
        is_update=False,
        proposed={"title": "Active Work", "url": "https://eventstructure.com/active-work"},
        error=None,
    )
    helper._insert_record(
        batch_id=completed_batch,
        url="https://eventstructure.com/completed-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.9,
        is_update=False,
        proposed={"title": "Completed Work", "url": "https://eventstructure.com/completed-work"},
        error=None,
    )
    helper._insert_record(
        batch_id=failed_batch,
        url="https://eventstructure.com/failed-work",
        status=helper.RECORD_FAILED,
        page_type="unknown",
        confidence=0.0,
        is_update=False,
        proposed=None,
        error="Failure",
    )

    pruned = helper.prune_terminal_batches()

    assert pruned == 1
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (active_batch,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (completed_batch,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (failed_batch,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (active_batch,)).fetchone()[0] == 1


def test_prune_keeps_failed_batch_with_accepted_records_for_retry(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    retryable_batch = helper._create_batch("incremental")

    with helper.connect_db() as conn:
        helper._touch_batch(conn, retryable_batch, status=helper.BATCH_FAILED)

    helper._insert_record(
        batch_id=retryable_batch,
        url="https://eventstructure.com/retry-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.9,
        is_update=False,
        proposed={"title": "Retry Work", "url": "https://eventstructure.com/retry-work"},
        error=None,
    )

    pruned = helper.prune_terminal_batches()

    assert pruned == 0
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (retryable_batch,)).fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM records WHERE batch_id = ? AND status = ?",
                (retryable_batch, helper.RECORD_ACCEPTED),
            ).fetchone()[0]
            == 1
        )


def test_reject_record_restores_incremental_url_to_sitemap_cache(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    helper.ensure_workspace()
    sitemap_path = helper.workspace_root() / ".cache" / "sitemap_lastmod.json"
    url = "https://eventstructure.com/new-work"
    sitemap_path.write_text(json.dumps({url: "2026-03-12"}), encoding="utf-8")

    batch_id = helper._create_batch("incremental")
    helper._insert_record(
        batch_id=batch_id,
        url=url,
        status=helper.RECORD_READY_FOR_REVIEW,
        page_type="artwork",
        confidence=0.9,
        is_update=False,
        proposed={"title": "New Work", "url": url},
        error=None,
    )
    with helper.connect_db() as conn:
        record_id = conn.execute("SELECT id FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0]

    helper.reject_record(record_id)

    restored_cache = json.loads(sitemap_path.read_text(encoding="utf-8"))
    assert url not in restored_cache


def test_delete_incremental_batch_restores_all_urls_to_sitemap_cache(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    helper.ensure_workspace()
    sitemap_path = helper.workspace_root() / ".cache" / "sitemap_lastmod.json"
    first_url = "https://eventstructure.com/first-work"
    second_url = "https://eventstructure.com/second-work"
    sitemap_path.write_text(
        json.dumps({first_url: "2026-03-12", second_url: "2026-03-12"}),
        encoding="utf-8",
    )

    batch_id = helper._create_batch("incremental")
    for url in (first_url, second_url):
        helper._insert_record(
            batch_id=batch_id,
            url=url,
            status=helper.RECORD_READY_FOR_REVIEW,
            page_type="artwork",
            confidence=0.9,
            is_update=False,
            proposed={"title": url.rsplit("/", 1)[-1], "url": url},
            error=None,
        )

    helper.delete_batch(batch_id)

    restored_cache = json.loads(sitemap_path.read_text(encoding="utf-8"))
    assert first_url not in restored_cache
    assert second_url not in restored_cache


def test_apply_accepted_records_uses_managed_publish_repo_when_source_repo_is_dirty(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setattr(helper, "_fetch_website_order", lambda: ["https://eventstructure.com/test-work"])

    remote_repo = tmp_path / "remote.git"
    working_repo = tmp_path / "source"
    subprocess.run(["git", "init", "--bare", str(remote_repo)], check=True, capture_output=True, text=True)
    working_repo.mkdir()
    _run_git(working_repo, "init", "-b", "main")
    _run_git(working_repo, "config", "user.name", "Tester")
    _run_git(working_repo, "config", "user.email", "tester@example.com")
    (working_repo / "aaajiao_works.json").write_text("[]\n", encoding="utf-8")
    (working_repo / "aaajiao_portfolio.md").write_text("# Portfolio\n", encoding="utf-8")
    _run_git(working_repo, "add", "aaajiao_works.json", "aaajiao_portfolio.md")
    _run_git(working_repo, "commit", "-m", "initial")
    _run_git(working_repo, "remote", "add", "origin", str(remote_repo))
    _run_git(working_repo, "push", "-u", "origin", "main")
    initial_head = _run_git(working_repo, "rev-parse", "HEAD")
    (working_repo / "dirty.txt").write_text("keep dirty\n", encoding="utf-8")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(working_repo))

    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/test-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.99,
        is_update=False,
        proposed={"title": "Test Work", "url": "https://eventstructure.com/test-work", "images": []},
        error=None,
    )

    monkeypatch.setattr(
        helper,
        "_merge_accepted_records",
        lambda _: ([{"title": "Published Work", "url": "https://eventstructure.com/test-work", "images": []}], 1, 0),
    )
    monkeypatch.setattr(helper, "_generate_workspace_markdown", lambda works: (helper.workspace_root() / "aaajiao_portfolio.md").write_text("# Published\n", encoding="utf-8"))

    response = helper.apply_accepted_records(batch_id)

    assert response["batch_id"] == batch_id
    assert _run_git(working_repo, "rev-parse", "HEAD") == initial_head
    assert _run_git(working_repo, "status", "--short") == "?? dirty.txt"

    published_json = _run_git(
        working_repo,
        "--git-dir",
        str(remote_repo),
        "show",
        "refs/heads/main:aaajiao_works.json",
    )
    assert "Test Work" in published_json


def test_workspace_manifest_keeps_stable_structure_contract(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    status = helper.ensure_workspace()
    manifest = helper._load_json(helper.workspace_manifest_path())

    assert status == "initialized"
    assert manifest["manifest_version"] == helper.MANIFEST_VERSION
    assert manifest["app_name"] == helper.APP_NAME
    assert manifest["workspace_root"] == str(workspace_root)
    assert manifest["workspace_status"] == "ready"
    assert manifest["tracked_files"] == [helper.REPO_WORKS, helper.REPO_PORTFOLIO]
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SEED_FALLBACK
    assert manifest["baseline_source_url"] == helper.BASELINE_REMOTE_URL
    assert manifest["baseline_branch"] == helper.BASELINE_REMOTE_BRANCH
    for field in helper.BASELINE_MANIFEST_FIELDS:
        assert field in manifest


def test_seed_snapshot_root_prefers_direct_path_over_vendor_fallback(tmp_path, monkeypatch):
    helper = _load_helper_module()
    bundle_root = tmp_path / "bundle"
    vendor_snapshot = bundle_root / "Vendor" / "python_snapshot"
    vendor_snapshot.mkdir(parents=True)
    monkeypatch.setenv("AAAJIAO_IMPORTER_BUNDLE_ROOT", str(bundle_root))

    assert helper.seed_snapshot_root() == vendor_snapshot

    direct_snapshot = bundle_root / "python_snapshot"
    direct_snapshot.mkdir()
    assert helper.seed_snapshot_root() == direct_snapshot


def test_parse_args_accepts_alias_commands_and_flags(monkeypatch):
    helper = _load_helper_module()

    monkeypatch.setattr(sys, "argv", ["aaajiao_importer.py", "overview"])
    overview_args = helper.parse_args()
    assert overview_args.command == "overview"

    monkeypatch.setattr(
        sys,
        "argv",
        ["aaajiao_importer.py", "apply-accepted", "--batch-id", "7", "--dry-run"],
    )
    apply_args = helper.parse_args()
    assert apply_args.command == "apply-accepted"
    assert apply_args.batch_id == 7
    assert apply_args.dry_run is True


def test_copy_seed_payload_respects_overwrite_switch(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    helper.ensure_workspace()
    works_path = workspace_root / helper.REPO_WORKS
    portfolio_path = workspace_root / helper.REPO_PORTFOLIO
    seed_works = (helper.seed_root() / helper.REPO_WORKS).read_text(encoding="utf-8")
    seed_portfolio = (helper.seed_root() / helper.REPO_PORTFOLIO).read_text(encoding="utf-8")

    works_path.write_text(
        json.dumps([{"title": "Local Workspace Only", "url": "https://eventstructure.com/local-only"}], indent=2) + "\n",
        encoding="utf-8",
    )
    portfolio_path.write_text("# Local Workspace\n", encoding="utf-8")

    helper._copy_seed_payload(overwrite=False)
    assert "Local Workspace Only" in works_path.read_text(encoding="utf-8")
    assert portfolio_path.read_text(encoding="utf-8") == "# Local Workspace\n"

    helper._copy_seed_payload(overwrite=True)
    assert works_path.read_text(encoding="utf-8") == seed_works
    assert portfolio_path.read_text(encoding="utf-8") == seed_portfolio


def test_ensure_workspace_restores_corrupt_works_file(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    helper.ensure_workspace()
    works_path = workspace_root / helper.REPO_WORKS
    works_path.write_text("{not valid json", encoding="utf-8")

    # A corrupt-but-present works file must be repaired, not left to crash later reads.
    helper.ensure_workspace()

    restored = json.loads(works_path.read_text(encoding="utf-8"))
    assert isinstance(restored, list)
    assert isinstance(helper._existing_urls(), set)


def test_copy_seed_payload_tolerates_missing_seed_cache(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    bundle_root = tmp_path / "bundle"
    seed_dir = bundle_root / "Seed"
    seed_dir.mkdir(parents=True)
    # Provide required seed target files and snapshot, but deliberately omit Seed/cache.
    repo_root = Path(__file__).resolve().parents[1]
    (seed_dir / helper.REPO_WORKS).write_text(
        (repo_root / "macos" / "Seed" / helper.REPO_WORKS).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (seed_dir / helper.REPO_PORTFOLIO).write_text("# Seed\n", encoding="utf-8")
    snapshot_scraper = bundle_root / "Vendor" / "python_snapshot" / "scraper"
    snapshot_scraper.mkdir(parents=True)
    (snapshot_scraper / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BUNDLE_ROOT", str(bundle_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(repo_root))

    # Must not raise FileNotFoundError; an empty cache dir is created instead.
    helper._copy_seed_payload()

    assert (workspace_root / ".cache").is_dir()


def test_submit_manual_url_marks_batch_failed_when_setup_aborts(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    helper.ensure_workspace()

    def boom():
        raise RuntimeError("snapshot modules unavailable")

    monkeypatch.setattr(helper, "_load_snapshot_modules", boom)

    with pytest.raises(RuntimeError):
        helper.submit_manual_url("https://eventstructure.com/some-work")

    with helper.connect_db() as conn:
        statuses = [row["status"] for row in conn.execute("SELECT status FROM batches")]
    # The aborted batch is terminal (failed), not a ghost draft.
    assert statuses == [helper.BATCH_FAILED]
    # A failed setup must not masquerade as pending review work blocking baseline refresh.
    assert helper._workspace_has_active_review_state() is False


def test_prune_removes_ghost_draft_batches(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    ghost_draft = helper._create_batch("manual")  # left in draft with no records
    reviewing_batch = helper._create_batch("incremental")
    with helper.connect_db() as conn:
        helper._touch_batch(conn, reviewing_batch, status=helper.BATCH_REVIEWING)
    helper._insert_record(
        batch_id=reviewing_batch,
        url="https://eventstructure.com/active-work",
        status=helper.RECORD_READY_FOR_REVIEW,
        page_type="artwork",
        confidence=0.9,
        is_update=False,
        proposed={"title": "Active Work", "url": "https://eventstructure.com/active-work"},
        error=None,
    )

    pruned = helper.prune_terminal_batches()

    assert pruned == 1
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (ghost_draft,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (reviewing_batch,)).fetchone()[0] == 1


def test_refresh_workspace_baseline_ignores_ghost_draft_batch(tmp_path, monkeypatch):
    helper = _load_helper_module()
    workspace_root = tmp_path / "workspace"
    remote_repo, working_repo, _ = _prepare_baseline_remote(tmp_path, title="Ghost Draft Baseline")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_URL", str(remote_repo))
    monkeypatch.setenv("AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH", "main")

    helper.bootstrap_workspace()
    # A draft batch with zero records is a ghost left behind when batch creation aborted
    # before reaching "reviewing" (e.g. the process was killed mid-setup); it must not be
    # mistaken for pending review work that blocks a baseline refresh.
    ghost_draft = helper._create_batch("manual")

    latest_commit = _commit_baseline_files(working_repo, title="Ghost Draft Refresh", markdown="# Ghost Draft\n")
    _run_git(working_repo, "push", "origin", "main")

    response = helper.refresh_workspace_baseline()

    works = json.loads((workspace_root / "aaajiao_works.json").read_text(encoding="utf-8"))
    manifest = helper._load_json(helper.workspace_manifest_path())
    assert response["status"] == "baseline_synced"
    assert works[0]["title"] == "Ghost Draft Refresh"
    assert manifest["baseline_commit"] == latest_commit
    assert manifest["baseline_status"] == helper.BASELINE_STATUS_SYNCED
    with helper.connect_db() as conn:
        # The ghost draft is merely ignored, not implicitly pruned, by refresh itself.
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (ghost_draft,)).fetchone()[0] == 1


def test_apply_accepted_records_restores_unreviewed_incremental_urls(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

    helper.ensure_workspace()
    sitemap_path = helper.workspace_root() / ".cache" / "sitemap_lastmod.json"
    accepted_url = "https://eventstructure.com/accepted-work"
    pending_url = "https://eventstructure.com/needs-review-work"
    sitemap_path.write_text(
        json.dumps({accepted_url: "2026-03-12", pending_url: "2026-03-12"}),
        encoding="utf-8",
    )

    batch_id = helper._create_batch("incremental")
    helper._insert_record(
        batch_id=batch_id,
        url=accepted_url,
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.99,
        is_update=False,
        proposed={"title": "Accepted Work", "url": accepted_url, "images": []},
        error=None,
    )
    helper._insert_record(
        batch_id=batch_id,
        url=pending_url,
        status=helper.RECORD_NEEDS_REVIEW,
        page_type="artwork",
        confidence=0.2,
        is_update=False,
        proposed={"title": "Needs Review Work", "url": pending_url, "images": []},
        error="low confidence",
    )

    monkeypatch.setattr(
        helper,
        "_repo_publish_config",
        lambda root: {
            "branch": "main",
            "upstream": "origin/main",
            "remote_name": "origin",
            "remote_branch": "main",
            "remote_url": "git@example.com:test/repo.git",
            "user_name": "Tester",
            "user_email": "tester@example.com",
        },
    )
    monkeypatch.setattr(
        helper,
        "_merge_accepted_records",
        lambda _: ([{"title": "Accepted Work", "url": accepted_url, "images": []}], 1, 0),
    )
    monkeypatch.setattr(helper, "_write_workspace_works", lambda works: None)
    monkeypatch.setattr(helper, "_generate_workspace_markdown", lambda works: None)
    monkeypatch.setattr(helper, "_validate_workspace_outputs", lambda: None)
    monkeypatch.setattr(helper, "_sync_workspace_to_repo", lambda _: "abc123")
    monkeypatch.setattr(helper, "_copy_published_baseline_to_workspace", lambda batch_id, sha: None)

    helper.apply_accepted_records(batch_id)

    cache = json.loads(sitemap_path.read_text(encoding="utf-8"))
    # The unresolved record's URL is freed so the next sync can rediscover it...
    assert pending_url not in cache
    # ...while the applied record stays cached (already persisted to the baseline).
    assert accepted_url in cache
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0] == 1


def test_apply_accepted_records_rejects_branch_mismatch(tmp_path, monkeypatch):
    helper = _load_helper_module()

    remote_repo = tmp_path / "remote.git"
    working_repo = tmp_path / "source"
    subprocess.run(["git", "init", "--bare", str(remote_repo)], check=True, capture_output=True, text=True)
    working_repo.mkdir()
    _run_git(working_repo, "init", "-b", "main")
    _run_git(working_repo, "config", "user.name", "Tester")
    _run_git(working_repo, "config", "user.email", "tester@example.com")
    (working_repo / "aaajiao_works.json").write_text("[]\n", encoding="utf-8")
    (working_repo / "aaajiao_portfolio.md").write_text("# Portfolio\n", encoding="utf-8")
    _run_git(working_repo, "add", "aaajiao_works.json", "aaajiao_portfolio.md")
    _run_git(working_repo, "commit", "-m", "initial")
    _run_git(working_repo, "remote", "add", "origin", str(remote_repo))
    _run_git(working_repo, "push", "-u", "origin", "main")
    # Simulate a developer working off the baseline branch, with its own upstream, rather
    # than a detached HEAD or a missing upstream (already covered by _repo_publish_config's
    # own contract; this is the "current branch is real but wrong" case).
    _run_git(working_repo, "checkout", "-b", "feature/other-work")
    _run_git(working_repo, "push", "-u", "origin", "feature/other-work")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(working_repo))

    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/test-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.99,
        is_update=False,
        proposed={"title": "Test Work", "url": "https://eventstructure.com/test-work", "images": []},
        error=None,
    )

    preview = helper.get_apply_preview(batch_id)
    assert preview["will_push"] is False
    assert "does not match the baseline branch" in preview["error_message"]

    with pytest.raises(RuntimeError, match="does not match the baseline branch"):
        helper.apply_accepted_records(batch_id)

    # Rejected before any workspace/git mutation: no push, no half-applied batch state,
    # and the accepted record is still there to retry once the user switches branches.
    assert _run_git(working_repo, "rev-parse", "HEAD") == _run_git(working_repo, "rev-parse", "refs/heads/feature/other-work")
    with helper.connect_db() as conn:
        row = conn.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)).fetchone()
        record_count = conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0]
    assert row["status"] == helper.BATCH_FAILED
    assert record_count == 1


def test_apply_accepted_records_marks_batch_failed_with_real_stderr_on_push_rejection_and_allows_retry(
    tmp_path, monkeypatch
):
    helper = _load_helper_module()
    monkeypatch.setattr(helper, "_fetch_website_order", lambda: ["https://eventstructure.com/test-work"])

    remote_repo = tmp_path / "remote.git"
    working_repo = tmp_path / "source"
    subprocess.run(["git", "init", "--bare", str(remote_repo)], check=True, capture_output=True, text=True)
    working_repo.mkdir()
    _run_git(working_repo, "init", "-b", "main")
    _run_git(working_repo, "config", "user.name", "Tester")
    _run_git(working_repo, "config", "user.email", "tester@example.com")
    (working_repo / "aaajiao_works.json").write_text("[]\n", encoding="utf-8")
    (working_repo / "aaajiao_portfolio.md").write_text("# Portfolio\n", encoding="utf-8")
    _run_git(working_repo, "add", "aaajiao_works.json", "aaajiao_portfolio.md")
    _run_git(working_repo, "commit", "-m", "initial")
    _run_git(working_repo, "remote", "add", "origin", str(remote_repo))
    _run_git(working_repo, "push", "-u", "origin", "main")

    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(working_repo))

    batch_id = helper._create_batch("manual")
    helper._insert_record(
        batch_id=batch_id,
        url="https://eventstructure.com/test-work",
        status=helper.RECORD_ACCEPTED,
        page_type="artwork",
        confidence=0.99,
        is_update=False,
        proposed={"title": "Test Work", "url": "https://eventstructure.com/test-work", "images": []},
        error=None,
    )

    monkeypatch.setattr(
        helper,
        "_merge_accepted_records",
        lambda _: ([{"title": "Published Work", "url": "https://eventstructure.com/test-work", "images": []}], 1, 0),
    )
    monkeypatch.setattr(
        helper,
        "_generate_workspace_markdown",
        lambda works: (helper.workspace_root() / "aaajiao_portfolio.md").write_text("# Published\n", encoding="utf-8"),
    )

    original_create_commit = helper._create_commit_from_publish_repo

    def create_commit_and_race_remote(root, applied_batch_id):
        sha = original_create_commit(root, applied_batch_id)
        # Simulate a second apply (or a manual push) landing on the remote branch after
        # publish_repo was cloned but before this push executes, so our push is rejected
        # as a non-fast-forward -- the most common real-world push failure.
        foreign_clone = tmp_path / "foreign_push"
        _run_git(tmp_path, "clone", "--branch", "main", "--single-branch", str(remote_repo), str(foreign_clone))
        _run_git(foreign_clone, "config", "user.name", "Concurrent Apply")
        _run_git(foreign_clone, "config", "user.email", "concurrent@example.com")
        (foreign_clone / "unrelated.txt").write_text("advance\n", encoding="utf-8")
        _run_git(foreign_clone, "add", "unrelated.txt")
        _run_git(foreign_clone, "commit", "-m", "concurrent apply landed first")
        _run_git(foreign_clone, "push", "origin", "HEAD:main")
        return sha

    monkeypatch.setattr(helper, "_create_commit_from_publish_repo", create_commit_and_race_remote)

    with pytest.raises(RuntimeError) as exc_info:
        helper.apply_accepted_records(batch_id)

    error_message = str(exc_info.value)
    assert "Failed to publish reviewed changes to GitHub" in error_message
    # The real git stderr must reach the user, not a bare "exit status 1".
    assert "rejected" in error_message.lower() or "fetch first" in error_message.lower()

    with helper.connect_db() as conn:
        row = conn.execute("SELECT status, last_error FROM batches WHERE id = ?", (batch_id,)).fetchone()
        record_count = conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0]

    assert row["status"] == helper.BATCH_FAILED
    # last_error carries the same real stderr, not a generic CalledProcessError string.
    assert row["last_error"] == helper._fatal_error_message(exc_info.value)
    # A rejected push must not silently drop the accepted record -- it must survive for retry.
    assert record_count == 1

    # Retry: once the transient conflict is gone (publish_repo re-clones fresh each call),
    # the same batch can be applied again without any manual repair.
    monkeypatch.setattr(helper, "_create_commit_from_publish_repo", original_create_commit)
    retry_response = helper.apply_accepted_records(batch_id)

    assert retry_response["batch_id"] == batch_id
    assert retry_response["applied_commit_sha"]
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (batch_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0] == 0


def _transaction_fixture(tmp_path, monkeypatch, *, real_markdown=False):
    helper = _load_helper_module()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    remote, source, _ = _prepare_baseline_remote(tmp_path)
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AAAJIAO_REPO_ROOT", str(source))
    helper.ensure_workspace()
    for name in helper.TARGET_FILES:
        (helper.workspace_root() / name).write_bytes((source / name).read_bytes())
    monkeypatch.setattr(helper, "_fetch_website_order", lambda: ["https://eventstructure.com/remote-baseline-work"])
    if not real_markdown:
        monkeypatch.setattr(
            helper, "_generate_markdown_at",
            lambda works, path: path.write_text("# Portfolio\n" + "\n".join(work["title"] for work in works), encoding="utf-8"),
        )
    return helper, remote, source


def _review_fixture(helper, batch_id, *, title="Imported Work", url="https://eventstructure.com/imported-work", status=None):
    proposed = {"url": url, "title": title, "images": [], "description_en": f"{title} description"}
    helper._insert_record(
        batch_id=batch_id, url=url, status=status or helper.RECORD_ACCEPTED,
        page_type="artwork", confidence=0.99, is_update=url in helper._existing_urls(),
        proposed=proposed, error="Network unavailable" if status == helper.RECORD_FAILED else None,
    )
    return helper._record_rows(batch_id=batch_id)[0]["id"]


def _remote_works(remote):
    return json.loads(_run_git(remote, "show", "refs/heads/main:aaajiao_works.json"))


def test_publish_replays_only_reviewed_delta_onto_latest_remote(tmp_path, monkeypatch):
    helper, remote, source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    _review_fixture(helper, batch_id)
    remote_works = _remote_works(remote)
    remote_works[0]["description_en"] = "A remote correction made during review.\n\nKeep this formatting."
    remote_works.append({"title": "Remote Addition", "url": "https://eventstructure.com/remote-addition", "images": []})
    remote_works.append({"title": "Another Remote Addition", "url": "https://eventstructure.com/another-remote-addition", "images": []})
    monkeypatch.setattr(helper, "_fetch_website_order", lambda: [
        "https://eventstructure.com/imported-work", remote_works[0]["url"],
    ])
    (source / helper.REPO_WORKS).write_text(json.dumps(remote_works), encoding="utf-8")
    _run_git(source, "add", helper.REPO_WORKS)
    _run_git(source, "commit", "-m", "remote artwork update during review")
    _run_git(source, "push")

    response = helper.apply_accepted_records(batch_id)

    published = _remote_works(remote)
    assert published[0]["title"] == "Imported Work"
    assert published[1:] == remote_works
    assert response["applied_commit_sha"] == _run_git(remote, "rev-parse", "refs/heads/main")
    assert helper._load_workspace_works() == published


def test_dry_run_and_publish_use_website_order_with_real_markdown(tmp_path, monkeypatch):
    helper, remote, source = _transaction_fixture(tmp_path, monkeypatch, real_markdown=True)
    baseline = helper._load_workspace_works()
    original = baseline[0]
    other = dict(original, title="Website First", url="https://eventstructure.com/website-first", year="2001")
    baseline.append(other)
    (source / helper.REPO_WORKS).write_text(json.dumps(baseline), encoding="utf-8")
    _run_git(source, "add", helper.REPO_WORKS)
    _run_git(source, "commit", "-m", "second baseline artwork")
    _run_git(source, "push")
    helper._write_workspace_works(baseline)
    baseline_bytes = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}

    batch_id = helper._create_batch("manual")
    updated_id = _review_fixture(helper, batch_id, title=original["title"], url=original["url"])
    helper.update_record(updated_id, {"title": "Updated Baseline", "year": "2099"})
    helper.accept_record(updated_id)
    new_url = "https://eventstructure.com/inserted-work"
    new_id = _review_fixture(helper, batch_id, title="Inserted Work", url=new_url)
    helper.update_record(new_id, {"year": "1998"})
    helper.accept_record(new_id)
    expected_urls = [other["url"], new_url, original["url"]]
    fetches = []

    def website_order():
        fetches.append(True)
        return expected_urls

    monkeypatch.setattr(helper, "_fetch_website_order", website_order)
    preview = helper.get_apply_preview(batch_id)
    assert (preview["new_count"], preview["updated_count"]) == (1, 1)
    assert fetches == [], "Count-only previews must not fetch the website"

    dry_run = helper.apply_accepted_records(batch_id, dry_run=True)
    staging = Path(dry_run["staging_path"])
    staged_json = json.loads((staging / helper.REPO_WORKS).read_text())
    staged_markdown = (staging / helper.REPO_PORTFOLIO).read_text()
    assert [work["url"] for work in staged_json] == expected_urls
    assert re.findall(r"^### \[.*?\]\(([^)]+)\)", staged_markdown, flags=re.MULTILINE) == expected_urls
    assert not re.search(r"^## \d", staged_markdown, flags=re.MULTILINE)
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == baseline_bytes

    helper.apply_accepted_records(batch_id)

    assert fetches == [True, True], "Each output transaction needs one verified website order"
    assert _remote_works(remote) == staged_json
    assert _run_git(remote, "show", "refs/heads/main:aaajiao_portfolio.md") == staged_markdown.strip()
    assert helper._load_workspace_works() == staged_json
    assert staged_json[-1]["title"] == "Updated Baseline"


@pytest.mark.parametrize("dry_run", [False, True])
def test_website_order_failure_leaves_outputs_and_queue_retryable(tmp_path, monkeypatch, dry_run):
    helper, remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id)
    original_head = _run_git(remote, "rev-parse", "refs/heads/main")
    baseline_bytes = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    expected_urls = ["https://eventstructure.com/imported-work", "https://eventstructure.com/remote-baseline-work"]
    original_write = helper._generate_markdown_at

    def unavailable():
        raise RuntimeError("Website returned an incomplete project list")

    monkeypatch.setattr(helper, "_fetch_website_order", unavailable)
    monkeypatch.setattr(helper, "_generate_markdown_at", lambda *args: pytest.fail("Do not write unverified output"))
    assert helper.get_apply_preview(batch_id)["will_push"] is True
    with pytest.raises(RuntimeError, match="Could not verify the website artwork order.*No changes were published"):
        helper.apply_accepted_records(batch_id, dry_run=dry_run)

    assert _run_git(remote, "rev-parse", "refs/heads/main") == original_head
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == baseline_bytes
    row = helper._record_rows(batch_id=batch_id)[0]
    assert (row["id"], row["status"]) == (record_id, helper.RECORD_ACCEPTED)
    assert not helper._publish_receipt_path(batch_id).exists()
    assert not (helper.workspace_root() / "apply_previews" / f"batch-{batch_id}").exists()
    with helper.connect_db() as conn:
        batch = conn.execute("SELECT status, last_error FROM batches WHERE id = ?", (batch_id,)).fetchone()
        assert batch["status"] == helper.BATCH_FAILED
        assert "website artwork order" in batch["last_error"]

    monkeypatch.setattr(helper, "_fetch_website_order", lambda: expected_urls)
    monkeypatch.setattr(helper, "_generate_markdown_at", original_write)
    response = helper.apply_accepted_records(batch_id)
    assert response["applied_commit_sha"] != original_head
    assert [work["url"] for work in _remote_works(remote)] == expected_urls


@pytest.mark.parametrize("fixture", [
    [], {}, "https://eventstructure.com/work", [None], [5],
    ["https://eventstructure.com/"], ["https://elsewhere.example/work"],
    ["file:///private/work"], ["https://user:password@eventstructure.com/work"],
    ["https://eventstructure.com/work", "http://www.eventstructure.com/work/?preview=1"],
])
def test_offline_website_order_fixture_rejects_invalid_or_duplicate_urls(tmp_path, monkeypatch, fixture):
    helper = _load_helper_module()
    fixture_path = tmp_path / "order.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setenv("AAAJIAO_IMPORTER_SITE_ORDER_FILE", str(fixture_path))
    output = tmp_path / "output"
    with pytest.raises(RuntimeError, match="Could not verify the website artwork order"):
        helper._write_apply_outputs(output, [{"url": "https://eventstructure.com/work", "title": "Work"}])
    assert not output.exists()


def test_website_order_fixture_is_read_only_and_default_fetches_live(tmp_path, monkeypatch):
    helper = _load_helper_module()
    site_order = importlib.import_module("scraper.site_order")
    live_calls = []
    monkeypatch.setattr(site_order, "fetch_website_order", lambda: (live_calls.append(True), ["https://eventstructure.com/live"])[1])
    assert helper._fetch_website_order() == ["https://eventstructure.com/live"]
    fixture = tmp_path / "order.json"
    fixture_bytes = b'["http://www.eventstructure.com/Fixture/?view=1", "https://eventstructure.com/second"]\n'
    fixture.write_bytes(fixture_bytes)
    monkeypatch.setenv("AAAJIAO_IMPORTER_SITE_ORDER_FILE", str(fixture))
    assert helper._fetch_website_order() == ["https://eventstructure.com/Fixture", "https://eventstructure.com/second"]
    assert live_calls == [True]
    assert fixture.read_bytes() == fixture_bytes


@pytest.mark.parametrize("unknown_legacy_snapshot", [False, True])
def test_publish_blocks_same_artwork_conflicts_and_unknown_legacy_updates(tmp_path, monkeypatch, unknown_legacy_snapshot):
    helper, remote, source = _transaction_fixture(tmp_path, monkeypatch)
    original = helper._load_workspace_works()[0]
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, title=original["title"], url=original["url"])
    if unknown_legacy_snapshot:
        with helper.connect_db() as conn:
            conn.execute("UPDATE records SET baseline_record_json = NULL WHERE id = ?", (record_id,))
    else:
        current = dict(original, description_en="Concurrent remote correction")
        (source / helper.REPO_WORKS).write_text(json.dumps([current]), encoding="utf-8")
        _run_git(source, "add", helper.REPO_WORKS)
        _run_git(source, "commit", "-m", "same artwork changed remotely")
        _run_git(source, "push")
    remote_head = _run_git(remote, "rev-parse", "refs/heads/main")
    workspace_before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}

    with pytest.raises(RuntimeError, match="no original artwork snapshot" if unknown_legacy_snapshot else "Artwork changed on the remote"):
        helper.apply_accepted_records(batch_id)

    assert _run_git(remote, "rev-parse", "refs/heads/main") == remote_head
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == workspace_before
    assert helper._record_rows(batch_id=batch_id)[0]["status"] == helper.RECORD_ACCEPTED


def test_failed_publish_and_discard_do_not_leak_into_another_batch(tmp_path, monkeypatch):
    helper, remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    first = helper._create_batch("manual")
    _review_fixture(helper, first, title="Discarded Work", url="https://eventstructure.com/discarded-work")
    original_run_git = helper._run_git

    def reject_push(root, args, **kwargs):
        if args[0] == "push":
            raise subprocess.CalledProcessError(1, ["git", *args], stderr="fixture rejected push")
        return original_run_git(root, args, **kwargs)

    with monkeypatch.context() as attempt:
        attempt.setattr(helper, "_run_git", reject_push)
        with pytest.raises(RuntimeError, match="fixture rejected push"):
            helper.apply_accepted_records(first)
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == before
    helper.delete_batch(first)
    second = helper._create_batch("manual")
    _review_fixture(helper, second, title="Retained Work", url="https://eventstructure.com/retained-work")

    helper.apply_accepted_records(second)

    assert [work["title"] for work in _remote_works(remote)] == ["Remote Baseline Work", "Retained Work"]


def test_published_commit_survives_local_finalization_failure_and_retry(tmp_path, monkeypatch):
    helper, remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    _review_fixture(helper, batch_id)
    with monkeypatch.context() as attempt:
        attempt.setattr(helper, "_copy_published_baseline_to_workspace", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
        response = helper.apply_accepted_records(batch_id)
    sha = _run_git(remote, "rev-parse", "refs/heads/main")
    assert response["applied_commit_sha"] == sha
    assert "Published commit" in response["warning_message"]
    assert "disk unavailable" in response["warning_message"]
    assert helper.prune_terminal_batches() == 0
    assert helper.get_batch_detail(batch_id)["batch"]["status"] == helper.BATCH_COMPLETED

    retry = helper.apply_accepted_records(batch_id)

    assert retry["applied_commit_sha"] == sha
    assert "warning_message" not in retry
    assert _run_git(remote, "rev-parse", "refs/heads/main") == sha
    assert helper._load_workspace_works() == _remote_works(remote)
    assert not helper._publish_receipt_path(batch_id).exists()


def test_retry_resolves_a_push_that_succeeded_before_response_was_lost(tmp_path, monkeypatch):
    helper, remote, source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    _review_fixture(helper, batch_id)
    original_run_git = helper._run_git

    def lose_push_response(root, args, **kwargs):
        result = original_run_git(root, args, **kwargs)
        if args[0] == "push":
            raise RuntimeError("Push response was lost")
        return result

    with monkeypatch.context() as attempt:
        attempt.setattr(helper, "_run_git", lose_push_response)
        with pytest.raises(RuntimeError, match="Push response was lost"):
            helper.apply_accepted_records(batch_id)
    sha = _run_git(remote, "rev-parse", "refs/heads/main")
    assert helper._load_json(helper._publish_receipt_path(batch_id))["status"] == "prepared"
    # A later remote commit must not prevent recognizing the successful candidate.
    _run_git(source, "pull", "--ff-only")
    (source / "later.txt").write_text("remote advanced\n")
    _run_git(source, "add", "later.txt")
    _run_git(source, "commit", "-m", "remote advance after successful push")
    _run_git(source, "push")
    head = _run_git(remote, "rev-parse", "refs/heads/main")

    result = helper.apply_accepted_records(batch_id)

    assert result["applied_commit_sha"] == sha
    assert _run_git(remote, "rev-parse", "refs/heads/main") == head
    assert not helper._publish_receipt_path(batch_id).exists()


def test_unknown_previous_push_outcome_blocks_new_push_and_discard(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    _review_fixture(helper, batch_id)
    original_run_git = helper._run_git

    def timeout_push(root, args, **kwargs):
        if args[0] == "push":
            raise RuntimeError("Network timeout")
        return original_run_git(root, args, **kwargs)

    with monkeypatch.context() as attempt:
        attempt.setattr(helper, "_run_git", timeout_push)
        with pytest.raises(RuntimeError, match="Network timeout"):
            helper.apply_accepted_records(batch_id)
    monkeypatch.setattr(helper, "_ensure_publish_repo", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    for operation in (helper.apply_accepted_records, helper.delete_batch):
        with pytest.raises(RuntimeError, match="previous push outcome is not yet confirmed"):
            operation(batch_id)
    assert helper._publish_receipt_path(batch_id).exists()
    assert helper._record_rows(batch_id=batch_id)[0]["status"] == helper.RECORD_ACCEPTED


def test_dry_run_generates_staging_without_mutating_workspace_or_remote(tmp_path, monkeypatch):
    helper, remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    _review_fixture(helper, batch_id)
    before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    head = _run_git(remote, "rev-parse", "refs/heads/main")

    result = helper.apply_accepted_records(batch_id, dry_run=True)

    assert result["dry_run"] is True
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == before
    assert _run_git(remote, "rev-parse", "refs/heads/main") == head
    assert json.loads((Path(result["staging_path"]) / helper.REPO_WORKS).read_text())[-1]["title"] == "Imported Work"
    assert helper._record_rows(batch_id=batch_id)[0]["status"] == helper.RECORD_ACCEPTED


def _import_result(url):
    return {
        "should_apply": True, "page_type": "artwork", "confidence": .99,
        "proposed": {"title": url.rsplit("/", 1)[-1], "url": url, "images": []},
        "rejection_reason": "",
    }


def _fake_incremental_modules(helper, sitemap):
    class Scraper:
        def __init__(self, use_cache):
            pass

        def _save_sitemap_cache(self, data):
            helper._write_json_atomic(helper._workspace_sitemap_cache_path(), data)

        def get_all_work_links(self, incremental):
            old = helper._load_workspace_sitemap_cache()
            urls = [url for url, stamp in sitemap.items() if old.get(url) != stamp]
            self._save_sitemap_cache(sitemap)
            return urls

    return {"AaajiaoScraper": Scraper}


def test_interrupted_incremental_does_not_checkpoint_unprocessed_urls(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    urls = [f"https://eventstructure.com/candidate-{index}" for index in range(3)]
    sitemap = dict.fromkeys(urls, "2026-09-07")
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, sitemap))
    seen = []

    def interrupted_import(url, modules):
        seen.append(url)
        if len(seen) == 2:
            raise KeyboardInterrupt("fixture cancellation")
        return _import_result(url)

    monkeypatch.setattr(helper, "_import_url", interrupted_import)
    with pytest.raises(KeyboardInterrupt):
        helper.start_incremental_sync()
    assert len(helper._record_rows()) == 1
    assert all(url not in helper._load_workspace_sitemap_cache() for url in urls)
    retried = []
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: (retried.append(url), _import_result(url))[1])

    helper.start_incremental_sync()

    assert retried == urls[1:]
    assert len(helper._record_rows()) == 3
    assert helper.start_incremental_sync()["urls_processed"] == 0


@pytest.mark.parametrize("mode", ["manual", "incremental"])
def test_cancel_before_first_record_leaves_prunable_draft(tmp_path, monkeypatch, mode):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    url = "https://eventstructure.com/cancel-before-first"
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, {url: "2026-09-07"}))
    monkeypatch.setattr(helper, "_import_url", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt("cancel")))
    with pytest.raises(KeyboardInterrupt):
        if mode == "manual":
            helper.submit_manual_url(url)
        else:
            helper.start_incremental_sync()
    assert helper._record_rows() == []
    assert not helper._workspace_has_active_review_state()
    assert helper.prune_terminal_batches() == 1
    assert url not in helper._load_workspace_sitemap_cache()


def test_partial_apply_confirms_only_published_urls_and_keeps_failed_record_retryable(tmp_path, monkeypatch):
    helper, remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    accepted_url = "https://eventstructure.com/accepted-work"
    failed_url = "https://eventstructure.com/failed-work"
    sitemap = {accepted_url: "2026-09-07", failed_url: "2026-09-07"}
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, sitemap))

    def import_url(url, modules):
        if url == failed_url:
            raise RuntimeError("Temporary network failure")
        return _import_result(url)

    monkeypatch.setattr(helper, "_import_url", import_url)
    batch_id = helper.start_incremental_sync()["batch_id"]
    rows = helper._record_rows(batch_id=batch_id)
    failed_id = next(row["id"] for row in rows if row["url"] == failed_url)
    helper.accept_record(next(row["id"] for row in rows if row["url"] == accepted_url))

    response = helper.apply_accepted_records(batch_id)

    assert response["remaining_records"] == 1
    assert helper._load_workspace_sitemap_cache().get(accepted_url) == "2026-09-07"
    assert failed_url not in helper._load_workspace_sitemap_cache()
    remaining = helper.get_batch_detail(batch_id)["records"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == failed_id
    assert remaining[0]["error_message"] == "Temporary network failure"
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: _import_result(url))
    assert helper.retry_record(failed_id)["status"] == helper.RECORD_READY_FOR_REVIEW
    helper.accept_record(failed_id)
    helper.apply_accepted_records(batch_id)
    assert helper._load_workspace_sitemap_cache().get(failed_url) == "2026-09-07"
    assert len(_remote_works(remote)) == 3


def test_retry_record_preserves_identity_original_error_and_attempt_history(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, status=helper.RECORD_FAILED)
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: {})
    monkeypatch.setattr(helper, "_import_url", lambda *args: (_ for _ in ()).throw(RuntimeError("Retry request timed out")))

    with pytest.raises(RuntimeError, match="Retry request timed out"):
        helper.retry_record(record_id)
    failed = helper.get_batch_detail(batch_id)["records"][0]
    assert failed["id"] == record_id
    assert failed["status"] == helper.RECORD_FAILED
    assert failed["retry_count"] == 1
    assert [item["message"] for item in failed["error_history"]] == ["Network unavailable", "Retry request timed out"]
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: _import_result(url))

    result = helper.retry_record(record_id)

    record = helper.get_batch_detail(batch_id)["records"][0]
    assert result == {"id": record_id, "batch_id": batch_id, "status": helper.RECORD_READY_FOR_REVIEW}
    assert len(helper._record_rows(batch_id=batch_id)) == 1
    assert record["retry_count"] == 2
    assert record["error_message"] is None
    assert len(record["error_history"]) == 2
    assert record["baseline_available"] is True
    assert record["baseline_record"] is None


def test_manual_import_captures_baseline_before_network_work(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    original = helper._load_workspace_works()[0]
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: {})

    def import_with_baseline_change(url, modules):
        helper._write_workspace_works([dict(original, description_en="Changed during network request")])
        return _import_result(url)

    monkeypatch.setattr(helper, "_import_url", import_with_baseline_change)
    response = helper.submit_manual_url(original["url"])
    record = helper.get_batch_detail(response["batch_id"])["records"][0]
    assert record["baseline_record"] == original


def test_parse_args_accepts_retry_record(monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setattr(sys, "argv", ["helper", "retryRecord", "--id", "17"])
    args = helper.parse_args()
    assert args.command == "retryRecord"
    assert args.id == 17


def test_optional_vacuum_failure_does_not_turn_cleanup_into_failure(tmp_path, monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("AAAJIAO_IMPORTER_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    helper.ensure_workspace()
    monkeypatch.setattr(helper.sqlite3, "connect", lambda *args: (_ for _ in ()).throw(helper.sqlite3.OperationalError("busy")))
    helper._vacuum_db_if_needed()


def test_explicit_review_edits_match_comparison_dry_run_and_published_output(tmp_path, monkeypatch):
    helper, remote, source = _transaction_fixture(tmp_path, monkeypatch)
    original = dict(
        helper._load_workspace_works()[0],
        title_cn="原作品标题", materials="A long original materials description", credits="Original credits",
        description_cn="原始中文段落。\n\n保留历史快照。",
        images=["https://example.com/original-one.jpg", "https://example.com/original-two.jpg"],
        high_res_images=["https://example.com/original-large.jpg"], video_link="https://vimeo.com/original",
    )
    helper._write_workspace_works([original])
    (source / helper.REPO_WORKS).write_text(json.dumps([original]), encoding="utf-8")
    _run_git(source, "add", helper.REPO_WORKS)
    _run_git(source, "commit", "-m", "rich baseline fixture")
    _run_git(source, "push")
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, title=original["title"], url=original["url"])
    before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    before_head = _run_git(remote, "rev-parse", "refs/heads/main")
    before_record = helper._record_rows(batch_id=batch_id)[0]
    edits = {
        "description_en": "Short.\n\nExactly two paragraphs.", "description_cn": "", "materials": "", "credits": "",
        "title_cn": "", "images": "", "high_res_images": " https://example.com/replacement.jpg \n\n", "video_link": "",
        "year": original["year"],
    }

    response = helper.update_record(record_id, edits)

    assert response == {"id": record_id, "status": helper.RECORD_NEEDS_REVIEW}
    assert helper.get_apply_preview(batch_id)["accepted_count"] == 0
    record = helper.get_batch_detail(batch_id)["records"][0]
    assert record["baseline_fields"]["images"] == "\n".join(original["images"])
    assert record["baseline_fields"]["description_cn"] == original["description_cn"]
    assert record["baseline_record"] == original
    assert record["effective_fields"]["materials"] == ""
    assert record["effective_fields"]["images"] == ""
    assert record["effective_fields"]["high_res_images"] == "https://example.com/replacement.jpg"
    assert record["description_en"] == edits["description_en"]
    assert record["description_cn"] == record["credits"] == record["video_link"] == ""
    assert record["images"] == []
    assert record["high_res_images"] == ["https://example.com/replacement.jpg"]
    saved = helper._record_rows(batch_id=batch_id)[0]
    assert saved["proposed_record_json"] == before_record["proposed_record_json"]
    assert saved["baseline_record_json"] == before_record["baseline_record_json"]
    assert "year" not in json.loads(saved["edited_fields_json"])
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == before
    assert _run_git(remote, "rev-parse", "refs/heads/main") == before_head

    helper.accept_record(record_id)
    dry_run = helper.apply_accepted_records(batch_id, dry_run=True)
    staged = json.loads((Path(dry_run["staging_path"]) / helper.REPO_WORKS).read_text())[0]
    assert helper._review_fields(staged) == record["effective_fields"]
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == before
    helper.apply_accepted_records(batch_id)
    assert _remote_works(remote)[0] == staged


def test_review_edit_patches_are_cumulative_and_revoke_prior_acceptance(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id)
    helper.update_record(record_id, {"description_en": "One sentence."})
    helper.accept_record(record_id)

    helper.update_record(record_id, {"title": "Renamed Artwork", "images": "https://example.com/first.jpg\nhttps://example.com/second.jpg"})

    record = helper.get_batch_detail(batch_id)["records"][0]
    assert record["status"] == helper.RECORD_NEEDS_REVIEW
    assert record["description_en"] == "One sentence."
    assert record["title"] == "Renamed Artwork"
    assert record["url"] == "https://eventstructure.com/imported-work"
    assert record["images"] == ["https://example.com/first.jpg", "https://example.com/second.jpg"]
    assert set(json.loads(helper._record_rows(batch_id=batch_id)[0]["edited_fields_json"])) == {"description_en", "title", "images"}


@pytest.mark.parametrize("edits", [
    {"url": "https://eventstructure.com/another-work"},
    {"source": "changed"},
    {"unknown_field": "changed"},
    {"title": "  \n  "},
    {"images": "javascript:alert(1)"},
    {"images": "https://example.com/ok.jpg\nfile:///tmp/local.jpg"},
    {"high_res_images": "/relative/image.jpg"},
    {"video_link": "https://example.com:invalid-port/video"},
    {"video_link": "ftp://example.com/video"},
    {"images": ["https://example.com/not-a-string.jpg"]},
])
def test_invalid_review_edits_are_rejected_without_changing_record(tmp_path, monkeypatch, edits):
    helper, remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id)
    before = dict(helper._record_rows(batch_id=batch_id)[0])
    head = _run_git(remote, "rev-parse", "refs/heads/main")

    with pytest.raises(RuntimeError):
        helper.update_record(record_id, edits)

    assert dict(helper._record_rows(batch_id=batch_id)[0]) == before
    assert _run_git(remote, "rev-parse", "refs/heads/main") == head


@pytest.mark.parametrize("locked_state", ["failed", "prepared", "published"])
def test_failed_or_publication_locked_records_cannot_be_edited(tmp_path, monkeypatch, locked_state):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, status=helper.RECORD_FAILED if locked_state == "failed" else None)
    if locked_state != "failed":
        helper._publication_root(batch_id).mkdir(parents=True)
        helper._write_json_atomic(helper._publish_receipt_path(batch_id), {"status": locked_state})
    before = dict(helper._record_rows(batch_id=batch_id)[0])

    with pytest.raises(RuntimeError, match="failed import|pending publication"):
        helper.update_record(record_id, {"title": "Should not be saved"})

    assert dict(helper._record_rows(batch_id=batch_id)[0]) == before


def test_review_fields_distinguish_unknown_baseline_from_known_new_work(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id)
    known = helper.get_batch_detail(batch_id)["records"][0]
    assert known["baseline_available"] is True
    assert known["baseline_fields"] == dict.fromkeys(helper.EDITABLE_FIELDS, "")
    with helper.connect_db() as conn:
        conn.execute("UPDATE records SET baseline_record_json = NULL WHERE id = ?", (record_id,))

    unknown = helper.get_batch_detail(batch_id)["records"][0]

    assert unknown["baseline_available"] is False
    assert unknown["baseline_fields"] is None
    assert unknown["effective_fields"] == known["effective_fields"]


def test_update_record_cli_reads_edits_file(tmp_path, monkeypatch, capsys):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id)
    edits_file = tmp_path / "edits.json"
    edits_file.write_text(json.dumps({"title_cn": "人工校订标题", "description_en": "Concise."}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["helper", "updateRecord", "--id", str(record_id), "--edits-file", str(edits_file)])

    helper.main()

    assert json.loads(capsys.readouterr().out) == {"id": record_id, "status": helper.RECORD_NEEDS_REVIEW}
    record = helper.get_batch_detail(batch_id)["records"][0]
    assert record["title_cn"] == "人工校订标题"
    assert record["effective_fields"]["description_en"] == "Concise."


class _OpenAIHTTPFixture:
    def __init__(self, get_response, post_response=None, get_error=None):
        self.get_response = get_response
        self.post_response = post_response
        self.get_error = get_error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.get_error:
            raise self.get_error
        return self.get_response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.post_response


def _auth_extraction_fixture(helper, monkeypatch, sitemap, *, status=401):
    modules = _fake_incremental_modules(helper, sitemap)
    seen = []

    def extract(_self, url):
        seen.append(url)
        return {
            "title": url.rsplit("/", 1)[-1], "url": url, "year": "2026", "type": "installation",
            "materials": "steel", "description_en": "Extracted artwork description", "images": ["https://example.com/image.jpg"],
        }

    modules["AaajiaoScraper"].extract_metadata_bs4 = extract
    modules["AaajiaoScraper"].extract_work_details_v2 = lambda self, url: self.extract_metadata_bs4(url)
    modules["is_artwork"] = lambda data: True
    modules["normalize_year"] = lambda year: year
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: modules)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    body = {"error": {"message": "Incorrect API key provided: sk-proj-SYNTHETIC***TAIL", "code": "invalid_api_key"}}
    if status != 401:
        body = {"error": {"message": "Model access is not permitted", "code": "insufficient_permissions"}}
    session = _OpenAIHTTPFixture(_make_response(200, b'{"data":[]}'), _make_response(status, json.dumps(body).encode()))
    monkeypatch.setattr(helper, "_OPENAI_HTTP_SESSION", session)
    return seen, session


def test_incremental_stops_after_first_authentication_failure_and_preserves_extraction(tmp_path, monkeypatch, capsys):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    urls = [f"https://eventstructure.com/candidate-{index}" for index in range(7)]
    seen, session = _auth_extraction_fixture(helper, monkeypatch, dict.fromkeys(urls, "2026-09-07"))

    with pytest.raises(helper.OpenAIServiceError) as failure:
        helper.start_incremental_sync()

    assert failure.value.code == "openai_authentication_failed"
    assert str(failure.value).startswith("[OPENAI_AUTHENTICATION_FAILED]")
    assert seen == urls[:1]
    assert [call[0] for call in session.calls] == ["GET", "POST"]
    rows = helper._record_rows()
    assert len(rows) == 1
    assert rows[0]["status"] == helper.RECORD_FAILED
    assert json.loads(rows[0]["proposed_record_json"])["description_en"] == "Extracted artwork description"
    detail = helper.get_batch_detail(rows[0]["batch_id"])
    assert detail["batch"]["status"] == helper.BATCH_FAILED
    assert detail["records"][0]["error_code"] == "openai_authentication_failed"
    assert helper.prune_terminal_batches() == 0
    assert all(url not in helper._load_workspace_sitemap_cache() for url in urls)
    assert "PROGRESS 0/7" in capsys.readouterr().err
    assert "SYNTHETIC" not in json.dumps(detail)
    assert "TAIL" not in helper._fatal_error_message(failure.value)


@pytest.mark.parametrize("operation", ["manual", "retry"])
def test_manual_and_retry_auth_failure_persist_data_and_machine_error(tmp_path, monkeypatch, operation):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    url = "https://eventstructure.com/auth-failure"
    _seen, session = _auth_extraction_fixture(helper, monkeypatch, {url: "2026-09-07"})
    record_id = None
    if operation == "retry":
        batch_id = helper._create_batch("manual")
        record_id = _review_fixture(helper, batch_id, url=url, status=helper.RECORD_FAILED)
    with pytest.raises(helper.OpenAIServiceError, match="OPENAI_AUTHENTICATION_FAILED"):
        if operation == "manual":
            helper.submit_manual_url(url)
        else:
            helper.retry_record(record_id)
    rows = helper._record_rows()
    assert len(rows) == 1
    assert rows[0]["status"] == helper.RECORD_FAILED
    assert rows[0]["error_code"] == "openai_authentication_failed"
    assert json.loads(rows[0]["proposed_record_json"])["images"] == ["https://example.com/image.jpg"]
    if record_id:
        assert rows[0]["id"] == record_id
        assert rows[0]["retry_count"] == 1
    assert [call[0] for call in session.calls] == ["GET", "POST"]


def test_legacy_auth_review_is_sanitized_without_mutation_and_can_retry_in_place(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, status=helper.RECORD_NEEDS_REVIEW)
    old_error = "AI validation failed [gpt-4.1]: Incorrect API key provided: sk-proj-LEGACY***FRAGMENT"
    with helper.connect_db() as conn:
        conn.execute(
            "UPDATE records SET error_message = ?, error_history_json = ? WHERE id = ?",
            (old_error, json.dumps([{"at": "2026-09-07", "message": old_error}]), record_id),
        )
    before = dict(helper._record_rows(batch_id=batch_id)[0])

    record = helper.get_batch_detail(batch_id)["records"][0]

    assert record["status"] == helper.RECORD_NEEDS_REVIEW
    assert record["error_code"] == "openai_authentication_failed"
    assert "LEGACY" not in json.dumps(record)
    assert "FRAGMENT" not in json.dumps(record)
    assert dict(helper._record_rows(batch_id=batch_id)[0]) == before
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: {})
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: _import_result(url))
    result = helper.retry_record(record_id)
    assert result["id"] == record_id
    assert result["status"] == helper.RECORD_READY_FOR_REVIEW
    assert helper.get_batch_detail(batch_id)["records"][0]["error_code"] is None
    assert "LEGACY" not in helper._record_rows(batch_id=batch_id)[0]["error_history_json"]


@pytest.mark.parametrize("status,body,expected", [
    (401, {"error": {"message": "Server echoed arbitrary secret fragments"}}, "openai_authentication_failed"),
    (400, {"error": {"code": "invalid_api_key", "message": "Arbitrary server content"}}, "openai_authentication_failed"),
    (403, {"error": {"code": "insufficient_permissions", "message": "Model permission denied"}}, "openai_permission_denied"),
    (400, {"error": {"code": "invalid_request_error", "message": "Invalid response parameter"}}, "ai_request_failed"),
    (500, {"error": {"message": "Temporarily unavailable"}}, "ai_request_failed"),
])
def test_openai_response_codes_distinguish_auth_permission_and_other_failures(monkeypatch, status, body, expected):
    helper = _load_helper_module()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    session = _OpenAIHTTPFixture(None, _make_response(status, json.dumps(body).encode()))
    monkeypatch.setattr(helper, "_OPENAI_HTTP_SESSION", session)

    result = helper._call_openai_validation("https://eventstructure.com/test-work", {"title": "Test Work"}, {})

    assert result.error_state == expected
    if expected in helper.OPENAI_FATAL_ERRORS:
        assert result.payload.rejection_reason == str(helper.OpenAIServiceError(expected))
        assert "Arbitrary" not in result.payload.rejection_reason
        assert "secret fragments" not in result.payload.rejection_reason
    assert len(session.calls) == 1


def test_openai_preflight_and_validation_reuse_session_with_separate_short_connect_timeout(monkeypatch):
    helper = _load_helper_module()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    session = _OpenAIHTTPFixture(_make_response(200, b'{"data":[]}'), _make_response(500, b'{}'))
    created = []
    monkeypatch.setattr(helper.requests, "Session", lambda: (created.append(session), session)[1])

    assert helper.validate_openai_key()["status"] == "valid"
    helper._call_openai_validation("https://eventstructure.com/test-work", {"title": "Test Work"}, {})

    assert len(created) == 1
    assert session.calls[0][2]["timeout"] == (5, 10)
    assert session.calls[1][2]["timeout"] == (5, 120)
    assert session.calls[0][1] == "https://api.openai.com/v1/models"
    assert session.calls[1][1] == "https://api.openai.com/v1/chat/completions"


@pytest.mark.parametrize("operation", ["incremental", "manual"])
def test_invalid_key_preflight_stops_before_batch_creation_or_site_fetch(tmp_path, monkeypatch, operation):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    session = _OpenAIHTTPFixture(_make_response(401, b'{"error":{"message":"Incorrect API key provided: sk-proj-PREFLIGHT***TAIL"}}'))
    monkeypatch.setattr(helper, "_OPENAI_HTTP_SESSION", session)
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: pytest.fail("Site extraction must not start"))

    with pytest.raises(helper.OpenAIServiceError, match="OPENAI_AUTHENTICATION_FAILED"):
        if operation == "incremental":
            helper.start_incremental_sync()
        else:
            helper.submit_manual_url("https://eventstructure.com/no-fetch")

    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert len(session.calls) == 1


@pytest.mark.parametrize("failure_mode", ["timeout", "server"])
def test_preflight_unavailable_is_not_invalid_key_and_blocks_import(tmp_path, monkeypatch, failure_mode):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    session = _OpenAIHTTPFixture(
        _make_response(503, b'{}'),
        get_error=helper.requests.exceptions.ConnectTimeout("synthetic timeout") if failure_mode == "timeout" else None,
    )
    monkeypatch.setattr(helper, "_OPENAI_HTTP_SESSION", session)
    assert helper.validate_openai_key()["status"] == "unverified"
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: pytest.fail("Site extraction must not start"))

    with pytest.raises(helper.OpenAIServiceError) as failure:
        helper.start_incremental_sync()

    assert failure.value.code == "openai_preflight_failed"
    assert "authentication" not in str(failure.value).lower()
    assert helper._record_rows() == []


def test_models_permission_denied_allows_chat_to_check_actual_model_access(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    url = "https://eventstructure.com/permission-test"
    seen, session = _auth_extraction_fixture(helper, monkeypatch, {url: "2026-09-07"}, status=403)
    session.get_response = _make_response(403, b'{"error":{"message":"Restricted models listing"}}')
    assert helper.validate_openai_key()["reason"] == "restricted_key"

    with pytest.raises(helper.OpenAIServiceError) as failure:
        helper.submit_manual_url(url)

    assert failure.value.code == "openai_permission_denied"
    assert seen == [url]
    assert helper._record_rows()[0]["error_code"] == "openai_permission_denied"


def test_retry_preflight_failure_updates_original_record_without_fetching(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, status=helper.RECORD_FAILED)
    before = helper._record_rows(batch_id=batch_id)[0]["proposed_record_json"]
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    monkeypatch.setattr(helper, "_OPENAI_HTTP_SESSION", _OpenAIHTTPFixture(_make_response(401, b'{}')))
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: pytest.fail("Retry must not fetch after invalid key preflight"))

    with pytest.raises(helper.OpenAIServiceError, match="OPENAI_AUTHENTICATION_FAILED"):
        helper.retry_record(record_id)

    record = helper._record_rows(batch_id=batch_id)[0]
    assert record["id"] == record_id
    assert record["proposed_record_json"] == before
    assert record["retry_count"] == 1
    assert record["error_code"] == "openai_authentication_failed"


def test_validate_openai_key_cli_returns_status_without_echoing_key(monkeypatch, capsys):
    helper = _load_helper_module()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-review-key")
    monkeypatch.setattr(helper, "_OPENAI_HTTP_SESSION", _OpenAIHTTPFixture(_make_response(200, b'{"data":[]}')))
    monkeypatch.setattr(sys, "argv", ["helper", "validateOpenAIKey"])

    helper.main()

    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "valid"
    assert "synthetic-review-key" not in output


def _install_older_seed_fixture(helper, tmp_path, monkeypatch):
    seed = tmp_path / "older-bundled-seed"
    (seed / "cache").mkdir(parents=True)
    (seed / helper.REPO_WORKS).write_text(
        json.dumps([{"title": "Older Seed Work", "url": "https://eventstructure.com/older-seed-work"}]),
        encoding="utf-8",
    )
    (seed / helper.REPO_PORTFOLIO).write_text("# Older bundled portfolio\n", encoding="utf-8")
    (seed / "cache" / "sitemap_lastmod.json").write_text("{}\n", encoding="utf-8")
    manifest = dict(helper._load_seed_manifest(), seed_version="upgrade-checkpoint-v1")
    monkeypatch.setattr(helper, "seed_root", lambda: seed)
    monkeypatch.setattr(helper, "_load_seed_manifest", lambda: manifest)
    helper.ensure_workspace()
    return manifest, seed


def test_publish_then_seed_upgrade_keeps_checkpoints_and_real_later_updates(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    manifest, _seed = _install_older_seed_fixture(helper, tmp_path, monkeypatch)
    urls = ["https://eventstructure.com/published-one", "https://eventstructure.com/published-two"]
    sitemap = dict.fromkeys(urls, "2026-09-07")
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, sitemap))
    imported = []
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: (imported.append(url), _import_result(url))[1])
    batch_id = helper.start_incremental_sync()["batch_id"]
    for row in helper._record_rows(batch_id=batch_id):
        helper.accept_record(row["id"])
    helper.apply_accepted_records(batch_id)
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    checkpoint_before = helper._workspace_sitemap_cache_path().read_bytes()
    cache_extra = helper.workspace_root() / ".cache" / "retained-extraction.pkl"
    cache_extra.write_bytes(b"keep cached extraction")
    receipt = helper._publication_root(999) / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"prepared","commit_sha":"preserve-unconfirmed-receipt"}', encoding="utf-8")
    obsolete_module = helper.snapshot_root() / "scraper" / "obsolete_snapshot_module.py"
    obsolete_module.write_text("old snapshot code\n", encoding="utf-8")

    manifest["seed_version"] = "upgrade-checkpoint-v2"
    assert helper.ensure_workspace() == "ready"

    assert not obsolete_module.exists()
    assert (helper.snapshot_root() / "scraper" / "__init__.py").read_bytes() == (helper.seed_snapshot_root() / "scraper" / "__init__.py").read_bytes()
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == before
    assert helper._workspace_sitemap_cache_path().read_bytes() == checkpoint_before
    assert cache_extra.read_bytes() == b"keep cached extraction"
    assert "preserve-unconfirmed-receipt" in receipt.read_text()
    imported.clear()
    assert helper.start_incremental_sync()["urls_processed"] == 0
    assert imported == []

    sitemap[urls[0]] = "2026-09-08"

    def changed_import(url, modules):
        imported.append(url)
        result = _import_result(url)
        result["proposed"]["description_en"] = "A real artwork description change after publication."
        return result

    monkeypatch.setattr(helper, "_import_url", changed_import)
    changed = helper.start_incremental_sync()
    assert changed["urls_processed"] == 1
    assert imported == [urls[0]]
    assert helper._record_rows(batch_id=changed["batch_id"])[0]["is_update"] == 1


def test_seed_upgrade_with_pending_review_refreshes_code_only_and_skips_baseline(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch, real_markdown=True)
    manifest, _seed = _install_older_seed_fixture(helper, tmp_path, monkeypatch)
    original = helper._load_workspace_works()[0]
    batch_id = helper._create_batch("manual")
    record_id = _review_fixture(helper, batch_id, title=original["title"], url=original["url"])
    helper.update_record(record_id, {"description_en": "Unpublished review edit"})
    records_before = [dict(row) for row in helper._record_rows(batch_id=batch_id)]
    files_before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    helper._write_json_atomic(helper._workspace_sitemap_cache_path(), {original["url"]: "2026-09-07"})
    checkpoint_before = helper._workspace_sitemap_cache_path().read_bytes()
    receipt = helper._publication_root(999) / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"prepared","commit_sha":"keep-receipt"}', encoding="utf-8")
    snapshot = helper.snapshot_root() / "scraper"
    (snapshot / "site_order.py").unlink(missing_ok=True)
    (snapshot / "report.py").write_text("# Old renderer without preserve_order\n", encoding="utf-8")
    obsolete = snapshot / "obsolete.py"
    obsolete.write_text("# Remove obsolete code\n", encoding="utf-8")
    source_snapshot = HELPER_PATH.parents[2] / "portfolio_scraper"
    monkeypatch.setattr(helper, "seed_snapshot_root", lambda: source_snapshot)
    monkeypatch.setattr(helper, "_clone_remote_baseline_repo", lambda: pytest.fail("Pending reviews must prevent baseline refresh"))
    manifest["seed_version"] = "pending-review-code-upgrade-v2"

    response = helper.bootstrap_workspace()

    assert response["status"] == "baseline_sync_skipped_pending_review"
    workspace_manifest = helper._workspace_manifest_or_empty()
    assert workspace_manifest["workspace_status"] == "ready"
    assert workspace_manifest["workspace_seed_version"] == manifest["seed_version"]
    assert workspace_manifest["baseline_status"] == helper.BASELINE_STATUS_SYNC_SKIPPED_PENDING_REVIEW
    for name in ("site_order.py", "report.py"):
        assert (snapshot / name).read_bytes() == (source_snapshot / "scraper" / name).read_bytes()
    assert not obsolete.exists()
    assert [dict(row) for row in helper._record_rows(batch_id=batch_id)] == records_before
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == files_before
    assert helper._workspace_sitemap_cache_path().read_bytes() == checkpoint_before
    assert "keep-receipt" in receipt.read_text()
    helper._write_apply_outputs(tmp_path / "upgraded-output", [original])
    assert original["title"] in (tmp_path / "upgraded-output" / helper.REPO_PORTFOLIO).read_text()


def test_offline_seed_upgrade_preserves_published_baseline_but_explicit_reset_clears_it(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    manifest, seed = _install_older_seed_fixture(helper, tmp_path, monkeypatch)
    batch_id = helper._create_batch("manual")
    _review_fixture(helper, batch_id)
    published_sha = helper.apply_accepted_records(batch_id)["applied_commit_sha"]
    published_files = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    baseline_time = helper._workspace_manifest_or_empty()["baseline_updated_at"]
    checkpoint = {"https://eventstructure.com/imported-work": "2026-09-07"}
    helper._write_json_atomic(helper._workspace_sitemap_cache_path(), checkpoint)
    receipt = helper._publication_root(999) / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"prepared"}', encoding="utf-8")
    manifest["seed_version"] = "upgrade-offline-v2"
    monkeypatch.setattr(helper, "_clone_remote_baseline_repo", lambda: (_ for _ in ()).throw(RuntimeError("Offline fixture")))

    response = helper.bootstrap_workspace()

    assert response["status"] == "baseline_cached_fallback"
    assert response["settings"]["baseline_status"] == helper.BASELINE_STATUS_CACHED_FALLBACK
    assert response["settings"]["baseline_commit"] == published_sha
    assert response["settings"]["baseline_updated_at"] == baseline_time
    assert response["settings"]["baseline_error"] == "Offline fixture"
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == published_files
    assert helper._load_workspace_sitemap_cache() == checkpoint
    assert receipt.exists()

    pending_batch = helper._create_batch("manual")
    _review_fixture(helper, pending_batch)
    reset = helper.reset_workspace()
    assert reset["status"] == "reset_seed_fallback"
    assert reset["settings"]["baseline_commit"] == ""
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == {
        name: (seed / name).read_bytes() for name in helper.TARGET_FILES
    }
    assert helper._load_workspace_sitemap_cache() == {}
    assert not receipt.exists()
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0


def _matching_import_result(baseline):
    result = _import_result(baseline["url"])
    result["proposed"] = dict(baseline, source="new-extractor-label")
    return result


def test_incremental_unchanged_effective_fields_are_checkpointed_without_review(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    baseline = helper._load_workspace_works()[0]
    url = baseline["url"]
    before = {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES}
    sitemap = {url: "2026-09-07"}
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, sitemap))
    result = _matching_import_result(baseline)
    # Empty extraction values preserve richer baseline fields in the actual merge.
    result["proposed"]["materials"] = ""
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: result)

    response = helper.start_incremental_sync()

    assert response["urls_processed"] == response["unchanged_count"] == 1
    detail = helper.get_batch_detail(response["batch_id"])
    assert detail["records"] == []
    assert detail["batch"]["status"] == helper.BATCH_COMPLETED
    assert detail["batch"]["total_records"] == 0
    assert helper._load_workspace_sitemap_cache()[url] == "2026-09-07"
    assert {name: (helper.workspace_root() / name).read_bytes() for name in helper.TARGET_FILES} == before
    assert helper.start_incremental_sync()["urls_processed"] == 0


def test_incremental_mixed_results_checkpoint_only_successful_noops(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    original = helper._load_workspace_works()[0]
    names = ["unchanged", "changed", "unapproved", "failed"]
    baselines = {name: dict(original, title=name, url=f"https://eventstructure.com/{name}") for name in names}
    helper._write_workspace_works(list(baselines.values()))
    sitemap = {work["url"]: "2026-09-07" for work in baselines.values()}
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, sitemap))

    def import_result(url, modules):
        name = url.rsplit("/", 1)[-1]
        if name == "failed":
            raise RuntimeError("Could not fetch artwork")
        result = _matching_import_result(baselines[name])
        if name == "changed":
            result["proposed"]["materials"] = "paper"
        if name == "unapproved":
            result["should_apply"] = False
            result["rejection_reason"] = "Requires manual review"
        return result

    monkeypatch.setattr(helper, "_import_url", import_result)

    response = helper.start_incremental_sync()

    assert response["urls_processed"] == 4
    assert response["unchanged_count"] == 1
    detail = helper.get_batch_detail(response["batch_id"])
    assert detail["batch"]["total_records"] == 3
    assert {record["url"].rsplit("/", 1)[-1]: record["status"] for record in detail["records"]} == {
        "changed": helper.RECORD_READY_FOR_REVIEW, "unapproved": helper.RECORD_NEEDS_REVIEW, "failed": helper.RECORD_FAILED,
    }
    cache = helper._load_workspace_sitemap_cache()
    assert cache[baselines["unchanged"]["url"]] == "2026-09-07"
    assert all(baselines[name]["url"] not in cache for name in ["changed", "unapproved", "failed"])


@pytest.mark.parametrize("operation", ["manual", "retry"])
def test_explicit_imports_keep_unchanged_artwork_available_for_review(tmp_path, monkeypatch, operation):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    baseline = helper._load_workspace_works()[0]
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: {})
    monkeypatch.setattr(helper, "_import_url", lambda url, modules: _matching_import_result(baseline))
    if operation == "manual":
        response = helper.submit_manual_url(baseline["url"])
        record = helper.get_batch_detail(response["batch_id"])["records"][0]
    else:
        batch_id = helper._create_batch("manual")
        record_id = _review_fixture(helper, batch_id, url=baseline["url"], status=helper.RECORD_FAILED)
        helper.retry_record(record_id)
        record = helper.get_batch_detail(batch_id)["records"][0]
        assert record["id"] == record_id
    assert record["status"] == helper.RECORD_READY_FOR_REVIEW
    assert record["url"] == baseline["url"]


def test_fatal_validation_is_never_suppressed_as_an_unchanged_artwork(tmp_path, monkeypatch):
    helper, _remote, _source = _transaction_fixture(tmp_path, monkeypatch)
    baseline = helper._load_workspace_works()[0]
    sitemap = {baseline["url"]: "2026-09-07", "https://eventstructure.com/not-started": "2026-09-07"}
    monkeypatch.setattr(helper, "_load_snapshot_modules", lambda: _fake_incremental_modules(helper, sitemap))
    seen = []

    def fatal_result(url, modules):
        seen.append(url)
        result = _matching_import_result(baseline)
        result["ai_error_state"] = helper.OPENAI_AUTHENTICATION_FAILED
        return result

    monkeypatch.setattr(helper, "_import_url", fatal_result)

    with pytest.raises(helper.OpenAIServiceError, match="OPENAI_AUTHENTICATION_FAILED"):
        helper.start_incremental_sync()

    assert seen == [baseline["url"]]
    rows = helper._record_rows()
    assert len(rows) == 1
    assert rows[0]["status"] == helper.RECORD_FAILED
    assert helper.get_batch_detail(rows[0]["batch_id"])["batch"]["total_records"] == 1
    assert baseline["url"] not in helper._load_workspace_sitemap_cache()
