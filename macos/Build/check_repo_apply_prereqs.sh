#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "Repo preflight for live apply..."

if [[ -n "$(git status --porcelain)" ]]; then
  echo "FAIL: worktree is not clean" >&2
  exit 1
fi

branch="$(git symbolic-ref --quiet --short HEAD)"
if [[ -z "${branch}" ]]; then
  echo "FAIL: detached HEAD" >&2
  exit 1
fi

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u})"
if [[ -z "${upstream}" ]]; then
  echo "FAIL: missing upstream" >&2
  exit 1
fi

echo "OK"
echo "branch=${branch}"
echo "upstream=${upstream}"
