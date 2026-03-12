import AppKit
import Foundation
import SwiftUI

private let settingsWindowID = "settings"
private let importerWindowID = "importer"

private func presentSettingsWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.async {
        openWindow(id: settingsWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

private func presentImporterWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.async {
        openWindow(id: importerWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

private func closeSettingsWindow() {
    if let settingsWindow = NSApp.windows.first(where: { $0.title == "Settings" }) {
        settingsWindow.performClose(nil)
        return
    }
    NSApp.keyWindow?.performClose(nil)
}

private func openAIModelSourceLabel(_ source: String) -> String {
    switch source {
    case "custom":
        return "custom"
    case "preset":
        return "preset"
    default:
        return "default"
    }
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
    @Published var statusMessage = "Ready"
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
                if response.status == "initialized" {
                    statusMessage = "Workspace initialized"
                } else if response.status == "seed_version_mismatch" {
                    statusMessage = "Workspace snapshot differs from the bundled seed"
                }
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func refreshFromUI() {
        Task {
            do {
                try await refresh(allowFallbackBatch: currentBatchID == nil)
            } catch {
                statusMessage = display(error)
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
                statusMessage = "Loaded the latest review results"
                return
            } catch {
                clearCurrentRun()
            }
        }

        if !hasSavedOpenAIKey {
            currentFlowState = .idle
            statusMessage = "OpenAI key missing. Save a key to enable imports."
        } else {
            currentFlowState = .idle
            statusMessage = "Ready for a new import"
        }
    }

    func startSync() {
        guard canRunProtectedActions else {
            statusMessage = "OpenAI key missing. Save a key to continue."
            return
        }
        currentFlowState = .syncing
        currentBusyAction = .syncSite
        statusMessage = "Syncing entire site..."
        Task {
            do {
                let result = try helper.startIncrementalSync(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                statusMessage = "Synced \(result.urls_processed) URLs"
            } catch {
                currentFlowState = .idle
                currentBusyAction = nil
                statusMessage = display(error)
            }
        }
    }

    func requestWorkspaceReset() {
        isShowingResetConfirmation = true
    }

    func confirmWorkspaceReset() {
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
                statusMessage = "Workspace reset"
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func submitURL() {
        guard canRunProtectedActions else {
            statusMessage = "OpenAI key missing. Save a key to continue."
            return
        }
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        currentFlowState = .syncing
        currentBusyAction = .importURL
        statusMessage = "Importing URL..."
        Task {
            do {
                let result = try helper.submitManualURL(
                    trimmed,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                manualURL = ""
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                statusMessage = "Imported \(result.url)"
            } catch {
                currentFlowState = .idle
                currentBusyAction = nil
                statusMessage = display(error)
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
                statusMessage = "Accepted \(record.displayTitle)"
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func deleteSelectedRecord() {
        guard let record = selectedRecord else { return }
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
                    statusMessage = "Discarded current results"
                    return
                }

                _ = try helper.rejectRecord(
                    id: record.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await loadBatch(batchID: batchID, updateStatusMessage: false)
                statusMessage = "Deleted \(record.displayTitle)"
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func discardCurrentRun() {
        guard let batchID = currentBatchID else { return }
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
                statusMessage = "Discarded current results"
            } catch {
                statusMessage = display(error)
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
        statusMessage = "Syncing accepted results to GitHub..."
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
                statusMessage = "Synced to GitHub at \(result.applied_commit_sha)"
            } catch {
                currentFlowState = hasAcceptedRecords ? .readyToSync : .reviewing
                currentBusyAction = nil
                statusMessage = display(error)
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
            statusMessage = "Loaded current results"
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
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            WindowHeaderView()
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    StatusOverviewSection()
                    ImportURLSection()
                    SyncSiteSection()
                    ReviewResultsSection()
                    if model.hasAcceptedRecords {
                        GitHubSyncSection()
                    }
                }
                .padding(24)
            }
            Divider()
            WorkspaceFooterView()
                .padding(.horizontal, 24)
                .padding(.vertical, 14)
        }
        .frame(width: 980, height: 760)
        .background(Color(nsColor: .windowBackgroundColor))
        .onAppear { model.bootstrapIfNeeded() }
        .alert("Sync accepted results to GitHub?", isPresented: $model.isShowingApplyConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Sync", role: .destructive) {
                model.confirmApply()
            }
        } message: {
            if let preview = model.currentApplyPreview {
                Text("This will sync \(preview.accepted_count) accepted result(s) to GitHub.")
            } else {
                Text("This will sync accepted results to GitHub.")
            }
        }
        .alert("Reset workspace from bundled seed?", isPresented: $model.isShowingResetConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Reset", role: .destructive) {
                model.confirmWorkspaceReset()
            }
        } message: {
            Text("This removes the local importer workspace and recreates it from the bundled seed.")
        }
    }
}

private struct WindowHeaderView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("aaajiao Importer")
                    .font(.system(size: 28, weight: .semibold, design: .rounded))
                Text("Import one URL or sync the site, review the results, then sync accepted changes to GitHub.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(model.statusMessage)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: 260, alignment: .trailing)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 20)
    }
}

private struct StatusOverviewSection: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(spacing: 14) {
            StatusCard(
                title: "OpenAI",
                value: model.hasSavedOpenAIKey ? "Configured" : "Missing",
                detail: model.hasSavedOpenAIKey ? model.effectiveOpenAIModel : "Save your API key in Settings",
                systemImage: model.hasSavedOpenAIKey ? "checkmark.circle.fill" : "key.slash",
                tint: model.hasSavedOpenAIKey ? .green : .orange
            )
            StatusCard(
                title: "Current Run",
                value: model.currentRunTitle,
                detail: model.currentBatchSummary.map { "#\($0.id) \($0.mode == "manual" ? "Manual" : "Sync")" } ?? "No imported results loaded",
                systemImage: "tray.full",
                tint: model.hasCurrentRun ? .blue : .secondary
            )
            StatusCard(
                title: "Review",
                value: model.reviewStatusValue,
                detail: reviewDetail(model.currentBatchDetail),
                systemImage: "checklist",
                tint: model.hasAcceptedRecords ? .green : .secondary
            )
            StatusCard(
                title: "Workspace",
                value: workspaceLabel(model.settings.workspace_status),
                detail: model.settings.workspace_path.isEmpty ? "Unavailable" : "Local workspace ready",
                systemImage: "externaldrive",
                tint: model.settings.workspace_status == "seed_version_mismatch" ? .orange : .secondary
            )
        }
    }

    private func reviewDetail(_ detail: BatchDetailResponse?) -> String {
        guard let detail else { return "Nothing in review" }
        return "\(detail.total_records) total | \(detail.failed_count) failed"
    }

    private func workspaceLabel(_ status: String?) -> String {
        switch status {
        case "ready":
            return "Ready"
        case "seed_version_mismatch":
            return "Snapshot changed"
        case "missing":
            return "Missing"
        default:
            return "Unknown"
        }
    }
}

private struct ImportURLSection: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        SectionCard {
            VStack(alignment: .leading, spacing: 14) {
                Text("Import URL")
                    .font(.title3.weight(.semibold))
                Text("Paste one eventstructure.com artwork URL and import it for review.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                HStack(spacing: 12) {
                    TextField("Paste an artwork URL", text: $model.manualURL)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {
                            model.submitURL()
                        }

                    HStack(spacing: 8) {
                        Button("Import") {
                            model.submitURL()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isBusy || !model.canRunProtectedActions || model.manualURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                        if model.isImportingURL {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                }

                if !model.hasSavedOpenAIKey {
                    HStack(spacing: 10) {
                        Label("OpenAI key required before you can import.", systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.orange)
                        Spacer()
                        Button("Open Settings") {
                            presentSettingsWindow(openWindow)
                        }
                    }
                }
            }
        }
    }
}

private struct SyncSiteSection: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        SectionCard(material: .thinMaterial) {
            HStack(alignment: .center, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Sync Entire Site")
                        .font(.system(size: 24, weight: .semibold, design: .rounded))
                    Text("Run an incremental site sync, review the imported results below, and keep only the entries you accept.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                HStack(spacing: 8) {
                    Button("Sync Entire Site") {
                        model.startSync()
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(model.isBusy || !model.canRunProtectedActions)

                    if model.isSyncingSite {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
            }
        }
    }
}

private struct ReviewResultsSection: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        SectionCard {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Review Results")
                            .font(.title3.weight(.semibold))
                        Text("Check the imported content before accepting it.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if model.hasCurrentRun {
                        Button("Discard Run", role: .destructive) {
                            model.discardCurrentRun()
                        }
                    }
                }

                if let detail = model.currentBatchDetail {
                    RunSummaryStrip(detail: detail)

                    if model.visibleCurrentRecords.isEmpty {
                        EmptyStatePanel(
                            title: "No reviewable results",
                            message: "This run no longer has any visible items. Start a new import or sync."
                        )
                    } else if model.visibleCurrentRecords.count == 1, let record = model.selectedRecord {
                        RecordDetailPanel(record: record)
                    } else {
                        HStack(alignment: .top, spacing: 18) {
                            RecordListPanel()
                                .frame(width: 300)
                            if let record = model.selectedRecord {
                                RecordDetailPanel(record: record)
                            } else {
                                EmptyStatePanel(
                                    title: "Select a result",
                                    message: "Choose an item from the list to inspect its details."
                                )
                            }
                        }
                    }
                } else {
                    EmptyStatePanel(
                        title: "No current results",
                        message: "Import one URL or run a site sync to populate this area."
                    )
                }
            }
        }
    }
}

private struct GitHubSyncSection: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        SectionCard(material: .thinMaterial) {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Sync to GitHub")
                        .font(.title3.weight(.semibold))
                    Text("Only accepted results will be synced.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                if let preview = model.currentApplyPreview {
                    HStack(spacing: 12) {
                        SummaryPill(label: "Accepted", value: "\(preview.accepted_count)")
                        SummaryPill(label: "New", value: "\(preview.new_count)")
                        SummaryPill(label: "Updated", value: "\(preview.updated_count)")
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Target Files")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        ForEach(preview.target_files, id: \.self) { file in
                            Text(file)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }

                    if !preview.error_message.isEmpty {
                        Label(preview.error_message, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }

                    HStack {
                        Spacer()
                        HStack(spacing: 8) {
                            Button("Sync to GitHub") {
                                model.requestApply()
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.large)
                            .disabled(model.isBusy || !model.canRunProtectedActions || !model.canSyncCurrentRun)

                            if model.isSyncingGitHub {
                                ProgressView()
                                    .controlSize(.small)
                            }
                        }
                    }
                } else {
                    ProgressView()
                        .controlSize(.small)
                }
            }
        }
    }
}

