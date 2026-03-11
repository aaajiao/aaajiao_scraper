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

mkdir -p "${WHEELHOUSE_DIR}"
rm -f "${WHEELHOUSE_DIR}"/*.whl

echo "Downloading wheelhouse from locked requirements..."
"${XCODE_PYTHON_BIN}" -m pip download \
  --disable-pip-version-check \
  --only-binary=:all: \
  --dest "${WHEELHOUSE_DIR}" \
  -r "${REQUIREMENTS_FILE}"

"${SCRIPT_DIR}/verify_wheelhouse.sh"

echo "Wheelhouse refreshed at ${WHEELHOUSE_DIR}"
