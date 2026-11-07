#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_PYTHON="${MACOS_DIR}/../.venv/bin/python"
WHEELHOUSE_DIR="${MACOS_DIR}/Vendor/wheelhouse"
REQUIREMENTS_FILE="${SCRIPT_DIR}/wheelhouse_requirements.txt"

RUNTIME_PYTHON="${MACOS_DIR}/Vendor/python_runtime/bin/python3"

if [[ ! -x "${RUNTIME_PYTHON}" ]]; then
  echo "Missing standalone Python; run refresh_wheelhouse.sh or prepare_python_runtime.py first." >&2
  exit 1
fi

wheel_files=("${WHEELHOUSE_DIR}"/*.whl)
if [[ "${#wheel_files[@]}" -eq 0 ]]; then
  echo "No wheels found in ${WHEELHOUSE_DIR}" >&2
  exit 1
fi

TMP_TARGET="$(mktemp -d "${TMPDIR:-/tmp}/aaajiao_wheelhouse_verify.XXXXXX")"
cleanup() {
  rm -rf "${TMP_TARGET}"
}
trap cleanup EXIT

echo "Verifying wheelhouse..."
"${BUILD_PYTHON}" "${SCRIPT_DIR}/verify_wheel_paths.py" "${WHEELHOUSE_DIR}"
unset PYTHONHOME PYTHONPATH PYTHONEXECUTABLE PYTHONUSERBASE __PYVENV_LAUNCHER__
export PYTHONNOUSERSITE=1
"${RUNTIME_PYTHON}" -I -m pip install \
  --disable-pip-version-check \
  --no-index \
  --find-links "${WHEELHOUSE_DIR}" \
  --only-binary=:all: \
  --no-compile \
  --target "${TMP_TARGET}" \
  -r "${REQUIREMENTS_FILE}"

"${RUNTIME_PYTHON}" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import requests, bs4, pydantic, pydantic_core; print("Verified dependency imports on", sys.version.split()[0])' "${TMP_TARGET}"

echo "Wheelhouse verified"
