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
INITIAL_HEAD="$(git -C "${TEST_REPO}" rev-parse HEAD)"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL="${REMOTE_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH="${BRANCH_NAME}" \
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
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL="${REMOTE_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH="${BRANCH_NAME}" \
"${HELPER_BIN}" getApplyPreview --batch-id 1 > "${PREVIEW_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL="${REMOTE_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH="${BRANCH_NAME}" \
"${HELPER_BIN}" applyAcceptedRecords --batch-id 1 > "${APPLY_JSON}"

export TEST_REPO REMOTE_REPO BRANCH_NAME PREVIEW_JSON APPLY_JSON INITIAL_HEAD
/usr/bin/python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path

test_repo = Path(os.environ["TEST_REPO"])
remote_repo = Path(os.environ["REMOTE_REPO"])
branch_name = os.environ["BRANCH_NAME"]
initial_head = os.environ["INITIAL_HEAD"]
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
assert head == initial_head, (head, initial_head, apply_result)
assert remote_head == apply_result["applied_commit_sha"], (remote_head, apply_result)

last_commit_files = subprocess.run(
    ["git", f"--git-dir={remote_repo}", "show", "--name-only", "--format=", remote_head],
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

echo "Verified the successful apply transaction"

echo ""
echo "Testing branch mismatch rejection..."
git -C "${TEST_REPO}" checkout --quiet -b other-branch
git -C "${TEST_REPO}" push --quiet -u origin other-branch

export WORKSPACE_ROOT
BRANCH_MISMATCH_URL="https://eventstructure.com/codex-branch-mismatch-fixture"
export BRANCH_MISMATCH_URL
/usr/bin/python3 - <<'PY'
import json
import os
import sqlite3
from pathlib import Path

workspace_root = Path(os.environ["WORKSPACE_ROOT"])
db_path = workspace_root / "jobs.sqlite"
now = "2026-03-11T00:00:00+00:00"
record = {
    "title": "Codex Branch Mismatch Fixture",
    "title_cn": "",
    "year": "2026",
    "type": "installation",
    "materials": "steel, text",
    "size": "100 x 100 cm",
    "duration": "",
    "credits": "",
    "description_en": "Fixture record used to exercise the branch-mismatch apply rejection.",
    "description_cn": "",
    "url": os.environ["BRANCH_MISMATCH_URL"],
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
        "codex-branch-mismatch-fixture",
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

BRANCH_MISMATCH_ERR="${TMP_ROOT}/branch_mismatch.err"
set +e
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL="${REMOTE_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH="${BRANCH_NAME}" \
"${HELPER_BIN}" applyAcceptedRecords --batch-id 2 > "${TMP_ROOT}/branch_mismatch.json" 2> "${BRANCH_MISMATCH_ERR}"
BRANCH_MISMATCH_EXIT=$?
set -e

if [[ "${BRANCH_MISMATCH_EXIT}" -eq 0 ]]; then
  echo "FAIL: applyAcceptedRecords should have rejected a branch mismatch" >&2
  cat "${BRANCH_MISMATCH_ERR}" >&2
  exit 1
fi
if ! grep -q "does not match the baseline branch" "${BRANCH_MISMATCH_ERR}"; then
  echo "FAIL: branch mismatch error did not mention the baseline branch requirement" >&2
  cat "${BRANCH_MISMATCH_ERR}" >&2
  exit 1
fi
echo "Branch mismatch correctly rejected: $(cat "${BRANCH_MISMATCH_ERR}")"

git -C "${TEST_REPO}" checkout --quiet "${BRANCH_NAME}"

echo ""
echo "Testing push rejection and failure bookkeeping..."
HOOK_PATH="${REMOTE_REPO}/hooks/pre-receive"
cat > "${HOOK_PATH}" <<'HOOK'
#!/bin/sh
echo "remote rejected: simulated push failure for git transaction checks" >&2
exit 1
HOOK
chmod +x "${HOOK_PATH}"

PUSH_FAILURE_URL="https://eventstructure.com/codex-push-failure-fixture"
export PUSH_FAILURE_URL
/usr/bin/python3 - <<'PY'
import json
import os
import sqlite3
from pathlib import Path

workspace_root = Path(os.environ["WORKSPACE_ROOT"])
db_path = workspace_root / "jobs.sqlite"
now = "2026-03-11T00:00:00+00:00"
record = {
    "title": "Codex Push Failure Fixture",
    "title_cn": "",
    "year": "2026",
    "type": "installation",
    "materials": "steel, text",
    "size": "100 x 100 cm",
    "duration": "",
    "credits": "",
    "description_en": "Fixture record used to exercise the push-rejected apply failure path.",
    "description_cn": "",
    "url": os.environ["PUSH_FAILURE_URL"],
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
        "codex-push-failure-fixture",
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

PUSH_FAILURE_ERR="${TMP_ROOT}/push_failure.err"
set +e
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL="${REMOTE_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH="${BRANCH_NAME}" \
"${HELPER_BIN}" applyAcceptedRecords --batch-id 3 > "${TMP_ROOT}/push_failure.json" 2> "${PUSH_FAILURE_ERR}"
PUSH_FAILURE_EXIT=$?
set -e

if [[ "${PUSH_FAILURE_EXIT}" -eq 0 ]]; then
  echo "FAIL: applyAcceptedRecords should have failed when the remote rejects the push" >&2
  cat "${PUSH_FAILURE_ERR}" >&2
  exit 1
fi
if ! grep -q "simulated push failure" "${PUSH_FAILURE_ERR}"; then
  echo "FAIL: push failure error did not surface the remote's rejection reason" >&2
  cat "${PUSH_FAILURE_ERR}" >&2
  exit 1
fi

export TEST_REPO INITIAL_HEAD WORKSPACE_ROOT
/usr/bin/python3 - <<'PY'
import os
import sqlite3
import subprocess
from pathlib import Path

test_repo = Path(os.environ["TEST_REPO"])
initial_head = os.environ["INITIAL_HEAD"]
workspace_root = Path(os.environ["WORKSPACE_ROOT"])

# The rejected push must not have touched the source worktree: apply only ever
# writes through a managed clone under the workspace, never repo_root() itself.
head = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=test_repo, capture_output=True, text=True, check=True
).stdout.strip()
assert head == initial_head, (head, initial_head)
status = subprocess.run(
    ["git", "status", "--short"], cwd=test_repo, capture_output=True, text=True, check=True
).stdout.strip()
assert status == "", status

conn = sqlite3.connect(workspace_root / "jobs.sqlite")
row = conn.execute("SELECT status, last_error FROM batches WHERE id = 3").fetchone()
conn.close()
assert row is not None, "push-failure batch went missing"
assert row[0] == "failed", row
assert row[1], "expected a non-empty last_error after a rejected push"
print(f"batch 3 status={row[0]!r} last_error={row[1]!r}")
PY

echo "Push failure correctly recorded as a failed batch with a retryable state"

echo ""
echo "Retrying the same batch after the remote stops rejecting pushes..."
rm -f "${HOOK_PATH}"

RETRY_JSON="${TMP_ROOT}/push_retry.json"
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${TEST_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_URL="${REMOTE_REPO}" \
AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH="${BRANCH_NAME}" \
"${HELPER_BIN}" applyAcceptedRecords --batch-id 3 > "${RETRY_JSON}"

export RETRY_JSON WORKSPACE_ROOT REMOTE_REPO BRANCH_NAME
/usr/bin/python3 - <<'PY'
import json
import os
import sqlite3
import subprocess
from pathlib import Path

retry_result = json.loads(Path(os.environ["RETRY_JSON"]).read_text(encoding="utf-8"))
workspace_root = Path(os.environ["WORKSPACE_ROOT"])
remote_repo = Path(os.environ["REMOTE_REPO"])
branch_name = os.environ["BRANCH_NAME"]

assert retry_result["dry_run"] is False, retry_result
assert retry_result["applied_commit_sha"], retry_result

remote_head = subprocess.run(
    ["git", f"--git-dir={remote_repo}", "rev-parse", f"refs/heads/{branch_name}"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
assert remote_head == retry_result["applied_commit_sha"], (remote_head, retry_result)

conn = sqlite3.connect(workspace_root / "jobs.sqlite")
row = conn.execute("SELECT status, last_error FROM batches WHERE id = 3").fetchone()
conn.close()
# A successful apply calls cleanup_batch(), which deletes the batch row outright
# (same as the happy-path batch 1 above) rather than leaving a "completed" row behind.
assert row is None, row
print(f"retry succeeded: batch 3 cleaned up after apply, applied_commit_sha={retry_result['applied_commit_sha']!r}")
PY

echo "Git transaction checks passed"
