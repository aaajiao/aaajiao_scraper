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

func openAIModelSourceLabel(_ source: String) -> String {
    switch source {
    case "custom":
        return "custom"
    case "preset":
        return "preset"
    default:
        return "default"
    }
}

private func githubCommitURL(sourceURL: String?, commit: String?) -> URL? {
    let trimmedCommit = commit?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard !trimmedCommit.isEmpty else { return nil }
    let trimmedSource = sourceURL?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard !trimmedSource.isEmpty else { return nil }

    let repoPath: String
    if trimmedSource.hasPrefix("https://github.com/") || trimmedSource.hasPrefix("http://github.com/") {
        repoPath = trimmedSource
            .replacingOccurrences(of: "https://github.com/", with: "")
            .replacingOccurrences(of: "http://github.com/", with: "")
    } else if trimmedSource.hasPrefix("git@github.com:") {
        repoPath = trimmedSource.replacingOccurrences(of: "git@github.com:", with: "")
    } else {
        return nil
    }

    let normalizedRepoPath = repoPath.hasSuffix(".git")
        ? String(repoPath.dropLast(4))
        : repoPath
    return URL(string: "https://github.com/\(normalizedRepoPath)/commit/\(trimmedCommit)")
}

enum ImporterFlowState: String {
    case idle
    case imported
    case reviewing
    case readyToSync
    case syncing
}

enum ImporterBusyAction {
    case importURL
    case syncSite
    case syncGitHub
    case refreshBaseline
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
    @Published var currentFlowState: ImporterFlowState = .idle
    @Published var currentBusyAction: ImporterBusyAction?
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

    init() {
        let savedKey = KeychainStore.load()
        let modelSelection = OpenAIModelSettingsStore.load()
        settingsDraftOpenAIKey = savedKey
        settingsDraftOpenAIModelPreset = modelSelection.preset
        settingsDraftCustomOpenAIModel = modelSelection.customModel
    }

    var savedOpenAIKey: String {
        KeychainStore.load()
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
        hasSavedOpenAIKey
    }

