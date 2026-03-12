# aaajiao Importer for macOS

This directory contains the local-only macOS importer app and its bundled Python engine.

The repository now has two parallel product surfaces:

- `portfolio_scraper/` for the Python scraper product line
- `macos/` for the importer app

The importer still treats the repository root as the publish target for shared artifacts:

- `aaajiao_works.json`
- `aaajiao_portfolio.md`

At build time, `prepare_seed.sh` copies:

- `portfolio_scraper/scraper/` into the bundled Python snapshot
- `.cache/` into the seed cache
- root `aaajiao_works.json`
- root `aaajiao_portfolio.md`

At runtime the app initializes a workspace under
`~/Library/Application Support/AaajiaoImporter/workspace` and performs all processing there
until the user explicitly applies accepted changes back to the repository root.

## Current flow

1. Bootstrap a dedicated workspace from bundled seed data, then refresh the data baseline from GitHub.
2. Run incremental sync or submit a manual artwork URL.
3. Review `ready_for_review` and `needs_review` records in the menu bar app.
4. Preview the apply transaction, then explicitly confirm the git writeback.

## Validation model

AI validation is split into two stages:

1. OpenAI returns a strict structured record schema for `artwork / exhibition / unknown`.
2. The local helper re-validates slug/title consistency, type-as-title mistakes, contamination signals, and required-field completeness before a record can reach `ready_for_review`.

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
./macos/Build/build_local_app.sh
./macos/Build/smoke_test_app.sh
./macos/Build/run_acceptance_checks.sh
./macos/Build/run_git_transaction_checks.sh
./macos/Build/run_live_import_check.sh
./macos/Build/check_repo_apply_prereqs.sh
```

Release checklist:

```bash
open macos/Build/RELEASE_CHECKLIST.md
```

`prepare_seed.sh` writes `macos/Seed/seed_manifest.json`.
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
