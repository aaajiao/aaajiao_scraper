import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from requests import Response

HELPER_PATH = Path(__file__).resolve().parents[1] / "macos" / "Helper" / "aaajiao_importer.py"


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

    response = helper.apply_accepted_records(batch_id)

    assert response["batch_id"] == batch_id
    assert response["applied_commit_sha"] == "abc123"
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (batch_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0] == 0


def test_prune_terminal_batches_removes_completed_and_failed_only(tmp_path, monkeypatch):
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

    assert pruned == 2
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (active_batch,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (completed_batch,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (failed_batch,)).fetchone()[0] == 0
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
    assert "Published Work" in published_json


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

    helper.apply_accepted_records(batch_id)

    cache = json.loads(sitemap_path.read_text(encoding="utf-8"))
    # The unresolved record's URL is freed so the next sync can rediscover it...
    assert pending_url not in cache
    # ...while the applied record stays cached (already persisted to the baseline).
    assert accepted_url in cache
    with helper.connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0] == 0


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
    assert row["status"] not in {helper.BATCH_FAILED, helper.BATCH_COMPLETED}
    assert record_count == 1


def test_apply_accepted_records_marks_batch_failed_with_real_stderr_on_push_rejection_and_allows_retry(
    tmp_path, monkeypatch
):
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
    assert "Failed to publish workspace changes to GitHub" in error_message
    # The real git stderr must reach the user, not a bare "exit status 1".
    assert "rejected" in error_message.lower() or "fetch first" in error_message.lower()

    with helper.connect_db() as conn:
        row = conn.execute("SELECT status, last_error FROM batches WHERE id = ?", (batch_id,)).fetchone()
        record_count = conn.execute("SELECT COUNT(*) FROM records WHERE batch_id = ?", (batch_id,)).fetchone()[0]

    assert row["status"] == helper.BATCH_FAILED
    # last_error carries the same real stderr, not a generic CalledProcessError string.
    assert row["last_error"] == error_message
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
