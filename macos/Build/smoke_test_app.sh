#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="Aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
APP_RESOURCES="${APP_BUNDLE}/Contents/Resources"
APP_BINARY="${APP_BUNDLE}/Contents/MacOS/AaajiaoImporter"
HELPER_BIN="${APP_BUNDLE}/Contents/MacOS/AaajiaoHelper"
INFO_PLIST="${APP_BUNDLE}/Contents/Info.plist"
ICON_FILE="${APP_RESOURCES}/jiaozip.icns"

if [[ ! -x "${HELPER_BIN}" ]]; then
  echo "Bundled helper bridge not found at ${HELPER_BIN}" >&2
  exit 1
fi

if [[ ! -x "${APP_BINARY}" ]]; then
  echo "App binary not found at ${APP_BINARY}" >&2
  exit 1
fi

if [[ ! -f "${ICON_FILE}" ]]; then
  echo "Bundled icon not found at ${ICON_FILE}" >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/aaajiao_importer_smoke.XXXXXX")"
WORKSPACE_ROOT="${TMP_ROOT}/workspace"
BOOTSTRAP_JSON="${TMP_ROOT}/bootstrap.json"
OVERVIEW_JSON="${TMP_ROOT}/overview.json"

cleanup() {
  rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

echo "Running helper smoke tests..."
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" bootstrapWorkspace > "${BOOTSTRAP_JSON}"

AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${HELPER_BIN}" overview > "${OVERVIEW_JSON}"

export BOOTSTRAP_JSON OVERVIEW_JSON WORKSPACE_ROOT INFO_PLIST APP_BINARY
/usr/bin/python3 - <<'PY'
import json
import os
import plistlib
from pathlib import Path

bootstrap = json.loads(Path(os.environ["BOOTSTRAP_JSON"]).read_text(encoding="utf-8"))
overview = json.loads(Path(os.environ["OVERVIEW_JSON"]).read_text(encoding="utf-8"))
workspace_root = Path(os.environ["WORKSPACE_ROOT"])
workspace_manifest = json.loads((workspace_root / "workspace_manifest.json").read_text(encoding="utf-8"))
info_plist = plistlib.loads(Path(os.environ["INFO_PLIST"]).read_bytes())
binary_data = Path(os.environ["APP_BINARY"]).read_bytes()

assert bootstrap["status"] in {"initialized", "ready"}, bootstrap
assert overview["settings"]["workspace_path"] == str(workspace_root), overview
assert workspace_manifest["workspace_status"] in {"ready", "seed_version_mismatch"}, workspace_manifest
assert (workspace_root / "aaajiao_works.json").exists()
assert (workspace_root / "aaajiao_portfolio.md").exists()
assert info_plist["CFBundleIconFile"] == "jiaozip", info_plist
assert b"Settings" in binary_data, "Settings entry missing from app binary"
assert b"Quit Aaajiao Importer" in binary_data, "Quit entry missing from app binary"
PY

echo "Smoke test passed"
