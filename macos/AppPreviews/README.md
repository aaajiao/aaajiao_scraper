# Native UI preview

Build the production SwiftUI views with an isolated, in-memory helper and preferences:

```bash
./macos/Build/build_ui_preview.sh
```

The build creates `macos/.build/ui-preview/Importer Preview.app` and verifies its ad-hoc signature. It does not launch the app. The preview uses bundle identifier `com.aaajiao.importer.preview`, a 1200 × 820 main window, and a separate settings window.

The app compiles the production `AppModel`, DTOs, and views. Only the entrypoint, helper implementation, and preference storage differ. It does not bundle or start Python, access Keychain, read the real importer workspace, run Git, or call OpenAI. Public artwork images use the same URL loading as the production views. The sample key is a placeholder held in memory.

Sample records come from a static snapshot of selected entries in the shared portfolio. Review statuses and proposed field changes are illustrative:

- Batch 202: an update to Windows Gravestone with before/after field differences and bilingual text, new gumdrop artwork, a failed foam wave import with error history, and an accepted 404 record.
- Batch 101: Avatar and Cloud.data, for batch switching and additional review states.

All toolbar, search, filter, editor, accept, retry, and confirmation controls use the production views and model. The preview helper changes records in memory. Confirming a publish only removes accepted sample records and returns an explicit preview-only message; it never contacts a repository or remote.

Choose **Preview → Restore Sample Data** (⌘⌥0) or relaunch the app to reset the fixtures. Settings changes also remain in memory. Rebuild after changing production views or model interfaces to update the preview binary.

Choose **Preview → Appearance → System / Light / Dark** to inspect native appearance in this preview process. This changes only `NSApp.appearance`; it does not write system preferences or user defaults.
