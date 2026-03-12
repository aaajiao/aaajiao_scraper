import importlib.util
import json
import subprocess
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