private struct WorkspaceFooterView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(model.settings.workspace_path.isEmpty ? "Workspace unavailable" : model.settings.workspace_path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Text("Local review data is temporary and is cleaned up after a successful GitHub sync.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Menu("Workspace") {
                Button("Reset Workspace", role: .destructive) {
                    model.requestWorkspaceReset()
                }
                Divider()
                Button("Quit aaajiao Importer") {
                    model.quitApplication()
                }
            }
        }
    }
}

private struct StatusCard: View {
    let title: String
    let value: String
    let detail: String
    let systemImage: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
                .foregroundStyle(tint)
                .lineLimit(2)
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

private struct SectionCard<Content: View>: View {
    let material: Material
    let content: Content

    init(material: Material = .regularMaterial, @ViewBuilder content: () -> Content) {
        self.material = material
        self.content = content()
    }

    var body: some View {
        content
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(material, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.05), lineWidth: 1)
            )
    }
}

private struct RunSummaryStrip: View {
    let detail: BatchDetailResponse

    var body: some View {
        HStack(spacing: 12) {
            SummaryPill(label: "Mode", value: detail.batch.mode == "manual" ? "Single URL" : "Site Sync")
            SummaryPill(label: "Total", value: "\(detail.total_records)")
            SummaryPill(label: "Accepted", value: "\(detail.accepted_count)")
            SummaryPill(label: "Pending", value: "\(detail.pending_count)")
            SummaryPill(label: "Failed", value: "\(detail.failed_count)")
        }
    }
}

