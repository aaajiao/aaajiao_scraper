#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="Aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
APP_CONTENTS="${APP_BUNDLE}/Contents"
APP_RESOURCES="${APP_CONTENTS}/Resources"
APP_MACOS="${APP_CONTENTS}/MacOS"
BUILD_DIR="${REPO_ROOT}/build/macos"
XCODE_PYTHON_ROOT="/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9"
XCODE_PYTHON_BIN="${XCODE_PYTHON_ROOT}/bin/python3.9"

mkdir -p "${REPO_ROOT}/dist"
rm -rf "${BUILD_DIR}" "${APP_BUNDLE}"
mkdir -p "${BUILD_DIR}" "${APP_RESOURCES}" "${APP_MACOS}"

echo "Preparing seed and vendor snapshots..."
rm -rf "${MACOS_DIR}/Vendor/python_snapshot" "${MACOS_DIR}/Seed/cache"
mkdir -p "${MACOS_DIR}/Vendor/python_snapshot" "${MACOS_DIR}/Seed"
cp -R "${REPO_ROOT}/scraper" "${MACOS_DIR}/Vendor/python_snapshot/"
cp -R "${REPO_ROOT}/.cache" "${MACOS_DIR}/Seed/cache"
cp "${REPO_ROOT}/aaajiao_works.json" "${MACOS_DIR}/Seed/aaajiao_works.json"
cp "${REPO_ROOT}/aaajiao_portfolio.md" "${MACOS_DIR}/Seed/aaajiao_portfolio.md"

echo "Preparing bundled Python runtime..."
rm -rf "${MACOS_DIR}/Vendor/python_runtime"
if [[ -x "${XCODE_PYTHON_BIN}" ]]; then
  cp -R "${XCODE_PYTHON_ROOT}" "${MACOS_DIR}/Vendor/python_runtime"
  ln -sf python3.9 "${MACOS_DIR}/Vendor/python_runtime/bin/python3"
else
  echo "Missing Xcode bundled Python at ${XCODE_PYTHON_BIN}" >&2
  exit 1
fi

echo "Installing vendored Python dependencies..."
"${XCODE_PYTHON_BIN}" -m pip install \
  --disable-pip-version-check \
  --upgrade \
  --target "${MACOS_DIR}/Vendor/python_runtime/lib/python3.9/site-packages" \
  requests beautifulsoup4 python-dotenv pydantic "urllib3<2"

echo "Copying app resources..."
cp "${MACOS_DIR}/App/Info.plist" "${APP_CONTENTS}/Info.plist"
cp -R "${MACOS_DIR}/Helper" "${APP_RESOURCES}/engine"
cp -R "${MACOS_DIR}/Vendor/python_snapshot" "${APP_RESOURCES}/python_snapshot"
cp -R "${MACOS_DIR}/Vendor/python_runtime" "${APP_RESOURCES}/python_runtime"
cp -R "${MACOS_DIR}/Seed" "${APP_RESOURCES}/Seed"

echo "Compiling menu bar app..."
SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
SWIFT_FILES=("${MACOS_DIR}"/App/*.swift "${MACOS_DIR}"/Shared/*.swift)
xcrun swiftc \
  -parse-as-library \
  -target arm64-apple-macos13.0 \
  -sdk "${SDK_PATH}" \
  -framework SwiftUI \
  -framework AppKit \
  -framework Security \
  "${SWIFT_FILES[@]}" \
  -o "${APP_MACOS}/AaajiaoImporter"

echo "Ad-hoc signing app bundle..."
codesign --force --deep --sign - "${APP_BUNDLE}"

echo "Built ${APP_BUNDLE}"
