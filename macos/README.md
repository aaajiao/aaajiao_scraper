# Aaajiao Importer for macOS

This directory contains a local-only macOS importer app and its bundled Python engine.

The implementation intentionally does not modify the existing repository code or cache files.
At build time it copies the current `scraper/`, `.cache/`, `aaajiao_works.json`, and
`aaajiao_portfolio.md` into `macos/` seed/vendor directories. At runtime it initializes a
workspace under `~/Library/Application Support/AaajiaoImporter/workspace` and performs all
processing there until the user explicitly applies accepted changes back to the repository root.

Build locally with:

```bash
./macos/Build/build_local_app.sh
```

The resulting app bundle is written to `dist/Aaajiao Importer.app`.