private struct SummaryPill: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.body.weight(.medium))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct RecordListPanel: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(model.visibleCurrentRecords) { record in
                Button {
                    model.selectedRecordID = record.id
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(record.displayTitle)
                                .font(.body.weight(.medium))
                                .foregroundStyle(.primary)
                                .lineLimit(2)
                            Text(statusLabel(record.status))
                                .font(.caption)
                                .foregroundStyle(statusTint(record.status))
                            Text(record.url)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        Spacer(minLength: 0)
                        if model.selectedRecordID == record.id {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.blue)
                        }
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        model.selectedRecordID == record.id ? Color.accentColor.opacity(0.10) : Color(nsColor: .controlBackgroundColor),
                        in: RoundedRectangle(cornerRadius: 14, style: .continuous)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "accepted":
            return "Accepted"
        case "needs_review":
            return "Needs review"
        case "ready_for_review":
            return "Ready for review"
        case "failed":
            return "Failed"
        default:
            return status.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private func statusTint(_ status: String) -> Color {
        switch status {
        case "accepted":
            return .green
        case "failed":
            return .orange
        default:
            return .secondary
        }
    }
}

private struct RecordDetailPanel: View {
    @EnvironmentObject private var model: AppModel
    let record: ProposedRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(record.displayTitle)
                    .font(.title3.weight(.semibold))
                if !record.title_cn.isEmpty {
                    Text(record.title_cn)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 12) {
                SummaryPill(label: "Status", value: statusLabel(record.status))
                SummaryPill(label: "Confidence", value: String(format: "%.2f", record.confidence))
                SummaryPill(label: "Type", value: record.type.isEmpty ? "Unknown" : record.type)
            }

