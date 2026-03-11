import importlib.util
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
    monkeypatch.setenv("AAAJIAO_IMPORTER_REPO_ROOT", str(Path(__file__).resolve().parents[1]))

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
