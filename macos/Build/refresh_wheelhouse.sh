#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"
BUILD_PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${BUILD_PYTHON}" ]]; then
  echo "Prepare the repository .venv before refreshing the wheelhouse." >&2
  exit 1
fi
WHEELHOUSE_DIR="${MACOS_DIR}/Vendor/wheelhouse"
REQUIREMENTS_FILE="${SCRIPT_DIR}/wheelhouse_requirements.txt"

"${BUILD_PYTHON}" "${SCRIPT_DIR}/prepare_python_runtime.py"
RUNTIME_PYTHON="${MACOS_DIR}/Vendor/python_runtime/bin/python3"
unset PYTHONHOME PYTHONPATH PYTHONEXECUTABLE PYTHONUSERBASE __PYVENV_LAUNCHER__
export PYTHONNOUSERSITE=1
DOWNLOAD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aaajiao_wheels.XXXXXX")"
trap 'rm -rf "${DOWNLOAD_DIR}"' EXIT

echo "Downloading wheelhouse from locked requirements..."
# This pinned core predates upstream cp315 wheels. Build from verified official
# source using the standalone interpreter; never copy an installed .venv binary.
CORE_SOURCE="$("${BUILD_PYTHON}" -c 'import json,sys; s=json.load(open(sys.argv[1]))["pydantic-core"]; print(s["url"] + "#sha256=" + s["sha256"])' "${SCRIPT_DIR}/native_wheel_sources.json")"
EXPECTED_RUST="$("${BUILD_PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["pydantic-core"]["rust_version"])' "${SCRIPT_DIR}/native_wheel_sources.json")"
RUST_TOOLCHAIN="$("${BUILD_PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["pydantic-core"]["rust_toolchain"])' "${SCRIPT_DIR}/native_wheel_sources.json")"
RUSTUP_BIN="$(command -v rustup || true)"
if [[ -z "${RUSTUP_BIN}" ]]; then
  echo "Install rustup and toolchain ${RUST_TOOLCHAIN} before refreshing native wheels; no default-toolchain change is required." >&2
  exit 1
fi
RUSTC_BIN="$("${RUSTUP_BIN}" which --toolchain "${RUST_TOOLCHAIN}" rustc)"
CARGO_BIN="$("${RUSTUP_BIN}" which --toolchain "${RUST_TOOLCHAIN}" cargo)"
ACTUAL_RUST="$("${RUSTC_BIN}" --version | awk '{print $2}')"
if [[ "${ACTUAL_RUST}" != "${EXPECTED_RUST}" ]]; then
  echo "Native wheel refresh requires Rust ${EXPECTED_RUST}; found ${ACTUAL_RUST}. Existing committed wheels remain usable for offline app builds." >&2
  exit 1
fi
# Rust panic locations and macro expansions can retain paths even without debug
# info. Remap every local input; official std libraries avoid Homebrew build paths.
ENCODED_RUSTFLAGS="$("${BUILD_PYTHON}" - "${REPO_ROOT}" "${RUSTC_BIN:h:h}" <<'PY'
import os
import sys
import tempfile
from pathlib import Path

prefixes = [
    ("/Users", "/build/users"),
    ("/opt/homebrew", "/build/homebrew"),
    ("/private/var/folders", "/build/tmp"),
    ("/var/folders", "/build/tmp"),
    (str(Path.home()), "/build/home"),
    (os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")), "/build/cargo"),
    (str(Path(tempfile.gettempdir()).resolve()), "/build/tmp"),
    (str(Path(sys.argv[1]).resolve()), "/build/source"),
    (str(Path(sys.argv[2]).resolve()), "/build/rust-toolchain"),
]
flags = [f"--remap-path-prefix={source}={destination}" for source, destination in prefixes]
flags.extend(["-C", "debuginfo=0", "-C", "strip=symbols", "-C", "link-arg=-Wl,-S"])
print("\x1f".join(flags))
PY
)"
PATH="${CARGO_BIN:h}:${PATH}" RUSTC="${RUSTC_BIN}" \
CARGO_ENCODED_RUSTFLAGS="${ENCODED_RUSTFLAGS}" \
CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_PROFILE_RELEASE_STRIP=symbols \
MATURIN_STRIP=true \
MACOSX_DEPLOYMENT_TARGET=11.0 "${RUNTIME_PYTHON}" -I -m pip wheel \
  --disable-pip-version-check \
  --no-cache-dir \
  --no-deps \
  --build-constraint "${SCRIPT_DIR}/native_build_constraints.txt" \
  --config-settings=maturin.build-args=--strip \
  --wheel-dir "${DOWNLOAD_DIR}" \
  "${CORE_SOURCE}"
"${BUILD_PYTHON}" "${SCRIPT_DIR}/normalize_native_wheel_metadata.py" "${DOWNLOAD_DIR}"
"${RUNTIME_PYTHON}" -I -m pip download \
  --disable-pip-version-check \
  --only-binary=:all: \
  --find-links "${DOWNLOAD_DIR}" \
  --dest "${DOWNLOAD_DIR}" \
  -r "${REQUIREMENTS_FILE}"

mkdir -p "${MACOS_DIR}/.build/native-wheel-builds"
cp "${DOWNLOAD_DIR}"/pydantic_core-*.whl "${MACOS_DIR}/.build/native-wheel-builds/"
"${BUILD_PYTHON}" "${SCRIPT_DIR}/verify_wheel_paths.py" "${DOWNLOAD_DIR}"

# Replace only after every pinned wheel has downloaded successfully.
mkdir -p "${WHEELHOUSE_DIR}"
rm -f "${WHEELHOUSE_DIR}"/*.whl
cp "${DOWNLOAD_DIR}"/*.whl "${WHEELHOUSE_DIR}/"

"${SCRIPT_DIR}/verify_wheelhouse.sh"

echo "Wheelhouse refreshed at ${WHEELHOUSE_DIR}"