            HStack(spacing: 10) {
                if let url = URL(string: record.url), !record.url.isEmpty {
                    Link("Open Source Page", destination: url)
                }
                Button("Copy URL") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(record.url, forType: .string)
                }
                .disabled(record.url.isEmpty)
                Spacer()
                Button("Delete", role: .destructive) {
                    model.deleteSelectedRecord()
                }
                Button("Accept") {
                    model.acceptSelectedRecord()
                }
                .buttonStyle(.borderedProminent)
                .disabled(record.status == "accepted" || record.status == "failed")
            }

            VStack(alignment: .leading, spacing: 12) {
                DetailContentRow(label: "URL", value: record.url)
                DetailContentRow(label: "Year", value: record.year)
                DetailContentRow(label: "Materials", value: record.materials)
                DetailContentRow(label: "Size", value: record.size)
                DetailContentRow(label: "Duration", value: record.duration)
                DetailContentRow(label: "Credits", value: record.credits)
                DetailContentRow(label: "Video", value: record.video_link)
                DetailContentRow(label: "Mode", value: record.is_update ? "Update" : "New record")
            }

            ImageURLSection(images: record.images)
            ImageURLSection(title: "High-Res Image URLs", emptyMessage: "No high-res image URLs found", images: record.high_res_images)

            if !record.description_en.isEmpty {
                TextBlockSection(title: "Description EN", value: record.description_en)
            }

            if !record.description_cn.isEmpty {
                TextBlockSection(title: "Description CN", value: record.description_cn)
            }

            if let errorMessage = record.error_message, !errorMessage.isEmpty {
                TextBlockSection(title: record.status == "failed" ? "Import Error" : "Validation Note", value: errorMessage, tint: .secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "accepted":
            return "Accepted"
        case "needs_review":
            return "Needs review"
        case "ready_for_review":
            return "Ready for review"
        case "failed":
            return "Failed"
        default:
            return status.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}

private struct ImageURLSection: View {
    var title: String = "Image URLs"
    var emptyMessage: String = "No image URLs found"
    let images: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            if images.isEmpty {
                Text(emptyMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(images.enumerated()), id: \.offset) { index, imageURL in
                        HStack(alignment: .top, spacing: 10) {
                            Text("\(index + 1).")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .frame(width: 18, alignment: .leading)
                            VStack(alignment: .leading, spacing: 6) {
                                Text(imageURL)
                                    .font(.caption)
                                    .textSelection(.enabled)
                                    .foregroundStyle(.primary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                if let url = URL(string: imageURL), !imageURL.isEmpty {
                                    Link("Open Image", destination: url)
                                        .font(.caption)
                                }
                            }
                        }
                        .padding(12)
                        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
            }
        }
    }
}

private struct TextBlockSection: View {
    let title: String
    let value: String
    var tint: Color = .primary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(value)
                .textSelection(.enabled)
                .foregroundStyle(tint)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }
}