    var canSubmitManualURL: Bool {
        !isBusy && canRunProtectedActions && !manualURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var isBusy: Bool {
        currentFlowState == .syncing
    }

    var isImportingURL: Bool {
        currentBusyAction == .importURL
    }

    var isSyncingSite: Bool {
        currentBusyAction == .syncSite
    }

    var isSyncingGitHub: Bool {
        currentBusyAction == .syncGitHub
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
        if let selectedRecordID {
            return visibleCurrentRecords.first { $0.id == selectedRecordID }
        }
        return visibleCurrentRecords.first
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

    var canSyncCurrentRun: Bool {
        guard let preview = currentApplyPreview else { return false }
        return hasAcceptedRecords && preview.will_push
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

    var baselineCommitURL: URL? {
        githubCommitURL(sourceURL: settings.baseline_source_url, commit: settings.baseline_commit)
    }

    var busyStatusMessage: String? {
        switch currentBusyAction {
        case .importURL:
            return "Importing URL..."
        case .syncSite:
            return "Syncing site..."
        case .syncGitHub:
            return "Syncing accepted results..."
        case .refreshBaseline:
            return "Refreshing workspace baseline..."
        case .none:
            return nil
        }
    }

    var shouldShowStatusBanner: Bool {
        hasSavedOpenAIKey == false || busyStatusMessage != nil || statusTone != .neutral || hasBaselineWarning
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

    func bootstrapIfNeeded() {
        guard !hasBootstrapped else { return }
        hasBootstrapped = true
        bootstrapAndRefresh()
    }

    func bootstrapAndRefresh() {
        Task {
            do {
                let response = try helper.bootstrapWorkspace(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                syncDraftWithSavedSettingsIfNeeded()
                try await refresh(allowFallbackBatch: true)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func refreshFromUI() {
        Task {
            do {
                try await refresh(allowFallbackBatch: currentBatchID == nil)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func refresh(allowFallbackBatch: Bool) async throws {
        let response = try helper.listPendingRecords(
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        settings = response.settings
        syncDraftWithSavedSettingsIfNeeded()

        if let currentBatchID {
            do {
                try await loadBatch(batchID: currentBatchID, updateStatusMessage: false)
                return
            } catch {
                clearCurrentRun()
            }
        }

        if allowFallbackBatch, let latestBatch = response.batches.first {
            do {
                try await loadBatch(batchID: latestBatch.id, updateStatusMessage: false)
                setStatus("Loaded the latest review results", tone: .info)
                return
            } catch {
                clearCurrentRun()
            }
        }

        if !hasSavedOpenAIKey {
            currentFlowState = .idle
            setStatus("OpenAI key missing. Save a key to enable imports.", tone: .warning)
        } else {
            currentFlowState = .idle
            setStatus("Ready for a new import", tone: .neutral)
        }
    }

    func startSync() {
        guard canRunProtectedActions else {
            setStatus("OpenAI key missing. Save a key to continue.", tone: .warning)
            return
        }
        currentFlowState = .syncing
        currentBusyAction = .syncSite
        setStatus("Syncing site...", tone: .info)
        Task {
            do {
                let result = try helper.startIncrementalSync(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                setStatus("Synced \(result.urls_processed) URLs", tone: .success)
            } catch {
                currentFlowState = .idle
                currentBusyAction = nil
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
        currentFlowState = .syncing
        currentBusyAction = .refreshBaseline
        setStatus("Resetting workspace and refreshing the GitHub baseline...", tone: .info)
        Task {
            do {
                let response = try helper.resetWorkspace(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                clearCurrentRun()
                isShowingResetConfirmation = false
                try await refresh(allowFallbackBatch: false)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                currentFlowState = .idle
                currentBusyAction = nil
                setStatus(display(error), tone: .error)
            }
        }
    }

    func refreshWorkspaceBaseline() {
        guard canRefreshBaseline else {
            setStatus("Finish or discard the current review results before refreshing the baseline.", tone: .warning)
            return
        }
        currentFlowState = .syncing
        currentBusyAction = .refreshBaseline
        setStatus("Refreshing the GitHub baseline...", tone: .info)
        Task {
            do {
                let response = try helper.refreshWorkspaceBaseline(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                try await refresh(allowFallbackBatch: false)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                currentFlowState = hasAcceptedRecords ? .readyToSync : (hasCurrentRun ? .reviewing : .idle)
                currentBusyAction = nil
                setStatus(display(error), tone: .error)
            }
        }
    }

    func submitURL() {
        guard canRunProtectedActions else {
            setStatus("OpenAI key missing. Save a key to continue.", tone: .warning)
            return
        }
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        currentFlowState = .syncing
        currentBusyAction = .importURL
        setStatus("Importing URL...", tone: .info)
        Task {
            do {
                let result = try helper.submitManualURL(
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
                currentFlowState = .idle
                currentBusyAction = nil
                setStatus(display(error), tone: .error)
            }
        }
    }

    func acceptSelectedRecord() {
        guard let record = selectedRecord else { return }
        Task {
            do {
                _ = try helper.acceptRecord(
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
        isShowingDeleteConfirmation = false
        Task {
            do {
                guard let batchID = currentBatchID else { return }
                if visibleCurrentRecords.count <= 1 {
                    _ = try helper.deleteBatch(
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

                _ = try helper.rejectRecord(
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
        Task {
            do {
                _ = try helper.deleteBatch(
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
        isShowingApplyConfirmation = true
    }

    func confirmApply() {
        guard let batchID = currentBatchID else { return }
        currentFlowState = .syncing
        currentBusyAction = .syncGitHub
        setStatus("Syncing accepted results to GitHub...", tone: .info)
        Task {
            do {
                let result = try helper.applyAcceptedRecords(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                isShowingApplyConfirmation = false
                clearCurrentRun()
                try await refresh(allowFallbackBatch: false)
                setStatus("Synced to GitHub at \(result.applied_commit_sha)", tone: .success)
            } catch {
                currentFlowState = hasAcceptedRecords ? .readyToSync : .reviewing
                currentBusyAction = nil
                setStatus(display(error), tone: .error)
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

    private func loadBatch(batchID: Int, updateStatusMessage: Bool) async throws {
        let detail = try helper.getBatchDetail(
            batchID: batchID,
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        currentBatchID = batchID
        currentBatchDetail = detail
        syncSelection(with: detail.records.filter { $0.status != "rejected" })
        if detail.accepted_count > 0 {
            currentApplyPreview = try helper.getApplyPreview(
                batchID: batchID,
                openAIKey: savedOpenAIKey,
                openAIModel: savedOpenAIModelSelection.effectiveModel,
                openAIModelSource: savedOpenAIModelSelection.source
            )
        } else {
            currentApplyPreview = nil
        }
        currentFlowState = flowState(for: detail)
        currentBusyAction = nil
        if updateStatusMessage {
            setStatus("Loaded current results", tone: .info)
        }
    }

    private func clearCurrentRun() {
        currentBatchID = nil
        currentBatchDetail = nil
        selectedRecordID = nil
        currentApplyPreview = nil
        currentFlowState = .idle
        currentBusyAction = nil
    }

    private func syncSelection(with records: [ProposedRecord]) {
        if let selectedRecordID, records.contains(where: { $0.id == selectedRecordID }) {
            return
        }
        selectedRecordID = records.first?.id
    }

    private func flowState(for detail: BatchDetailResponse) -> ImporterFlowState {
        if detail.accepted_count > 0 {
            return .readyToSync
        }
        if detail.total_records > 0 {
            return .reviewing
        }
        return .idle
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
