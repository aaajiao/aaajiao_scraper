import AppKit
import Foundation
import SwiftUI

let settingsWindowID = "settings"
let importerWindowID = "importer"

func presentSettingsWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.async {
        openWindow(id: settingsWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

func presentImporterWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.async {
        openWindow(id: importerWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

func closeSettingsWindow() {
    if let settingsWindow = NSApp.windows.first(where: { $0.title == "Settings" }) {
        settingsWindow.performClose(nil)
        return
    }
    NSApp.keyWindow?.performClose(nil)
}

enum ImporterBusyAction {
    case bootstrap
    case importURL
    case syncSite
    case reloadResults
    case acceptRecord
    case deleteRecord
    case discardRun
    case resetWorkspace
    case prepareGitHubSync
    case syncGitHub
    case refreshBaseline
}

/// Incremental progress for `startSync()`, reported by the helper while it
/// works through a batch of URLs. nil until the first progress line arrives
/// (or for the whole run, on a helper build that doesn't emit any).
struct SyncProgress: Equatable {
    let completed: Int
    let total: Int
}

enum StatusTone: Equatable {
    case neutral
    case info
    case success
    case warning
    case error
}

@MainActor
final class AppModel: ObservableObject {
    @Published var manualURL = ""
    @Published var currentBatchID: Int?
    @Published var currentBatchDetail: BatchDetailResponse?
    @Published var selectedRecordID: Int?
    @Published var currentApplyPreview: ApplyPreview?
    @Published var currentBusyAction: ImporterBusyAction?
    @Published var syncProgress: SyncProgress?
    @Published var isShowingApplyConfirmation = false
    @Published var isShowingResetConfirmation = false
    @Published var isShowingImportSheet = false
    @Published var isShowingDeleteConfirmation = false
    @Published var isShowingDiscardConfirmation = false
    @Published var statusMessage = "Ready"
    @Published var statusTone: StatusTone = .neutral
    @Published var settings = AppSettings.empty
    @Published var settingsDraftOpenAIKey = ""
    @Published var settingsDraftOpenAIModelPreset = OpenAIModelPreset.defaultPreset
    @Published var settingsDraftCustomOpenAIModel = ""
    @Published var settingsStatusMessage = ""

    private let helper = HelperClient()
    private var hasBootstrapped = false

    // Keychain reads are relatively expensive and the derived properties below
    // are re-evaluated on every view update, so the last load is cached; call
    // reloadKeychainCache() wherever the stored key may have changed or a
    // user-initiated action should re-check availability (e.g. after the user
    // unlocked their keychain).
    @Published private var cachedKeychainLoad = KeychainStore.load()

    init() {
        let modelSelection = OpenAIModelSettingsStore.load()
        settingsDraftOpenAIKey = savedOpenAIKey
        settingsDraftOpenAIModelPreset = modelSelection.preset
        settingsDraftCustomOpenAIModel = modelSelection.customModel
    }

    private func reloadKeychainCache() {
        cachedKeychainLoad = KeychainStore.load()
    }

    var savedOpenAIKey: String {
        if case .found(let value) = cachedKeychainLoad {
            return value
        }
        return ""
    }

    /// True when the last Keychain lookup failed with something other than
    /// "no item saved" (e.g. locked keychain, auth failure) — distinct from
    /// simply never having saved a key.
    var hasKeychainAccessFailure: Bool {
        if case .failure = cachedKeychainLoad {
            return true
        }
        return false
    }

    var savedOpenAIModelSelection: OpenAIModelSelection {
        OpenAIModelSettingsStore.load()
    }

    var hasSavedOpenAIKey: Bool {
        !savedOpenAIKey.isEmpty
    }

    var trimmedDraftOpenAIKey: String {
        settingsDraftOpenAIKey.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var trimmedDraftCustomOpenAIModel: String {
        settingsDraftCustomOpenAIModel.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var draftOpenAIModelSelection: OpenAIModelSelection {
        OpenAIModelSelection(
            preset: settingsDraftOpenAIModelPreset,
            customModel: trimmedDraftCustomOpenAIModel
        )
    }

    var effectiveOpenAIModel: String {
        let configured = settings.openai_model.trimmingCharacters(in: .whitespacesAndNewlines)
        return configured.isEmpty ? savedOpenAIModelSelection.effectiveModel : configured
    }

    var effectiveOpenAIModelSource: String {
        let configured = settings.openai_model_source.trimmingCharacters(in: .whitespacesAndNewlines)
        return configured.isEmpty ? savedOpenAIModelSelection.source : configured
    }

    var canSaveSettings: Bool {
        draftOpenAIModelSelection.isValid
    }

    var isSettingsDirty: Bool {
        trimmedDraftOpenAIKey != savedOpenAIKey || draftOpenAIModelSelection != savedOpenAIModelSelection
    }

    var canRunProtectedActions: Bool {
        hasSavedOpenAIKey && !hasKeychainAccessFailure
    }

    var canSubmitManualURL: Bool {
        !isBusy && canRunProtectedActions && !manualURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var isBusy: Bool {
        currentBusyAction != nil
    }

    var isImportingURL: Bool {
        currentBusyAction == .importURL
    }

    var isSyncingSite: Bool {
        currentBusyAction == .syncSite
    }

    var isReloadingResults: Bool {
        currentBusyAction == .reloadResults
    }

    var isSyncingGitHub: Bool {
        currentBusyAction == .syncGitHub
    }

    var isPreparingGitHubSync: Bool {
        currentBusyAction == .prepareGitHubSync
    }

    var isRefreshingBaseline: Bool {
        currentBusyAction == .refreshBaseline
    }

    var currentBatchSummary: BatchSummary? {
        currentBatchDetail?.batch
    }

    var visibleCurrentRecords: [ProposedRecord] {
        (currentBatchDetail?.records ?? []).filter { $0.status != "rejected" }
    }

    var selectedRecord: ProposedRecord? {
        // No selection means no selection: the default "select the first row"
        // behavior is applied once at data-load time in syncSelection(with:),
        // not implicitly on every read here.
        guard let selectedRecordID else { return nil }
        return visibleCurrentRecords.first { $0.id == selectedRecordID }
    }

    var hasAcceptedRecords: Bool {
        (currentBatchDetail?.accepted_count ?? 0) > 0
    }

    var hasCurrentRun: Bool {
        currentBatchDetail != nil
    }

    var hasSelectedRecord: Bool {
        selectedRecord != nil
    }

    var currentRunTitle: String {
        guard let batch = currentBatchSummary else { return "No current results" }
        return batch.mode == "manual" ? "Single URL import" : "Site sync in review"
    }

    var reviewStatusValue: String {
        guard let detail = currentBatchDetail else { return "Nothing to review" }
        if detail.accepted_count > 0 {
            return "\(detail.accepted_count) accepted"
        }
        if detail.pending_count > 0 {
            return "\(detail.pending_count) pending"
        }
        if detail.failed_count > 0 {
            return "\(detail.failed_count) failed"
        }
        return "Ready"
    }

    var canRequestGitHubSync: Bool {
        hasAcceptedRecords && !isBusy
    }

    var canConfirmGitHubSync: Bool {
        guard let preview = currentApplyPreview else { return false }
        return hasAcceptedRecords && preview.will_push && !isBusy
    }

    var gitHubSyncActionTitle: String {
        "Sync GitHub…"
    }

    var gitHubSyncActionSymbol: String {
        "arrow.up.circle.fill"
    }

    var canAcceptSelectedRecord: Bool {
        guard let record = selectedRecord else { return false }
        return !isBusy && record.status != "accepted" && record.status != "failed"
    }

    var canDeleteSelectedRecord: Bool {
        hasSelectedRecord && !isBusy
    }

    var canDiscardCurrentRun: Bool {
        hasCurrentRun && !isBusy
    }

    var selectedRecordSourceURL: URL? {
        guard let record = selectedRecord else { return nil }
        return URL(string: record.url)
    }

    var hasBlockingReviewState: Bool {
        if settings.baseline_status == "sync_skipped_pending_review" {
            return true
        }
        return (currentBatchDetail?.total_records ?? 0) > 0
    }

    var canRefreshBaseline: Bool {
        !isBusy && !hasBlockingReviewState
    }

    var shouldAnimateGitHubSyncReady: Bool {
        hasAcceptedRecords && !isBusy && !isPreparingGitHubSync && !isSyncingGitHub
    }

    var baselineCommitURL: URL? {
        githubCommitURL(sourceURL: settings.baseline_source_url, commit: settings.baseline_commit)
    }

    var busyStatusMessage: String? {
        switch currentBusyAction {
        case .bootstrap:
            return "Preparing workspace..."
        case .importURL:
            return "Importing URL..."
        case .syncSite:
            guard let syncProgress else { return "Syncing site..." }
            return "Syncing site... (\(syncProgress.completed)/\(syncProgress.total))"
        case .reloadResults:
            return "Reloading results..."
        case .acceptRecord:
            return "Accepting result..."
        case .deleteRecord:
            return "Removing result..."
        case .discardRun:
            return "Discarding results..."
        case .resetWorkspace:
            return "Resetting workspace..."
        case .prepareGitHubSync:
            return "Preparing GitHub sync preview..."
        case .syncGitHub:
            return "Syncing accepted results..."
        case .refreshBaseline:
            return "Refreshing workspace baseline..."
        case .none:
            return nil
        }
    }

    var shouldShowStatusBanner: Bool {
        hasSavedOpenAIKey == false || hasKeychainAccessFailure || busyStatusMessage != nil || statusTone != .neutral || hasBaselineWarning
    }

    var hasBaselineWarning: Bool {
        if let error = settings.baseline_error, !error.isEmpty {
            return true
        }
        if settings.baseline_status == "seed_fallback" || settings.baseline_status == "sync_skipped_pending_review" {
            return true
        }
        return false
    }

    /// Single gate for every helper-backed action. Returns false (and does
    /// nothing) when another action is already in flight, so only one helper
    /// subprocess touches the workspace at a time. Callers that pass the gate
    /// must balance it with endExclusive(), typically via `defer` inside the
    /// Task that runs the async work.
    private func beginExclusive(_ action: ImporterBusyAction) -> Bool {
        guard !isBusy else { return false }
        currentBusyAction = action
        return true
    }

    private func endExclusive() {
        currentBusyAction = nil
    }

    func bootstrapIfNeeded() {
        guard !hasBootstrapped else { return }
        hasBootstrapped = true
        bootstrapAndRefresh()
    }

    func bootstrapAndRefresh() {
        guard beginExclusive(.bootstrap) else { return }
        Task {
            defer { endExclusive() }
            let response: BootstrapResponse
            do {
                response = try await helper.bootstrapWorkspace(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                syncDraftWithSavedSettingsIfNeeded()
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            // Read-only refresh is separate: a failure to load the review
            // results must not be reported as the workspace bootstrap failing.
            do {
                try await refresh(allowFallbackBatch: true)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus("Workspace ready, but loading review results failed: \(display(error))", tone: .warning)
            }
        }
    }

    func refreshFromUI() {
        guard beginExclusive(.reloadResults) else { return }
        Task {
            defer { endExclusive() }
            do {
                try await refresh(allowFallbackBatch: currentBatchID == nil)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    /// Reloads settings and the active/latest batch. A failure to load a batch
    /// is propagated to the caller (after clearing the now-unloadable run) so
    /// the current review results are never dropped silently — the caller is
    /// responsible for surfacing the error.
    func refresh(allowFallbackBatch: Bool) async throws {
        let response = try await helper.listPendingRecords(
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        settings = response.settings
        syncDraftWithSavedSettingsIfNeeded()

        if let currentBatchID {
            do {
                try await loadBatch(batchID: currentBatchID, updateStatusMessage: false)
            } catch {
                clearCurrentRun()
                throw error
            }
            return
        }

        if allowFallbackBatch, let latestBatch = response.batches.first {
            do {
                try await loadBatch(batchID: latestBatch.id, updateStatusMessage: false)
            } catch {
                clearCurrentRun()
                throw error
            }
            setStatus("Loaded the latest review results", tone: .info)
            return
        }

        if hasKeychainAccessFailure {
            setStatus("Could not read the OpenAI key from Keychain. Unlock your keychain and try again.", tone: .error)
        } else if !hasSavedOpenAIKey {
            setStatus("OpenAI key missing. Save a key to enable imports.", tone: .warning)
        } else {
            setStatus("Ready for a new import", tone: .neutral)
        }
    }

    func startSync() {
        reloadKeychainCache()
        guard canRunProtectedActions else {
            if hasKeychainAccessFailure {
                setStatus("Could not read the OpenAI key from Keychain. Unlock your keychain and try again.", tone: .error)
            } else {
                setStatus("OpenAI key missing. Save a key to continue.", tone: .warning)
            }
            return
        }
        guard beginExclusive(.syncSite) else { return }
        syncProgress = nil
        setStatus("Syncing site...", tone: .info)
        Task {
            defer {
                endExclusive()
                syncProgress = nil
            }
            do {
                let result = try await helper.startIncrementalSync(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source,
                    onProgress: { [weak self] progress in
                        Task { @MainActor in
                            // Ignore stray progress lines that arrive after this
                            // sync has already finished/been superseded.
                            guard let self, self.currentBusyAction == .syncSite else { return }
                            self.syncProgress = SyncProgress(completed: progress.completed, total: progress.total)
                        }
                    }
                )
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                setStatus("Synced \(result.urls_processed) URLs", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestImportSheet() {
        isShowingImportSheet = true
    }

    func cancelImportSheet() {
        isShowingImportSheet = false
    }

    func requestWorkspaceReset() {
        isShowingResetConfirmation = true
    }

    func confirmWorkspaceReset() {
        guard beginExclusive(.resetWorkspace) else { return }
        setStatus("Resetting workspace and refreshing the GitHub baseline...", tone: .info)
        Task {
            defer { endExclusive() }
            let response: BootstrapResponse
            do {
                response = try await helper.resetWorkspace(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                clearCurrentRun()
                isShowingResetConfirmation = false
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            do {
                try await refresh(allowFallbackBatch: false)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus("\(workspaceStatusMessage(for: response)) Reloading results failed — use Reload Results.", tone: .warning)
            }
        }
    }

    func refreshWorkspaceBaseline() {
        guard canRefreshBaseline else {
            setStatus("Finish or discard the current review results before refreshing the baseline.", tone: .warning)
            return
        }
        guard beginExclusive(.refreshBaseline) else { return }
        setStatus("Refreshing the GitHub baseline...", tone: .info)
        Task {
            defer { endExclusive() }
            let response: BootstrapResponse
            do {
                response = try await helper.refreshWorkspaceBaseline(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            do {
                try await refresh(allowFallbackBatch: false)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus("\(workspaceStatusMessage(for: response)) Reloading results failed — use Reload Results.", tone: .warning)
            }
        }
    }

    func submitURL() {
        reloadKeychainCache()
        guard canRunProtectedActions else {
            if hasKeychainAccessFailure {
                setStatus("Could not read the OpenAI key from Keychain. Unlock your keychain and try again.", tone: .error)
            } else {
                setStatus("OpenAI key missing. Save a key to continue.", tone: .warning)
            }
            return
        }
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard beginExclusive(.importURL) else { return }
        setStatus("Importing URL...", tone: .info)
        Task {
            defer { endExclusive() }
            do {
                let result = try await helper.submitManualURL(
                    trimmed,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                manualURL = ""
                isShowingImportSheet = false
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                setStatus("Imported \(result.url)", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func acceptSelectedRecord() {
        guard let record = selectedRecord else { return }
        guard beginExclusive(.acceptRecord) else { return }
        Task {
            defer { endExclusive() }
            do {
                _ = try await helper.acceptRecord(
                    id: record.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                if let batchID = currentBatchID {
                    try await loadBatch(batchID: batchID, updateStatusMessage: false)
                }
                setStatus("Accepted \(record.displayTitle)", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestDeleteSelectedRecord() {
        guard canDeleteSelectedRecord else { return }
        isShowingDeleteConfirmation = true
    }

    func confirmDeleteSelectedRecord() {
        guard let record = selectedRecord else { return }
        guard let batchID = currentBatchID else { return }
        isShowingDeleteConfirmation = false
        guard beginExclusive(.deleteRecord) else { return }
        Task {
            defer { endExclusive() }
            do {
                if visibleCurrentRecords.count <= 1 {
                    _ = try await helper.deleteBatch(
                        batchID: batchID,
                        openAIKey: savedOpenAIKey,
                        openAIModel: savedOpenAIModelSelection.effectiveModel,
                        openAIModelSource: savedOpenAIModelSelection.source
                    )
                    clearCurrentRun()
                    try await refresh(allowFallbackBatch: false)
                    setStatus("Discarded current results", tone: .success)
                    return
                }

                _ = try await helper.rejectRecord(
                    id: record.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await loadBatch(batchID: batchID, updateStatusMessage: false)
                setStatus("Deleted \(record.displayTitle)", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestDiscardCurrentRun() {
        guard canDiscardCurrentRun else { return }
        isShowingDiscardConfirmation = true
    }

    func confirmDiscardCurrentRun() {
        guard let batchID = currentBatchID else { return }
        isShowingDiscardConfirmation = false
        guard beginExclusive(.discardRun) else { return }
        Task {
            defer { endExclusive() }
            do {
                _ = try await helper.deleteBatch(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                clearCurrentRun()
                try await refresh(allowFallbackBatch: false)
                setStatus("Discarded current results", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestApply() {
        guard hasAcceptedRecords else { return }
        // A cached preview can be presented immediately without a helper call.
        if let preview = currentApplyPreview {
            presentApplyPreview(preview)
            return
        }
        guard let batchID = currentBatchID else { return }
        guard beginExclusive(.prepareGitHubSync) else { return }
        setStatus("Preparing GitHub sync preview...", tone: .info)
        Task {
            defer { endExclusive() }
            do {
                let preview = try await helper.getApplyPreview(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                currentApplyPreview = preview
                presentApplyPreview(preview)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    private func presentApplyPreview(_ preview: ApplyPreview) {
        if preview.will_push {
            isShowingApplyConfirmation = true
        } else {
            let message = preview.error_message.isEmpty
                ? "Accepted results are not ready to sync to GitHub yet."
                : preview.error_message
            setStatus(message, tone: .warning)
        }
    }

    func confirmApply() {
        guard let batchID = currentBatchID else { return }
        guard beginExclusive(.syncGitHub) else { return }
        setStatus("Syncing accepted results to GitHub...", tone: .info)
        Task {
            defer { endExclusive() }
            let result: ApplyResponse
            do {
                result = try await helper.applyAcceptedRecords(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                isShowingApplyConfirmation = false
                clearCurrentRun()
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            // The push already happened and is irreversible. Report success up
            // front so a failing read-only refresh can only downgrade it to a
            // warning, never present it as the sync itself having failed.
            do {
                try await refresh(allowFallbackBatch: false)
                setStatus("Synced to GitHub at \(result.applied_commit_sha)", tone: .success)
            } catch {
                setStatus("Synced to GitHub at \(result.applied_commit_sha), but reloading results failed — use Reload Results.", tone: .warning)
            }
        }
    }

    @discardableResult
    func saveSettings() -> Bool {
        let newValue = trimmedDraftOpenAIKey
        let modelSelection = draftOpenAIModelSelection
        guard modelSelection.isValid else {
            settingsStatusMessage = "Enter a custom model name or choose a preset."
            return false
        }
        if !isSettingsDirty {
            settingsStatusMessage = ""
            return true
        }
        do {
            if newValue.isEmpty {
                try KeychainStore.delete()
            } else {
                try KeychainStore.save(newValue)
            }
            OpenAIModelSettingsStore.save(modelSelection)
            reloadKeychainCache()
            settingsDraftOpenAIKey = newValue
            settingsDraftOpenAIModelPreset = modelSelection.preset
            settingsDraftCustomOpenAIModel = modelSelection.customModel
            settingsStatusMessage = newValue.isEmpty
                ? "OpenAI key cleared. Model selection saved."
                : "OpenAI settings saved."
            refreshFromUI()
            return true
        } catch {
            settingsStatusMessage = display(error)
            return false
        }
    }

    func revertSettings() {
        settingsDraftOpenAIKey = savedOpenAIKey
        settingsDraftOpenAIModelPreset = savedOpenAIModelSelection.preset
        settingsDraftCustomOpenAIModel = savedOpenAIModelSelection.customModel
        settingsStatusMessage = "Reverted unsaved changes."
    }

    func clearSavedKey() {
        do {
            try KeychainStore.delete()
            reloadKeychainCache()
            settingsDraftOpenAIKey = ""
            settingsStatusMessage = "OpenAI key cleared from macOS Keychain."
            refreshFromUI()
        } catch {
            settingsStatusMessage = display(error)
        }
    }

    func quitApplication() {
        NSApplication.shared.terminate(nil)
    }

    func openSelectedRecordSourcePage() {
        guard let url = selectedRecordSourceURL else { return }
        NSWorkspace.shared.open(url)
    }

    func openWorkspaceFolderOrCopyPath() {
        let trimmedPath = settings.workspace_path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPath.isEmpty else {
            setStatus("Workspace path is unavailable.", tone: .warning)
            return
        }

        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: trimmedPath, isDirectory: &isDirectory)
        if exists && isDirectory.boolValue {
            let didOpen = NSWorkspace.shared.open(URL(fileURLWithPath: trimmedPath, isDirectory: true))
            if didOpen {
                setStatus("Opened workspace folder in Finder.", tone: .info)
                return
            }
        }

        copyToPasteboard(trimmedPath)
        setStatus("Could not open folder. Workspace path copied to clipboard.", tone: .warning)
    }

    private func loadBatch(batchID: Int, updateStatusMessage: Bool) async throws {
        let detail = try await helper.getBatchDetail(
            batchID: batchID,
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        currentBatchID = batchID
        currentBatchDetail = detail
        syncSelection(with: detail.records.filter { $0.status != "rejected" })
        // The apply preview is a full-merge computation; fetch it lazily when
        // the user actually requests a GitHub sync (requestApply), not eagerly
        // after every data reload. Any preview from a prior load is now stale.
        currentApplyPreview = nil
        if updateStatusMessage {
            setStatus("Loaded current results", tone: .info)
        }
    }

    private func clearCurrentRun() {
        // Intentionally does not touch currentBusyAction: callers invoke this
        // mid-operation (e.g. before a follow-up refresh) and the busy gate
        // must stay held until the whole action finishes via endExclusive().
        currentBatchID = nil
        currentBatchDetail = nil
        selectedRecordID = nil
        currentApplyPreview = nil
    }

    private func syncSelection(with records: [ProposedRecord]) {
        if let selectedRecordID, records.contains(where: { $0.id == selectedRecordID }) {
            return
        }
        selectedRecordID = records.first?.id
    }

    private func syncDraftWithSavedSettingsIfNeeded() {
        guard !isSettingsDirty else { return }
        settingsDraftOpenAIKey = savedOpenAIKey
        settingsDraftOpenAIModelPreset = savedOpenAIModelSelection.preset
        settingsDraftCustomOpenAIModel = savedOpenAIModelSelection.customModel
    }

    private func display(_ error: Error) -> String {
        error.localizedDescription
    }

    private func setStatus(_ message: String, tone: StatusTone) {
        statusMessage = message
        statusTone = tone
    }

    private func copyToPasteboard(_ value: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }

    private func workspaceStatusMessage(for response: BootstrapResponse) -> String {
        switch response.status {
        case "initialized_synced":
            return "Workspace initialized from the latest GitHub baseline."
        case "initialized_seed_fallback":
            return "GitHub baseline unavailable. Workspace initialized from the bundled seed."
        case "baseline_synced":
            return "Workspace baseline refreshed from GitHub."
        case "baseline_seed_fallback":
            return "GitHub baseline refresh failed. Using bundled seed files."
        case "baseline_sync_skipped_pending_review":
            return "Skipped baseline refresh to protect current review results."
        case "reset_synced":
            return "Workspace reset and refreshed from the latest GitHub baseline."
        case "reset_seed_fallback":
            return "Workspace reset with bundled seed because GitHub was unavailable."
        default:
            return "Workspace updated."
        }
    }

    private func workspaceStatusTone(for status: String) -> StatusTone {
        switch status {
        case "initialized_seed_fallback", "baseline_seed_fallback", "baseline_sync_skipped_pending_review", "reset_seed_fallback":
            return .warning
        case "initialized_synced", "baseline_synced", "reset_synced":
            return .success
        default:
            return .info
        }
    }
}

@main
struct AaajiaoImporterApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra("aaajiao Importer", systemImage: "tray.full") {
            MenuBarMenuView()
                .environmentObject(model)
        }

        Window("Importer", id: importerWindowID) {
            ContentView()
                .environmentObject(model)
        }
        .defaultSize(width: 1180, height: 780)
        .windowResizability(.contentMinSize)
        .commands {
            AppCommands(model: model)
        }

        Window("Settings", id: settingsWindowID) {
            SettingsView()
                .environmentObject(model)
        }
        .windowResizability(.contentSize)
    }
}