private struct DetailContentRow: View {
    let label: String
    let value: String

    var body: some View {
        if !value.isEmpty {
            LabeledContent(label) {
                Text(value)
                    .textSelection(.enabled)
                    .multilineTextAlignment(.trailing)
            }
        }
    }
}

private struct EmptyStatePanel: View {
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "tray")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text(title)
                .font(.headline)
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .padding(24)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("OpenAI") {
                    SecureField("OpenAI API Key", text: $model.settingsDraftOpenAIKey)
                    Picker("Model", selection: $model.settingsDraftOpenAIModelPreset) {
                        ForEach(OpenAIModelPreset.allCases) { preset in
                            Text(preset.displayName).tag(preset)
                        }
                    }
                    if model.settingsDraftOpenAIModelPreset == .custom {
                        TextField("Custom model name", text: $model.settingsDraftCustomOpenAIModel)
                    }
                }

                Section("Current Configuration") {
                    LabeledContent("Effective model") {
                        Text(model.effectiveOpenAIModel)
                    }
                    LabeledContent("Model source") {
                        Text(model.effectiveOpenAIModelSource)
                    }
                    LabeledContent("Workspace") {
                        Text(model.settings.workspace_path.isEmpty ? "Unavailable" : model.settings.workspace_path)
                            .textSelection(.enabled)
                    }
                }

                Section {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("The OpenAI key is stored only in macOS Keychain. The selected model is stored in local app preferences.")
                        if !model.settingsStatusMessage.isEmpty {
                            Text(model.settingsStatusMessage)
                        }
                    }
                }
            }
            .formStyle(.grouped)

            Divider()

            HStack {
                Button("Clear Key", role: .destructive) {
                    model.clearSavedKey()
                }
                .disabled(!model.hasSavedOpenAIKey && model.trimmedDraftOpenAIKey.isEmpty)

                Spacer()

                Button("Revert") {
                    model.revertSettings()
                }
                .disabled(!model.isSettingsDirty)

                Button(model.isSettingsDirty ? "Save" : "Done") {
                    if model.saveSettings() {
                        closeSettingsWindow()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.canSaveSettings)
            }
            .padding(20)
        }
        .frame(width: 520)
    }
}

private struct MenuBarMenuView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button {
                presentImporterWindow(openWindow)
            } label: {
                Label("Open Importer", systemImage: "square.and.arrow.down")
            }

            Button {
                presentSettingsWindow(openWindow)
            } label: {
                Label("Settings…", systemImage: "gearshape")
            }

            Divider()

            Button {
                model.refreshFromUI()
            } label: {
                Label("Reload Results", systemImage: "arrow.clockwise")
            }

            Button {
                model.startSync()
            } label: {
                Label("Sync Entire Site", systemImage: "arrow.trianglehead.2.clockwise")
            }
            .disabled(!model.canRunProtectedActions)

            Divider()

            Button {
                model.quitApplication()
            } label: {
                Label("Quit aaajiao Importer", systemImage: "power")
            }
        }
    }
}

private struct AppCommands: Commands {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") {
                presentSettingsWindow(openWindow)
            }
            .keyboardShortcut(",", modifiers: [.command])
        }

        CommandMenu("Actions") {
            Button("Reload Results") {
                model.refreshFromUI()
            }
            .keyboardShortcut("r", modifiers: [.command])

            Button("Sync Entire Site") {
                model.startSync()
            }
            .keyboardShortcut("i", modifiers: [.command, .shift])
            .disabled(!model.canRunProtectedActions)
        }

        CommandGroup(replacing: .appTermination) {
            Button("Quit aaajiao Importer") {
                model.quitApplication()
            }
            .keyboardShortcut("q", modifiers: [.command])
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
