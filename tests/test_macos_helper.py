import importlib.util
import json
import subprocess
from pathlib import Path

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
