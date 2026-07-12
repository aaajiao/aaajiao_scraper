# aaajiao Importer for macOS

This directory contains the local-only macOS importer app and its bundled Python engine.

The repository now has two parallel product surfaces:

- `portfolio_scraper/` for the Python scraper product line
- `macos/` for the importer app

The importer publishes the same two shared artifacts the rest of the repo uses:

- `aaajiao_works.json`
- `aaajiao_portfolio.md`

At build time, `prepare_seed.sh` copies:

- `portfolio_scraper/scraper/` into the bundled Python snapshot
- `.cache/` into the seed cache, or seeds an empty cache directory if `.cache/` doesn't
  exist yet (it's gitignored, so a fresh clone has none to copy)
- root `aaajiao_works.json`
- root `aaajiao_portfolio.md`

At runtime the app initializes a workspace under
`~/Library/Application Support/AaajiaoImporter/workspace` and performs all processing there.
Applying accepted changes does **not** write into this repository checkout. The helper
instead clones this checkout's configured `origin` remote into a managed temporary clone
under the workspace, commits the updated `aaajiao_works.json` / `aaajiao_portfolio.md`
there, and pushes straight to `origin/<baseline branch>` (`main` by default, override with
`AAAJIAO_IMPORTER_BASELINE_REMOTE_BRANCH`). Before pushing it verifies that this checkout's
current branch and its upstream both resolve to the baseline branch and that the remote is
reachable; apply fails with a clear error instead of silently publishing to the wrong
branch otherwise. Because the push never touches this working tree, run `git pull` here
afterward to see the new commit locally.

## Current flow

1. Bootstrap a dedicated workspace from bundled seed data, then refresh the data baseline from GitHub.
2. Run incremental sync or submit a manual artwork URL.
3. Review `ready_for_review` and `needs_review` records in the menu bar app.
4. Preview the apply transaction, then explicitly confirm the push to `origin/<baseline
   branch>` (pull locally afterward to pick up the new commit in this checkout).

## Validation model

AI validation is split into two stages:

1. OpenAI returns a strict structured record schema for `artwork / exhibition / unknown`.
2. The local helper re-validates slug/title consistency, type-as-title mistakes, contamination signals, and required-field completeness before a record can reach `ready_for_review`.

The app exposes `gpt-4.1` and `gpt-5.4-mini` as built-in model presets, with `gpt-4.1`
remaining the default. A custom model name can still be entered in Settings. Existing local
preferences saved with the retired `gpt-5.1` preset are migrated to `gpt-5.4-mini` when loaded.

The app version is read from the bundle `Info.plist` and shown in both Settings and the menu
bar menu, so release builds should bump `CFBundleShortVersionString` and `CFBundleVersion`
before packaging.

## Command surface

- `bootstrapWorkspace`
- `resetWorkspace`
- `refreshWorkspaceBaseline`
- `startIncrementalSync`
- `submitManualURL`
- `listPendingRecords`
- `acceptRecord`
- `rejectRecord`
- `getApplyPreview`
- `applyAcceptedRecords`

## Build scripts

```bash
./macos/Build/refresh_wheelhouse.sh
./macos/Build/verify_wheelhouse.sh
./macos/Build/prepare_seed.sh
./macos/Build/run_app_tests.sh
./macos/Build/build_local_app.sh
./macos/Build/smoke_test_app.sh
./macos/Build/run_acceptance_checks.sh
./macos/Build/run_git_transaction_checks.sh
./macos/Build/run_live_import_check.sh
./macos/Build/check_repo_apply_prereqs.sh
./macos/Build/release_preflight.sh
```

`release_preflight.sh` chains the scripts above (offline dependencies, app tests, build,
acceptance checks, git transaction checks, optional live check, final repo preflight) in
the order `RELEASE_CHECKLIST.md` documents, so a release can be preflighted with one
command instead of running each step by hand. It runs `run_live_import_check.sh` only when
`OPENAI_API_KEY` is set (pass `--skip-live` to silence the reminder otherwise). It adds no
validation of its own -- the handful of checklist steps it can't automate (freezing inputs,
eyeballing the seed manifest and `.app` bundle, a final `git status`) still need a human pass.

Release checklist:

```bash
open macos/Build/RELEASE_CHECKLIST.md
```

`prepare_seed.sh` regenerates `macos/Seed/seed_manifest.json` on every run (timestamp, HEAD
commit, dirty-state). It's a build artifact, not a source file: `macos/.gitignore` excludes
it so a `prepare_seed.sh`/`build_local_app.sh` run never leaves it as an uncommitted diff.
Treat its `source_commit` field as "what this seed snapshot was built from," not as a
version-controlled record to keep in sync.
At runtime the helper writes `workspace_manifest.json` into the local workspace and validates
the bundled seed version before reusing the workspace. The manifest also records the latest
GitHub baseline status, commit, and fallback error details for the workspace data files.

`wheelhouse_requirements.txt` is the pinned runtime dependency lock for the bundled Python
environment. `refresh_wheelhouse.sh` downloads wheels into `macos/Vendor/wheelhouse/`, and
`verify_wheelhouse.sh` proves that the wheelhouse can satisfy an offline install.

Build locally with:

```bash
./macos/Build/build_local_app.sh
```

The resulting app bundle is written to `dist/aaajiao Importer.app`.
