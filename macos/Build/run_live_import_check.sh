#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
HELPER_BIN="${APP_BUNDLE}/Contents/MacOS/AaajiaoHelper"
TARGET_URL="${1:-https://eventstructure.com/Guard-I}"

if [[ ! -x "${HELPER_BIN}" ]]; then
  echo "Bundled helper bridge not found at ${HELPER_BIN}" >&2
  echo "Build the app first with ./macos/Build/build_local_app.sh" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for live AI validation." >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/aaajiao_live_import.XXXXXX")"
WORKSPACE_ROOT="${TMP_ROOT}/workspace"
SUBMIT_JSON="${TMP_ROOT}/submit.json"
OVERVIEW_JSON="${TMP_ROOT}/overview.json"

cleanup() {
  rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

echo "Running live import check for ${TARGET_URL}..."
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
OPENAI_API_KEY="${OPENAI_API_KEY}" \
"${HELPER_BIN}" submitManualURL --url "${TARGET_URL}" > "${SUBMIT_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
OPENAI_API_KEY="${OPENAI_API_KEY}" \
"${HELPER_BIN}" listPendingRecords > "${OVERVIEW_JSON}"

export SUBMIT_JSON OVERVIEW_JSON TARGET_URL
/usr/bin/python3 - <<'PY'
import json
import os
from pathlib import Path

submit = json.loads(Path(os.environ["SUBMIT_JSON"]).read_text(encoding="utf-8"))
overview = json.loads(Path(os.environ["OVERVIEW_JSON"]).read_text(encoding="utf-8"))
target_url = os.environ["TARGET_URL"]

assert submit["url"] == target_url, submit
pending = overview["pending_records"]
assert pending, overview
record = pending[0]
print(json.dumps({
    "url": record["url"],
    "status": record["status"],
    "page_type": record["page_type"],
    "confidence": record["confidence"],
    "title": record["title"],
    "error_message": record["error_message"],
}, ensure_ascii=False, indent=2))
PY
