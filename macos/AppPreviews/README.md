# Native UI preview

Build the production SwiftUI views with an isolated, in-memory helper and preferences:

```bash
./macos/Build/build_ui_preview.sh
```

The build creates `macos/.build/ui-preview/Importer Preview.app` and verifies its ad-hoc signature. It does not launch the app. The preview uses bundle identifier `com.aaajiao.importer.preview`, a 1180 × 780 main window, and a separate settings window.

The app compiles the production `AppModel`, DTOs, and views. Only the entrypoint, helper implementation, and preference storage differ. It does not bundle or start Python, access Keychain, read the real importer workspace, run Git, or call OpenAI. Public artwork images use the same URL loading as the production views. The sample key is a placeholder held in memory.

Sample records come from a static snapshot of selected entries in the shared portfolio. Review statuses and proposed field changes are illustrative:

- Batch 202: an update to Windows Gravestone with before/after field differences and bilingual text, new gumdrop artwork, a failed foam wave import with error history, and an accepted 404 record.
- Batch 101: Avatar and Cloud.data, for batch switching and additional review states.

All toolbar, search, filter, editor, accept, retry, and confirmation controls use the production views and model. The preview helper changes records in memory. Confirming a publish removes accepted sample records and returns normal success, retaining any unresolved records so partial publication can also be checked. The helper does not misuse the local-cleanup warning field to label preview mode. The **Preview** menu states: **Preview · Changes stay in memory; nothing is uploaded.** No repository or remote is contacted.

Choose **Preview → Queue Scenarios** to inspect the main workflow states:

- **Empty Queue** removes every sample record and run, so the initial import actions can be checked.
- **No Site Updates** loads a completed site-check run with zero records. **Check for Updates** then simulates another successful check returning zero new artworks, without creating review records.
- **All Accepted** restores the sample runs with every record accepted, so the review-to-publish flow can be checked.
- **Restore Sample Data** (⌘⌥0) restores the original mixed review states.

Scenario changes replace only the helper's in-memory records and refresh the production model's selection and queue. The controls are unavailable while an operation or review dialog is active. Relaunching also restores the fixtures; settings changes remain in memory. Rebuild after changing production views or model interfaces to update the preview binary.

The simulated site check emits the production progress protocol: `STAGE checking_access`, `STAGE discovering_urls`, then `PROGRESS 0/4` followed by `reading_page` / `validating_record` stages and each completed count. Four sample steps take about four seconds, leaving time to inspect stage messages or stop the operation. The no-updates scenario takes about one second and emits the checking/discovery stages without a misleading `0/0` progress bar. These events use synthetic page labels and do not perform HTTP or OpenAI requests.

Choose **Preview → Appearance → System / Light / Dark** to inspect native appearance in this preview process. This changes only `NSApp.appearance`; it does not write system preferences or user defaults.

Choose **Preview → Window Size → Compact (900×620) / Standard (1180×780)** to resize and center the preview's main window for layout checks. These sizes describe the usable `contentLayoutRect`; the outer frame adds titlebar/toolbar space and respects the window's minimum size. The window is found by its `importer` identifier, so changing the selected artwork's title does not break resizing. Settings and production app windows are left alone.

**Preview → API Authentication** switches between **Valid Key**, **Rejected Key**, and **Connection Unavailable**. The scenario changes only an in-memory flag; it does not replace the sample key or touch Keychain. Use **Settings → Check API Key** to inspect each result. Rejected-key checks raise the production authentication error type; connection failures remain unverified. **Check for Updates**, URL import, and retry stop before creating a batch or simulating any extraction when the scenario is rejected or disconnected. Switch back to **Valid Key** to resume. No OpenAI request is made by these scenarios.
