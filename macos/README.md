# Aaajiao Importer for macOS

This directory contains a local-only macOS importer app and its bundled Python engine.

The implementation intentionally does not modify the existing repository code or cache files.
At build time it copies the current `scraper/`, `.cache/`, `aaajiao_works.json`, and
`aaajiao_portfolio.md` into `macos/` seed/vendor directories. At runtime it initializes a
workspace under `~/Library/Application Support/AaajiaoImporter/workspace` and performs all
processing there until the user explicitly applies accepted changes back to the repository root.

Current flow:

1. Bootstrap a dedicated workspace from bundled seed data.
2. Run incremental sync or submit a manual artwork URL.
3. Review `ready_for_review` and `needs_review` records in the menu bar app.
4. Preview the apply transaction, then explicitly confirm the git writeback.

AI validation is now split into two stages:

1. OpenAI returns a strict structured record schema for `artwork / exhibition / unknown`.
2. The local helper re-validates slug/title consistency, type-as-title mistakes, contamination
   signals in materials/descriptions, and required-field completeness before a record can reach
   `ready_for_review`.

The helper now exposes the planned command surface:

- `bootstrapWorkspace`
- `resetWorkspace`
- `startIncrementalSync`
- `submitManualURL`
- `listPendingRecords`
- `acceptRecord`
- `rejectRecord`
- `getApplyPreview`
- `applyAcceptedRecords`

Build scripts:

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

`prepare_seed.sh` now writes `macos/Seed/seed_manifest.json`.
At runtime the helper writes `workspace_manifest.json` into the local workspace and validates
the bundled seed version before reusing the workspace.

`wheelhouse_requirements.txt` is the pinned runtime dependency lock for the bundled Python
environment. `refresh_wheelhouse.sh` downloads wheels into `macos/Vendor/wheelhouse/`, and
`verify_wheelhouse.sh` proves that the wheelhouse can satisfy an offline install.

Build locally with:

```bash
./macos/Build/build_local_app.sh
```

The resulting app bundle is written to `dist/Aaajiao Importer.app`.
