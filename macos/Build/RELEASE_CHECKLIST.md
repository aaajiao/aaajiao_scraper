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
- AppModel tests cover operation exclusion, failed import feedback, fresh publication
  preflight, cancellation, and publication success followed by a reload failure
- Process tests cover timeout/cancellation, child-process cleanup, and large pipe output
- Invalid OpenAI credentials fail before creating a batch or fetching artwork pages;
  authentication failure during a run preserves one retryable result and stops the rest
- Settings distinguishes saved/unverified/verified credentials and offers Check API Key;
  editing the draft clears stale check results, and errors never display key fragments
- Restricted model-list access and network failures are not labelled as invalid keys

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
- `applyAcceptedRecords --dry-run` returns `staging_path` containing generated artifacts
  while leaving the workspace baseline unchanged
- `resetWorkspace` recreates the workspace and refreshes the GitHub baseline, or reports a clear seed fallback
- `applyAcceptedRecords` commits and pushes to `origin/<baseline branch>` from a managed
  temporary clone (it never writes to the sandbox checkout itself)
- `applyAcceptedRecords` is rejected with a clear error when the sandbox checkout's
  current branch/upstream doesn't match the baseline branch
- `applyAcceptedRecords` marks the batch failed (with the remote's rejection reason
  recorded) when the push itself is rejected, instead of losing the failure silently
- Concurrent remote additions survive publication; conflicting edits to the reviewed
  artwork stop publication and keep the queue intact
- Failed apply followed by discard cannot contaminate a later batch
- Partial publication keeps failed and unreviewed records in the same queue for retry
- Cancelling before the first result or mid-batch does not checkpoint unprocessed URLs
  or leave an empty batch that blocks baseline refresh
- A confirmed push followed by local cleanup failure reports its SHA and a warning,
  with recovery from the saved publish receipt
- Field editing changes only review data and resets acceptance; shortened/cleared fields
  and removed images match both the Changes view and the published output

Before packaging a UI change, build `./macos/Build/build_ui_preview.sh` and inspect its
isolated native app. Check search/status filters, switching runs, accept-and-next, failed
retry, field editing and validation, the publication sheet, image loading/fallback, and
Settings. Check a compact window and both light/dark appearance. The preview uses in-memory
fixtures and never publishes to a real repository.

- At 900 × 620, Import URL, Check for Updates, and Publish retain visible text; More has
  a VoiceOver name, and review actions fit without clipping.
- Relaunching the app presents the Importer window, while closing it leaves the menu
  bar entry available. Both columns shrink and scroll without clipping their headers
  or bottom actions; native split-view minimum heights must not exceed the viewport.
- Check Empty Queue, No Site Updates, and All Accepted preview scenarios; search with no
  matches must differ from a genuinely empty queue.
- Accepting the last pending artwork exposes the publication step; Review Next reveals
  pending artworks even when a search or status filter had hidden them.
- Publication lists included artworks and returns a count-based confirmation; partial
  publication and local-cleanup warnings do not imply that all review work is finished.
- Import without a key gives a Settings entry point. Settings distinguishes checking the
  draft from saving it, and labels unsaved changes.
- Progress shows the actual helper stage, current URL, completed count, and Stop Import.
  Known STAGE protocol lines never leak into normal helper errors, even without a callback.

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
