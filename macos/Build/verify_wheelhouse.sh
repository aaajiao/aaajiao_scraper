#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WHEELHOUSE_DIR="${MACOS_DIR}/Vendor/wheelhouse"
REQUIREMENTS_FILE="${SCRIPT_DIR}/wheelhouse_requirements.txt"

XCODE_PYTHON_ROOT="/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9"
XCODE_PYTHON_BIN="${XCODE_PYTHON_ROOT}/bin/python3.9"

if [[ ! -x "${XCODE_PYTHON_BIN}" ]]; then
  echo "Missing Xcode bundled Python at ${XCODE_PYTHON_BIN}" >&2
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
"${XCODE_PYTHON_BIN}" -m pip install \
  --disable-pip-version-check \
  --no-index \
  --find-links "${WHEELHOUSE_DIR}" \
  --target "${TMP_TARGET}" \
  -r "${REQUIREMENTS_FILE}"

echo "Wheelhouse verified"
