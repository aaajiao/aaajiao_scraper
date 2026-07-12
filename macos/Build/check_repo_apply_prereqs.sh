#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_REPO_ROOT="$(cd "${MACOS_DIR}/.." && pwd)"

# aaajiao_importer.py's repo_root() resolves the same way (AAAJIAO_REPO_ROOT override,
# else a fixed default), so honor the same override here to preflight the repo the
# helper will actually publish from -- e.g. a sandboxed checkout in the test scripts.
REPO_ROOT="${AAAJIAO_REPO_ROOT:-${DEFAULT_REPO_ROOT}}"

cd "${REPO_ROOT}"

echo "Repo preflight for live apply..."

# Mirrors _repo_publish_config() in macos/Helper/aaajiao_importer.py: apply pushes
# straight to origin from a managed clone under the workspace and never reads or
# writes this worktree, so a dirty worktree does not block it (see
# tests/test_macos_helper.py's dirty-source-repo apply coverage). What actually
# gates a real apply is: HEAD resolves to a real branch, that branch has an
# upstream, the upstream's branch matches the configured baseline branch, and the
# remote it points at is reachable.
export GIT_TERMINAL_PROMPT=0

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [[ -z "${branch}" ]]; then
  echo "FAIL: repository is in detached HEAD state" >&2
  exit 1
fi

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
if [[ -z "${upstream}" || "${upstream}" != */* ]]; then
  echo "FAIL: current branch '${branch}' has no upstream configured" >&2
  exit 1
fi

remote_name="${upstream%%/*}"
remote_branch="${upstream#*/}"
expected_branch="${AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH:-main}"

if [[ "${branch}" != "${expected_branch}" || "${remote_branch}" != "${expected_branch}" ]]; then
  echo "FAIL: current branch '${branch}' (tracking '${upstream}') does not match the baseline branch '${expected_branch}'; switch to '${expected_branch}' before syncing" >&2
  exit 1
fi

remote_url="$(git remote get-url "${remote_name}" 2>/dev/null || true)"
if [[ -z "${remote_url}" ]]; then
  echo "FAIL: remote '${remote_name}' has no configured URL" >&2
  exit 1
fi

echo "Checking that '${remote_name}' (${remote_url}) is reachable..."
# ls-remote crosses the network: the http knobs abort a stalled HTTPS transfer,
# ConnectTimeout bounds SSH connection setup, and coreutils timeout (when
# installed) is a hard backstop so the preflight always returns.
ls_remote=(git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=15
  ls-remote --exit-code "${remote_url}" "refs/heads/${remote_branch}")
if command -v timeout >/dev/null 2>&1; then
  ls_remote=(timeout 30 "${ls_remote[@]}")
elif command -v gtimeout >/dev/null 2>&1; then
  ls_remote=(gtimeout 30 "${ls_remote[@]}")
fi
if ! GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o ConnectTimeout=15" \
    "${ls_remote[@]}" >/dev/null 2>&1; then
  echo "FAIL: remote '${remote_name}' is unreachable, has no '${remote_branch}' branch, or did not respond within the timeout" >&2
  exit 1
fi

echo "OK"
echo "branch=${branch}"
echo "upstream=${upstream}"
echo "remote_url=${remote_url}"
