#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="Aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
HELPER_BIN="${APP_BUNDLE}/Contents/MacOS/AaajiaoHelper"

if [[ ! -x "${HELPER_BIN}" ]]; then
  echo "Bundled helper bridge not found at ${HELPER_BIN}" >&2
  echo "Build the app first with ./macos/Build/build_local_app.sh" >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/aaajiao_git_txn.XXXXXX")"
TEST_REPO="${TMP_ROOT}/repo"
REMOTE_REPO="${TMP_ROOT}/remote.git"
WORKSPACE_ROOT="${TMP_ROOT}/workspace"
APPLY_JSON="${TMP_ROOT}/apply.json"
PREVIEW_JSON="${TMP_ROOT}/preview.json"

cleanup() {
  rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

echo "Preparing temporary git sandbox..."
git clone --quiet "${REPO_ROOT}" "${TEST_REPO}"
git init --bare --quiet "${REMOTE_REPO}"
BRANCH_NAME="$(git -C "${TEST_REPO}" branch --show-current)"
git -C "${TEST_REPO}" remote remove origin >/dev/null 2>&1 || true
git -C "${TEST_REPO}" remote add origin "${REMOTE_REPO}"
git -C "${TEST_REPO}" push --quiet -u origin "HEAD:refs/heads/${BRANCH_NAME}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
"${HELPER_BIN}" bootstrapWorkspace >/dev/null

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
    "title": "Codex Transaction Fixture",
    "title_cn": "",
    "year": "2026",
    "type": "installation",
    "materials": "steel, text",
    "size": "100 x 100 cm",
    "duration": "",
    "credits": "",
    "description_en": "Fixture record used for git transaction acceptance checks.",
    "description_cn": "",
    "url": "https://eventstructure.com/codex-transaction-fixture",
    "images": [],
    "source": "git_transaction_fixture",
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
        "codex-transaction-fixture",
        "accepted",
        "artwork",
        0.99,
        0,
        json.dumps(record, ensure_ascii=False),
        "",
        now,
        now,
    ),
)
cur.execute(
    "UPDATE batches SET status = ?, total_records = ?, updated_at = ? WHERE id = ?",
    ("ready_to_apply", 1, now, batch_id),
)
conn.commit()
conn.close()
PY

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
"${HELPER_BIN}" getApplyPreview --batch-id 1 > "${PREVIEW_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
"${HELPER_BIN}" applyAcceptedRecords --batch-id 1 > "${APPLY_JSON}"

export TEST_REPO REMOTE_REPO BRANCH_NAME PREVIEW_JSON APPLY_JSON
/usr/bin/python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path

test_repo = Path(os.environ["TEST_REPO"])
remote_repo = Path(os.environ["REMOTE_REPO"])
branch_name = os.environ["BRANCH_NAME"]
preview = json.loads(Path(os.environ["PREVIEW_JSON"]).read_text(encoding="utf-8"))
apply_result = json.loads(Path(os.environ["APPLY_JSON"]).read_text(encoding="utf-8"))

assert preview["accepted_count"] == 1, preview
assert preview["will_push"] is True, preview
assert apply_result["dry_run"] is False, apply_result

head = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=test_repo,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
remote_head = subprocess.run(
    ["git", f"--git-dir={remote_repo}", "rev-parse", f"refs/heads/{branch_name}"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
assert head == remote_head == apply_result["applied_commit_sha"], (head, remote_head, apply_result)

last_commit_files = subprocess.run(
    ["git", "show", "--name-only", "--format=", "HEAD"],
    cwd=test_repo,
    capture_output=True,
    text=True,
    check=True,
).stdout.splitlines()
last_commit_files = [line for line in last_commit_files if line.strip()]
assert sorted(last_commit_files) == ["aaajiao_portfolio.md", "aaajiao_works.json"], last_commit_files

status = subprocess.run(
    ["git", "status", "--short"],
    cwd=test_repo,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
assert status == "", status
PY

echo "Git transaction checks passed"
