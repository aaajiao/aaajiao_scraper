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

The helper now exposes the planned command surface:

- `bootstrapWorkspace`
- `startIncrementalSync`
- `submitManualURL`
- `listPendingRecords`
- `acceptRecord`
- `rejectRecord`
- `getApplyPreview`
- `applyAcceptedRecords`

Build locally with:

```bash
./macos/Build/build_local_app.sh
```

The resulting app bundle is written to `dist/Aaajiao Importer.app`.
