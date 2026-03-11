#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="Aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
APP_RESOURCES="${APP_BUNDLE}/Contents/Resources"
PYTHON_BIN="${APP_RESOURCES}/python_runtime/bin/python3"
HELPER_SCRIPT="${APP_RESOURCES}/engine/aaajiao_importer.py"
SITE_PACKAGES="${APP_RESOURCES}/python_runtime/lib/python3.9/site-packages"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Bundled Python runtime not found at ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ ! -f "${HELPER_SCRIPT}" ]]; then
  echo "Bundled helper script not found at ${HELPER_SCRIPT}" >&2
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
PYTHONNOUSERSITE=1 \
PYTHONPATH="${SITE_PACKAGES}" \
AAAJIAO_IMPORTER_BUNDLE_ROOT="${APP_RESOURCES}" \
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${PYTHON_BIN}" "${HELPER_SCRIPT}" bootstrapWorkspace > "${BOOTSTRAP_JSON}"

PYTHONNOUSERSITE=1 \
PYTHONPATH="${SITE_PACKAGES}" \
AAAJIAO_IMPORTER_BUNDLE_ROOT="${APP_RESOURCES}" \
AAAJIAO_IMPORTER_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
AAAJIAO_REPO_ROOT="${REPO_ROOT}" \
"${PYTHON_BIN}" "${HELPER_SCRIPT}" overview > "${OVERVIEW_JSON}"

export BOOTSTRAP_JSON OVERVIEW_JSON WORKSPACE_ROOT
/usr/bin/python3 - <<'PY'
import json
import os
from pathlib import Path

bootstrap = json.loads(Path(os.environ["BOOTSTRAP_JSON"]).read_text(encoding="utf-8"))
overview = json.loads(Path(os.environ["OVERVIEW_JSON"]).read_text(encoding="utf-8"))
workspace_root = Path(os.environ["WORKSPACE_ROOT"])
workspace_manifest = json.loads((workspace_root / "workspace_manifest.json").read_text(encoding="utf-8"))

assert bootstrap["status"] in {"initialized", "ready"}, bootstrap
assert overview["settings"]["workspace_path"] == str(workspace_root), overview
assert workspace_manifest["workspace_status"] in {"ready", "seed_version_mismatch"}, workspace_manifest
assert (workspace_root / "aaajiao_works.json").exists()
assert (workspace_root / "aaajiao_portfolio.md").exists()
PY

echo "Smoke test passed"
