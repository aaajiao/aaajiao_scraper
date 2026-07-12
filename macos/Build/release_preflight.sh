#!/bin/zsh
set -euo pipefail
setopt null_glob

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Strings together the existing release scripts in the order documented by
# macos/Build/RELEASE_CHECKLIST.md, so a release can be preflighted with one command
# instead of relying on someone following the checklist by hand and possibly skipping
# or reordering a step. This script adds no validation logic of its own -- each step
# below is one of the checklist's existing scripts.

RUN_LIVE_IMPORT_CHECK=0
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  RUN_LIVE_IMPORT_CHECK=1
fi

for arg in "$@"; do
  case "${arg}" in
    --skip-live)
      RUN_LIVE_IMPORT_CHECK=0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Usage: $0 [--skip-live]" >&2
      exit 1
      ;;
  esac
done

run_step() {
  echo ""
  echo "==> $*"
  "$@"
}

# 1. Freeze inputs is a manual checklist step (confirm the intended scraper/
#    aaajiao_works.json/aaajiao_portfolio.md state before building) -- nothing to run.

# 2. Refresh offline dependencies
run_step "${SCRIPT_DIR}/refresh_wheelhouse.sh"
run_step "${SCRIPT_DIR}/verify_wheelhouse.sh"

# 3. Build the app bundle (build_local_app.sh runs prepare_seed.sh and
#    smoke_test_app.sh itself)
run_step "${SCRIPT_DIR}/run_app_tests.sh"
run_step "${SCRIPT_DIR}/build_local_app.sh"

# 4. Run acceptance checks
run_step "${SCRIPT_DIR}/run_acceptance_checks.sh"
run_step "${SCRIPT_DIR}/run_git_transaction_checks.sh"

# 5. Optional live validation (needs a real OPENAI_API_KEY and network access)
if [[ "${RUN_LIVE_IMPORT_CHECK}" -eq 1 ]]; then
  run_step "${SCRIPT_DIR}/run_live_import_check.sh"
else
  echo ""
  echo "==> Skipping run_live_import_check.sh (set OPENAI_API_KEY to include it, or pass --skip-live to silence this)"
fi

# 6. Final release sanity checks
run_step "${SCRIPT_DIR}/check_repo_apply_prereqs.sh"

echo ""
echo "Release preflight passed."
echo "Remaining manual checklist steps (see macos/Build/RELEASE_CHECKLIST.md):"
echo "  - Confirm the .app bundle is not staged for git"
echo "  - Confirm macos/Seed/seed_manifest.json shows the intended source_commit"
echo "  - Confirm python_runtime.mode is wheelhouse for the final release build"
echo "  - Confirm the repo is clean after the final commit"
