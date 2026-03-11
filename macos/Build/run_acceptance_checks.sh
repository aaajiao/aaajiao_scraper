#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
HELPER_BIN="${APP_BUNDLE}/Contents/MacOS/AaajiaoHelper"

if [[ ! -x "${HELPER_BIN}" ]]; then
  echo "Bundled helper bridge not found at ${HELPER_BIN}" >&2
  echo "Build the app first with ./macos/Build/build_local_app.sh" >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/aaajiao_acceptance.XXXXXX")"
WORKSPACE_ROOT="${TMP_ROOT}/workspace"
BOOTSTRAP_JSON="${TMP_ROOT}/bootstrap.json"
LIST_JSON="${TMP_ROOT}/list.json"
ACCEPT_JSON="${TMP_ROOT}/accept.json"
PREVIEW_JSON="${TMP_ROOT}/preview.json"
DRY_RUN_JSON="${TMP_ROOT}/dry-run.json"
RESET_JSON="${TMP_ROOT}/reset.json"

cleanup() {
  rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" bootstrapWorkspace > "${BOOTSTRAP_JSON}"

export WORKSPACE_ROOT
/usr/bin/python3 - <<'PY'
import json
import os
import sqlite3
from pathlib import Path

workspace_root = Path(os.environ["WORKSPACE_ROOT"])
db_path = workspace_root / "jobs.sqlite"
now = "2026-03-11T00:00:00+00:00"
record = {
    "title": "Codex Fixture Work",
    "title_cn": "Codex Fixture Work",
    "year": "2026",
    "type": "installation",
    "materials": "steel, text",
    "size": "100 x 100 cm",
    "duration": "",
    "credits": "",
    "description_en": "Fixture record used for importer acceptance checks.",
    "description_cn": "",
    "url": "https://eventstructure.com/codex-fixture-work",
    "images": [],
    "source": "acceptance_fixture",
}

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(
    """
    INSERT INTO batches(mode, status, created_at, updated_at, total_records, last_error)
    VALUES(?, ?, ?, ?, ?, ?)
    """,
    ("manual", "reviewing", now, now, 1, ""),
)
batch_id = cur.lastrowid
cur.execute(
    """
    INSERT INTO records(
      batch_id, url, slug, status, page_type, confidence, is_update,
      proposed_record_json, error_message, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        batch_id,
        record["url"],
        "codex-fixture-work",
        "ready_for_review",
        "artwork",
        0.99,
        0,
        json.dumps(record, ensure_ascii=False),
        "",
        now,
        now,
    ),
)
conn.commit()
conn.close()
PY

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" listPendingRecords > "${LIST_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" acceptRecord --id 1 > "${ACCEPT_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" getApplyPreview --batch-id 1 > "${PREVIEW_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" applyAcceptedRecords --batch-id 1 --dry-run > "${DRY_RUN_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" resetWorkspace > "${RESET_JSON}"

export BOOTSTRAP_JSON LIST_JSON ACCEPT_JSON PREVIEW_JSON DRY_RUN_JSON RESET_JSON WORKSPACE_ROOT
/usr/bin/python3 - <<'PY'
import json
import os
from pathlib import Path

bootstrap = json.loads(Path(os.environ["BOOTSTRAP_JSON"]).read_text(encoding="utf-8"))
listing = json.loads(Path(os.environ["LIST_JSON"]).read_text(encoding="utf-8"))
accepted = json.loads(Path(os.environ["ACCEPT_JSON"]).read_text(encoding="utf-8"))
preview = json.loads(Path(os.environ["PREVIEW_JSON"]).read_text(encoding="utf-8"))
dry_run = json.loads(Path(os.environ["DRY_RUN_JSON"]).read_text(encoding="utf-8"))
reset_result = json.loads(Path(os.environ["RESET_JSON"]).read_text(encoding="utf-8"))
workspace_root = Path(os.environ["WORKSPACE_ROOT"])

assert bootstrap["status"] in {"initialized", "ready"}
assert bootstrap["settings"]["openai_model"] == "gpt-4.1", bootstrap
assert bootstrap["settings"]["openai_model_source"] == "default", bootstrap
assert len(listing["pending_records"]) == 1, listing
assert listing["pending_records"][0]["title"] == "Codex Fixture Work", listing
assert accepted["status"] == "accepted", accepted
assert preview["accepted_count"] == 1, preview
assert preview["new_count"] == 1, preview
assert preview["updated_count"] == 0, preview
assert preview["will_push"] in {True, False}, preview
if not preview["will_push"]:
    assert preview["error_message"] == "Repository worktree is not clean", preview
assert dry_run["dry_run"] is True, dry_run
assert (workspace_root / "aaajiao_works.json").exists()
assert (workspace_root / "aaajiao_portfolio.md").exists()
assert reset_result["status"] in {"initialized", "ready"}, reset_result
workspace_manifest = json.loads((workspace_root / "workspace_manifest.json").read_text(encoding="utf-8"))
assert workspace_manifest["workspace_status"] in {"ready", "seed_version_mismatch"}, workspace_manifest
PY

echo "Acceptance checks passed"
