# macOS Importer Release Checklist

Use this checklist before shipping a new local build of `aaajiao Importer.app`.

For a one-shot run, `./macos/Build/release_preflight.sh` chains the scripts from sections
2-6 below in order (set `OPENAI_API_KEY` beforehand to also include section 5's live-key
path, or pass `--skip-live` to silence the reminder). It is a convenience wrapper around
those same scripts, not a replacement for the checklist itself: section 1's freeze-inputs
step and section 6's file-eyeballing steps (`.app` not staged, `seed_manifest.json`'s
`source_commit`, `python_runtime.mode`, final `git status`) still need a human pass.

## 1. Freeze inputs

- Confirm the repo worktree is clean before producing the final seed manifest.
- Confirm `portfolio_scraper/scraper/` contains the intended Python snapshot for the release build.
- Confirm `aaajiao_works.json` and `aaajiao_portfolio.md` are the intended seed baseline.
- Confirm `macos/Vendor/wheelhouse/` matches `macos/Build/wheelhouse_requirements.txt`.

## 2. Refresh offline dependencies

```bash
./macos/Build/refresh_wheelhouse.sh
./macos/Build/verify_wheelhouse.sh
```

Expected result:

- All pinned wheels are present in `macos/Vendor/wheelhouse/`
- Offline install verification passes

## 3. Build the app bundle

Run app-side unit tests before packaging:

```bash
./macos/Build/run_app_tests.sh
```

Expected result:

- Model preset selection and migration checks pass
- App DTO decoding and pure app utility checks pass

```bash
./macos/Build/build_local_app.sh
```

Expected result:

- `macos/Seed/seed_manifest.json` is regenerated
- `dist/aaajiao Importer.app` is rebuilt and ad-hoc signed
- `smoke_test_app.sh` passes automatically

## 4. Run acceptance checks

```bash
./macos/Build/run_acceptance_checks.sh
./macos/Build/run_git_transaction_checks.sh
```

Expected result:

- Review queue fixture is visible
- `acceptRecord` works
- `getApplyPreview` works
- `applyAcceptedRecords --dry-run` regenerates workspace files
- `resetWorkspace` recreates the workspace and refreshes the GitHub baseline, or reports a clear seed fallback
- `applyAcceptedRecords` commits and pushes to `origin/<baseline branch>` from a managed
  temporary clone (it never writes to the sandbox checkout itself)
- `applyAcceptedRecords` is rejected with a clear error when the sandbox checkout's
  current branch/upstream doesn't match the baseline branch
- `applyAcceptedRecords` marks the batch failed (with the remote's rejection reason
  recorded) when the push itself is rejected, instead of losing the failure silently

## 5. Optional live validation

Run one real import in a temporary workspace. `OPENAI_API_KEY` is optional on this script:
without it, the helper still fetches the URL for real and takes its AI-unavailable
fallback path.

```bash
./macos/Build/run_live_import_check.sh                 # no-key path
OPENAI_API_KEY=... ./macos/Build/run_live_import_check.sh  # live AI validation path
```

Expected result:

- Without `OPENAI_API_KEY`, the record lands in `needs_review` with an "AI unavailable:
  missing OPENAI_API_KEY" error message
- With `OPENAI_API_KEY`, the record should either reach `ready_for_review` or return a clear local rejection reason

## 6. Final release sanity checks

- Confirm `.app` bundle is not staged for git
- Run `./macos/Build/check_repo_apply_prereqs.sh` (checks branch/upstream/remote
  reachability for the eventual push, not worktree cleanliness -- a real apply publishes
  through a managed clone and never reads or writes this worktree)
- Confirm the freshly regenerated `macos/Seed/seed_manifest.json` shows the intended
  `source_commit`; it's a gitignored build artifact rebuilt by `prepare_seed.sh` on every
  run, so there is nothing to `git add` for it
- Confirm `python_runtime.mode` is `wheelhouse` for the final release build
- Confirm the repo is clean after the final commit
