#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${MACOS_DIR}/.build/ui-preview"
APP_BUNDLE="${BUILD_DIR}/Importer Preview.app"
APP_CONTENTS="${APP_BUNDLE}/Contents"
MODULE_CACHE="${BUILD_DIR}/module-cache"

mkdir -p "${APP_CONTENTS}/MacOS" "${APP_CONTENTS}/Resources" "${MODULE_CACHE}"
cp "${MACOS_DIR}/AppPreviews/Info.plist" "${APP_CONTENTS}/Info.plist"
cp "${MACOS_DIR}/AppPreviews/fixtures.json" "${APP_CONTENTS}/Resources/fixtures.json"
cp "${MACOS_DIR}/jiaozip.icns" "${APP_CONTENTS}/Resources/jiaozip.icns"

SOURCE_FILES=()
for source in "${MACOS_DIR}"/App/*.swift; do
  case "${source:t}" in
    main.swift|ApplicationLifecycle.swift) ;;
    *) SOURCE_FILES+=("${source}") ;;
  esac
done
SOURCE_FILES+=("${MACOS_DIR}"/Shared/*.swift "${MACOS_DIR}"/AppPreviews/*.swift)

SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
echo "Compiling the in-memory UI preview..."
xcrun swiftc \
  -parse-as-library \
  -target arm64-apple-macos13.0 \
  -sdk "${SDK_PATH}" \
  -module-cache-path "${MODULE_CACHE}" \
  -framework SwiftUI \
  -framework AppKit \
  -framework Security \
  "${SOURCE_FILES[@]}" \
  -o "${APP_CONTENTS}/MacOS/ImporterPreview"

xattr -cr "${APP_BUNDLE}"
codesign --force --deep --sign - "${APP_BUNDLE}"
codesign --verify --deep --strict "${APP_BUNDLE}"
echo "Built ${APP_BUNDLE}"
echo "The preview was not launched. Its helper and settings only change in memory."
