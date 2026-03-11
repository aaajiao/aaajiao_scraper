#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

SEED_DIR="${MACOS_DIR}/Seed"
VENDOR_DIR="${MACOS_DIR}/Vendor"
PYTHON_SNAPSHOT_DIR="${VENDOR_DIR}/python_snapshot"
PYTHON_RUNTIME_DIR="${VENDOR_DIR}/python_runtime"
WHEELHOUSE_DIR="${VENDOR_DIR}/wheelhouse"
SEED_MANIFEST_PATH="${SEED_DIR}/seed_manifest.json"

XCODE_PYTHON_ROOT="/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9"
XCODE_PYTHON_BIN="${XCODE_PYTHON_ROOT}/bin/python3.9"

DEPENDENCIES=(
  requests
  beautifulsoup4
  python-dotenv
  pydantic
  "urllib3<2"
)

runtime_mode="prebuilt_runtime"

echo "Preparing seed payload..."
rm -rf "${PYTHON_SNAPSHOT_DIR}" "${SEED_DIR}/cache"
mkdir -p "${PYTHON_SNAPSHOT_DIR}" "${SEED_DIR}"
cp -R "${REPO_ROOT}/scraper" "${PYTHON_SNAPSHOT_DIR}/"
cp -R "${REPO_ROOT}/.cache" "${SEED_DIR}/cache"
cp "${REPO_ROOT}/aaajiao_works.json" "${SEED_DIR}/aaajiao_works.json"
cp "${REPO_ROOT}/aaajiao_portfolio.md" "${SEED_DIR}/aaajiao_portfolio.md"

wheel_files=("${WHEELHOUSE_DIR}"/*.whl)
if [[ "${#wheel_files[@]}" -gt 0 ]]; then
  if [[ ! -x "${XCODE_PYTHON_BIN}" ]]; then
    echo "Missing Xcode bundled Python at ${XCODE_PYTHON_BIN}" >&2
    exit 1
  fi
  echo "Preparing bundled Python runtime from wheelhouse..."
  rm -rf "${PYTHON_RUNTIME_DIR}"
  cp -R "${XCODE_PYTHON_ROOT}" "${PYTHON_RUNTIME_DIR}"
  ln -sf python3.9 "${PYTHON_RUNTIME_DIR}/bin/python3"
  "${XCODE_PYTHON_BIN}" -m pip install \
    --disable-pip-version-check \
    --no-index \
    --find-links "${WHEELHOUSE_DIR}" \
    --upgrade \
    --target "${PYTHON_RUNTIME_DIR}/lib/python3.9/site-packages" \
    "${DEPENDENCIES[@]}"
  runtime_mode="wheelhouse"
elif [[ -x "${PYTHON_RUNTIME_DIR}/bin/python3.9" ]]; then
  echo "Reusing existing vendored Python runtime..."
else
  echo "No wheelhouse found in ${WHEELHOUSE_DIR} and no prebuilt runtime available." >&2
  echo "Populate macos/Vendor/wheelhouse or prepare macos/Vendor/python_runtime first." >&2
  exit 1
fi

echo "Writing seed manifest..."
export REPO_ROOT SEED_DIR PYTHON_SNAPSHOT_DIR PYTHON_RUNTIME_DIR WHEELHOUSE_DIR SEED_MANIFEST_PATH runtime_mode
/usr/bin/python3 - <<'PY'
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
runtime_mode = os.environ["runtime_mode"]

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
        "mode": runtime_mode,
        "wheel_count": len(list(wheelhouse_dir.glob("*.whl"))),
        "python_exists": (runtime_dir / "bin" / "python3.9").exists(),
    },
}

manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Prepared seed manifest at ${SEED_MANIFEST_PATH}"
