#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

APP_NAME="aaajiao Importer"
APP_BUNDLE="${REPO_ROOT}/dist/${APP_NAME}.app"
APP_CONTENTS="${APP_BUNDLE}/Contents"
APP_RESOURCES="${APP_CONTENTS}/Resources"
APP_MACOS="${APP_CONTENTS}/MacOS"
BUILD_DIR="${MACOS_DIR}/.build/macos"

RUN_PREPARE=1
RUN_SMOKE=1

for arg in "$@"; do
  case "${arg}" in
    --skip-prepare)
      RUN_PREPARE=0
      ;;
    --skip-smoke)
      RUN_SMOKE=0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 1
      ;;
  esac
done

if [[ "${RUN_PREPARE}" -eq 1 ]]; then
  "${SCRIPT_DIR}/prepare_seed.sh"
fi

mkdir -p "${REPO_ROOT}/dist"
rm -rf "${BUILD_DIR}" "${APP_BUNDLE}"
mkdir -p "${BUILD_DIR}" "${APP_RESOURCES}" "${APP_MACOS}"

echo "Copying app resources..."
cp "${MACOS_DIR}/App/Info.plist" "${APP_CONTENTS}/Info.plist"
cp "${MACOS_DIR}/jiaozip.icns" "${APP_RESOURCES}/jiaozip.icns"
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

echo "Compiling local helper bridge..."
xcrun swiftc \
  -parse-as-library \
  -target arm64-apple-macos13.0 \
  -sdk "${SDK_PATH}" \
  "${MACOS_DIR}/HelperBridge/AaajiaoHelper.swift" \
  -o "${APP_MACOS}/AaajiaoHelper"

echo "Clearing extended attributes from app bundle..."
xattr -cr "${APP_BUNDLE}"

echo "Ad-hoc signing app bundle..."
codesign --force --deep --sign - "${APP_BUNDLE}"

if [[ "${RUN_SMOKE}" -eq 1 ]]; then
  "${SCRIPT_DIR}/smoke_test_app.sh"
fi

echo "Built ${APP_BUNDLE}"
