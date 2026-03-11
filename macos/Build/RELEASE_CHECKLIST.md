# macOS Importer Release Checklist

Use this checklist before shipping a new local build of `Aaajiao Importer.app`.

## 1. Freeze inputs

- Confirm the repo worktree is clean before producing the final seed manifest.
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

```bash
./macos/Build/build_local_app.sh
```

Expected result:

- `macos/Seed/seed_manifest.json` is regenerated
- `dist/Aaajiao Importer.app` is rebuilt and ad-hoc signed
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
- `resetWorkspace` recreates the workspace from bundled seed
- `applyAcceptedRecords` can commit and push in a temporary git sandbox

## 5. Optional live validation

Run one real import in a temporary workspace:

```bash
OPENAI_API_KEY=... ./macos/Build/run_live_import_check.sh
```

Expected result:

- Without `OPENAI_API_KEY`, the record lands in `needs_review`
- With `OPENAI_API_KEY`, the record should either reach `ready_for_review` or return a clear local rejection reason

## 6. Final release sanity checks

- Confirm `.app` bundle is not staged for git
- Run `./macos/Build/check_repo_apply_prereqs.sh`
- Confirm `seed_manifest.json` shows the intended `source_commit`
- Confirm `python_runtime.mode` is `wheelhouse` for the final release build
- Confirm the repo is clean after the final commit
