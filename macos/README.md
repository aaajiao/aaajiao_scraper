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

Publishing reads the latest remote data and reapplies only accepted records. Each record
keeps the baseline it was reviewed against; a conflicting remote edit to the same artwork
stops publication and leaves the review queue intact. Unrelated remote additions and edits
are preserved. Output generation and validation happen in the managed clone, and the local
workspace baseline is updated only after a confirmed push. A failed or discarded apply
cannot leak its proposed records into another batch. A durable publish receipt distinguishes
a confirmed publication from local cleanup errors, which are returned as warnings with the
published commit SHA.

`applyAcceptedRecords --dry-run` writes the proposed artifacts into
`workspace/apply_previews/batch-<id>/` and returns `staging_path`; it does not replace the
workspace baseline or publish anything. Failed imports remain available for `retryRecord`
in their original batch. A partial publication keeps failed and unreviewed records in the
same queue. Incremental discovery checkpoints URLs only after publication, so cancellation
cannot hide URLs that had not yet been processed; unresolved queue entries are not duplicated
by subsequent syncs.

App upgrades refresh the bundled scraper code without replacing valid workspace data,
incremental sitemap checkpoints, or publication receipts. Those are durable user state;
only an explicit Reset starts a fresh workspace. If GitHub cannot be reached, an existing
valid published baseline is kept and reported as `cached_fallback`, with its commit and
timestamp intact, rather than being replaced with an older bundled snapshot.

Incremental checks also compare the effective merged artwork fields against the published
baseline. A validated result that would change no artwork fields is not queued again; its
observed sitemap version is acknowledged directly. A changed sitemap timestamp still causes
inspection, and real field changes, failed imports, and unvalidated results remain for
review. Manual URL imports and retries remain explicit inspection paths, even when their
artwork fields have not changed.

## Current flow

1. Bootstrap a dedicated workspace from bundled seed data, then refresh the data baseline from GitHub.
2. Choose **Check for Updates** to find new/changed website pages, or **Import URL…** for one artwork.
3. Review artwork details and changes, edit as needed, then **Accept**. Acceptance saves a local review decision.
4. Choose **Publish…**, check the included artworks, then explicitly confirm the push to `origin/<baseline
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
- `retryRecord`
- `updateRecord`
- `validateOpenAIKey`
- `getApplyPreview`
- `applyAcceptedRecords`

Helper commands run in an isolated process group. A timeout terminates and reaps the
execution process before the app releases its busy state; imports and site syncs also
support cancellation. Publication cannot be cancelled through the app. Import completion
messages distinguish successful, review-required, and failed results, and each publication
request runs a fresh preflight so a repaired Git configuration can be retried immediately.
Quitting during an import cancels it and waits for termination; quitting during publication
waits for the confirmed result before closing the app.

OpenAI access is checked before a new import creates a batch or fetches artwork pages.
An invalid key stops the operation immediately and opens a clear recovery path through
Settings. The Settings **Check API Key** button checks the draft key without saving it or
creating a review run. A saved key is shown as saved, not as verified. The check uses the
official [list-models endpoint](https://developers.openai.com/api/reference/python/resources/models/methods/list);
success confirms account access, while model-specific permissions are checked by the actual
validation request. Restricted keys without model-list permission are marked unverified and
can still attempt validation. Connection/service failures stop automatic imports before
scraping and are distinguished from invalid credentials.

If authentication fails after the initial check, the current extraction is kept as a failed,
retryable record and the remaining batch stops. Old review records containing authentication
errors can also be retried in place. Credential errors shown in the app and error history
omit API-key fragments. OpenAI requests reuse a session and use a five-second connection
timeout separately from the 120-second validation response timeout.

## Review interface

Launching the app opens the Importer window. Its menu bar entry remains available when
the window is closed. Resizing keeps the queue controls and review actions visible;
long lists and artwork details scroll within the available column height.

The sidebar switches between review runs and filters results by status, title, Chinese
title, or URL. Accepting a result advances to the next pending result. Failed rows have an
in-place retry action, and active imports have a Stop Import control.

Primary toolbar commands use visible text; ambiguous import and publish symbols are omitted to keep narrow windows readable. **Check for Updates**
imports from the website; **Publish** uploads accepted artworks to GitHub. Generic More
menus use labelled, accessible icon controls. Removal and reset actions keep text and
scope-specific confirmation. The sidebar's Settings entry shows the saved/checked/error
state of API access and opens the settings window.

The last pending artwork uses **Accept** rather than promising a next item. An accepted
artwork offers **Review Next** while other pending items exist, then **Publish**. Review
Next clears search/status filters to reveal the pending item. Empty queues, zero-update
checks, no matching search results, and confirmed publication have separate explanations
and actions. The publication receipt reports counts and a GitHub link; local cleanup
warnings remain visible, and a new import clears the preceding completion card.

Site imports report API checking, update discovery, page reading, and detail validation
as distinct phases, with the current URL and completed/total progress. Stopping leaves
completed work available for review. An import entry without a saved key opens an
explanation with a Settings action; it never silently ignores the click.

Artwork updates open in a Changes view that compares the saved baseline with the effective
values to be published. Old records without a baseline snapshot are labelled as unknown.
The Details view includes lazy image previews, source links, bilingual descriptions, and
import error history. Edit Fields saves corrections to the review database only and returns
an accepted result to `needs_review`. Explicit corrections can shorten or clear text and
remove images; they are preserved exactly when the result is subsequently accepted and
published. The source URL remains the record's fixed identity.

Publication has a dedicated review sheet showing artwork titles, accepted/new/updated counts, repository,
branch, and target files. Failed and unreviewed results remain in the queue after a partial
publication. Secondary workspace actions are grouped in the toolbar's More menu.

Keyboard commands: `⌘N` import URL, `⇧⌘I` check for updates, `⌘R` reload, `⌘Return` accept,
`⌥⌘]` review next artwork,
`⌘E` edit fields, `⇧⌘R` retry, `⇧⌘P` review publication, and `⌘,` settings. Editing uses native
text controls and supports their standard selection, copy/paste, and undo behavior.

Build the isolated native preview with `./macos/Build/build_ui_preview.sh`. It runs the
production views and model with an in-memory helper and preferences, allowing review-flow
and appearance checks without using Keychain, the real workspace, or GitHub. See
[`AppPreviews/README.md`](AppPreviews/README.md).

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
