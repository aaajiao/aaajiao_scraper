#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"
BUILD_PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${BUILD_PYTHON}" ]]; then
  echo "Prepare the repository .venv before building the app." >&2
  exit 1
fi

SEED_DIR="${MACOS_DIR}/Seed"
VENDOR_DIR="${MACOS_DIR}/Vendor"
PYTHON_SNAPSHOT_DIR="${VENDOR_DIR}/python_snapshot"
PYTHON_RUNTIME_DIR="${VENDOR_DIR}/python_runtime"
WHEELHOUSE_DIR="${VENDOR_DIR}/wheelhouse"
SEED_MANIFEST_PATH="${SEED_DIR}/seed_manifest.json"
REQUIREMENTS_FILE="${SCRIPT_DIR}/wheelhouse_requirements.txt"

RUNTIME_MANIFEST_PATH="${SCRIPT_DIR}/python_runtime_manifest.json"
runtime_mode="standalone_wheelhouse"

echo "Preparing seed payload..."
rm -rf "${PYTHON_SNAPSHOT_DIR}" "${SEED_DIR}/cache"
mkdir -p "${PYTHON_SNAPSHOT_DIR}" "${SEED_DIR}"
cp -R "${REPO_ROOT}/portfolio_scraper/scraper" "${PYTHON_SNAPSHOT_DIR}/"
if [[ -d "${REPO_ROOT}/.cache" ]]; then
  cp -R "${REPO_ROOT}/.cache" "${SEED_DIR}/cache"
else
  # .cache/ is gitignored (portfolio_scraper's scraper cache), so a fresh clone or a
  # CI checkout won't have one yet. Seed an empty cache instead of failing the build;
  # aaajiao_importer.py's ensure_workspace() already tolerates a missing seed cache.
  echo "No ${REPO_ROOT}/.cache found; seeding an empty cache directory instead." >&2
  mkdir -p "${SEED_DIR}/cache"
fi
cp "${REPO_ROOT}/aaajiao_works.json" "${SEED_DIR}/aaajiao_works.json"
cp "${REPO_ROOT}/aaajiao_portfolio.md" "${SEED_DIR}/aaajiao_portfolio.md"

wheel_files=("${WHEELHOUSE_DIR}"/*.whl)
if [[ "${#wheel_files[@]}" -gt 0 ]]; then
  "${BUILD_PYTHON}" "${SCRIPT_DIR}/prepare_python_runtime.py"
  RUNTIME_PYTHON="${PYTHON_RUNTIME_DIR}/bin/python3"
  unset PYTHONHOME PYTHONPATH PYTHONEXECUTABLE PYTHONUSERBASE __PYVENV_LAUNCHER__
  export PYTHONNOUSERSITE=1
  SITE_PACKAGES="$("${RUNTIME_PYTHON}" -I -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
  if [[ "${SITE_PACKAGES}" != "${PYTHON_RUNTIME_DIR}/"* ]]; then
    echo "Refusing to install dependencies outside the bundled runtime: ${SITE_PACKAGES}" >&2
    exit 1
  fi
  echo "Installing the pinned standalone runtime dependencies from the offline wheelhouse..."
  "${RUNTIME_PYTHON}" -I -m pip install \
    --disable-pip-version-check \
    --no-index \
    --find-links "${WHEELHOUSE_DIR}" \
    --upgrade \
    --only-binary=:all: \
    --no-compile \
    --target "${SITE_PACKAGES}" \
    -r "${REQUIREMENTS_FILE}"
  # pip --target creates unused CLI entry points with absolute build-directory
  # shebangs. The app only imports these packages; do not ship those launchers.
  rm -rf "${SITE_PACKAGES}/bin"
else
  echo "No wheelhouse found in ${WHEELHOUSE_DIR}. Run ./macos/Build/refresh_wheelhouse.sh first." >&2
  exit 1
fi

echo "Writing seed manifest..."
export REPO_ROOT SEED_DIR PYTHON_SNAPSHOT_DIR PYTHON_RUNTIME_DIR WHEELHOUSE_DIR SEED_MANIFEST_PATH REQUIREMENTS_FILE RUNTIME_MANIFEST_PATH runtime_mode
"${BUILD_PYTHON}" - <<'PY'
import hashlib
import json
import os
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_info(path: Path) -> dict:
    return {
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def count_files(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file())


repo_root = Path(os.environ["REPO_ROOT"])
seed_dir = Path(os.environ["SEED_DIR"])
snapshot_dir = Path(os.environ["PYTHON_SNAPSHOT_DIR"]) / "scraper"
runtime_dir = Path(os.environ["PYTHON_RUNTIME_DIR"])
wheelhouse_dir = Path(os.environ["WHEELHOUSE_DIR"])
manifest_path = Path(os.environ["SEED_MANIFEST_PATH"])
requirements_file = Path(os.environ["REQUIREMENTS_FILE"])
runtime_mode = os.environ["runtime_mode"]
runtime_manifest = json.loads(Path(os.environ["RUNTIME_MANIFEST_PATH"]).read_text())

try:
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
except Exception:
    source_commit = "unknown"

source_state = "clean"
try:
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        source_state = "dirty"
except Exception:
    source_state = "unknown"

generated_at = subprocess.run(
    ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()

works_path = seed_dir / "aaajiao_works.json"
portfolio_path = seed_dir / "aaajiao_portfolio.md"
seed_version = f"{source_commit}:{sha256(works_path)[:12]}:{sha256(portfolio_path)[:12]}"
if source_state == "dirty":
    seed_version = f"{seed_version}-dirty"

manifest = {
    "manifest_version": 1,
    "generated_at": generated_at,
    "source_commit": source_commit,
    "source_state": source_state,
    "seed_version": seed_version,
    "files": {
        "aaajiao_works.json": file_info(works_path),
        "aaajiao_portfolio.md": file_info(portfolio_path),
    },
    "snapshot": {
        "scraper_files": count_files(snapshot_dir),
        "cache_files": count_files(seed_dir / "cache"),
    },
    "python_runtime": {
        **runtime_manifest,
        "mode": runtime_mode,
        "wheel_count": len(list(wheelhouse_dir.glob("*.whl"))),
        "python_exists": (runtime_dir / runtime_manifest["executable"]).exists(),
        "requirements_sha256": sha256(requirements_file),
        "wheel_sha256": {path.name: sha256(path) for path in sorted(wheelhouse_dir.glob("*.whl"))},
        "native_sources": json.loads((requirements_file.parent / "native_wheel_sources.json").read_text()),
        "native_build_constraints_sha256": sha256(requirements_file.parent / "native_build_constraints.txt"),
    },
}

manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Prepared seed manifest at ${SEED_MANIFEST_PATH}"
