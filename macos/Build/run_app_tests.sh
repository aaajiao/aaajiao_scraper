#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUILD_DIR="${MACOS_DIR}/.build/app-tests"
TEST_BINARY="${BUILD_DIR}/AaajiaoAppTests"
MODULE_CACHE="${BUILD_DIR}/module-cache"

mkdir -p "${BUILD_DIR}" "${MODULE_CACHE}"

SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
SOURCE_FILES=(
  "${MACOS_DIR}/App/AppUtilities.swift"
  "${MACOS_DIR}/App/HelperClient.swift"
  "${MACOS_DIR}/App/OpenAIModelSettings.swift"
  "${MACOS_DIR}/Shared/ImporterDTOs.swift"
  "${MACOS_DIR}/AppTests"/*.swift
)

echo "Compiling app unit tests..."
xcrun swiftc \
  -target arm64-apple-macos13.0 \
  -sdk "${SDK_PATH}" \
  -module-cache-path "${MODULE_CACHE}" \
  "${SOURCE_FILES[@]}" \
  -o "${TEST_BINARY}"

echo "Running app unit tests..."
"${TEST_BINARY}"
