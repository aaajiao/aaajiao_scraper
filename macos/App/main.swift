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

@MainActor
final class AppModel: ObservableObject {
    @Published var manualURL = ""
    @Published var batches: [BatchSummary] = []
    @Published var pendingRecords: [ProposedRecord] = []
    @Published var selectedRecordID: Int?
    @Published var selectedBatchID: Int?
    @Published var applyPreview: ApplyPreview?
    @Published var previewBatchID: Int?
    @Published var pendingApplyBatch: BatchSummary?
    @Published var pendingDeleteBatch: BatchSummary?
    @Published var isShowingApplyConfirmation = false
    @Published var isShowingDeleteConfirmation = false
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

    var selectedRecord: ProposedRecord? {
        pendingRecords.first { $0.id == selectedRecordID }
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

    var visiblePendingRecords: [ProposedRecord] {
        guard let selectedBatchID else { return pendingRecords }
        let filtered = pendingRecords.filter { $0.batch_id == selectedBatchID }
        return filtered.isEmpty ? pendingRecords : filtered
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
                try await refresh()
                if response.status == "initialized" {
                    statusMessage = "Workspace initialized from bundled seed"
                } else if response.status == "seed_version_mismatch" {
                    statusMessage = "Bundled snapshot changed. Reset Workspace only if you want to replace the current local snapshot."
                }
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func refreshFromUI() {
        Task {
            do {
                try await refresh()
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func refresh() async throws {
        let response = try helper.listPendingRecords(
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        settings = response.settings
        batches = response.batches
        pendingRecords = response.pending_records
        syncDraftWithSavedSettingsIfNeeded()

        if let previewBatchID, !batches.contains(where: { $0.id == previewBatchID }) {
            self.previewBatchID = nil
            applyPreview = nil
        }

        if let selectedBatchID, !batches.contains(where: { $0.id == selectedBatchID }) {
            self.selectedBatchID = nil
        }

        let visibleRecords = visiblePendingRecords
        if let selectedRecordID, visibleRecords.contains(where: { $0.id == selectedRecordID }) {
            self.selectedRecordID = selectedRecordID
        } else {
            self.selectedRecordID = visibleRecords.first?.id ?? pendingRecords.first?.id
        }

        if pendingRecords.isEmpty {
            statusMessage = hasSavedOpenAIKey ? "No pending records" : "OpenAI key missing. Save a key to enable imports."
        } else {
            statusMessage = "Loaded \(pendingRecords.count) review records"
        }
    }

    func startSync() {
        guard canRunProtectedActions else {
            statusMessage = "OpenAI key missing. Save a key to continue."
            return
        }
        Task {
            do {
                let result = try helper.startIncrementalSync(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await refresh()
                statusMessage = "Synced \(result.urls_processed) URLs into batch #\(result.batch_id)"
            } catch {
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
                isShowingResetConfirmation = false
                try await refresh()
                statusMessage = "Workspace reset from bundled seed"
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
        Task {
            do {
                let result = try helper.submitManualURL(
                    trimmed,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                manualURL = ""
                try await refresh()
                statusMessage = "Queued \(result.url) in batch #\(result.batch_id)"
            } catch {
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
                try await refresh()
                statusMessage = "Accepted record #\(record.id)"
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func rejectSelectedRecord() {
        guard let record = selectedRecord else { return }
        Task {
            do {
                _ = try helper.rejectRecord(
                    id: record.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await refresh()
                statusMessage = "Rejected record #\(record.id)"
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func loadApplyPreview(for batch: BatchSummary) {
        Task {
            do {
                let preview = try helper.getApplyPreview(
                    batchID: batch.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                previewBatchID = batch.id
                applyPreview = preview
                statusMessage = preview.error_message.isEmpty ? "Preview ready for batch #\(batch.id)" : preview.error_message
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func focusBatch(_ batch: BatchSummary) {
        selectedBatchID = batch.id
        if let firstRecord = pendingRecords.first(where: { $0.batch_id == batch.id }) {
            selectedRecordID = firstRecord.id
            let reviewCount = pendingRecords.filter { $0.batch_id == batch.id }.count
            statusMessage = "Showing \(reviewCount) review records for batch #\(batch.id)"
        } else {
            statusMessage = "Batch #\(batch.id) has no review records."
        }
    }

    func clearBatchFilter() {
        selectedBatchID = nil
        if let selectedRecordID, pendingRecords.contains(where: { $0.id == selectedRecordID }) {
            self.selectedRecordID = selectedRecordID
        } else {
            selectedRecordID = pendingRecords.first?.id
        }
        statusMessage = pendingRecords.isEmpty ? "No pending records" : "Showing all review records"
    }

    func requestApply(batch: BatchSummary) {
        guard canRunProtectedActions else {
            statusMessage = "OpenAI key missing. Save a key to continue."
            return
        }
        pendingApplyBatch = batch
        isShowingApplyConfirmation = true
    }

    func requestDelete(batch: BatchSummary) {
        pendingDeleteBatch = batch
        isShowingDeleteConfirmation = true
    }

    func confirmApply() {
        guard let batch = pendingApplyBatch else { return }
        Task {
            do {
                let result = try helper.applyAcceptedRecords(
                    batchID: batch.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                isShowingApplyConfirmation = false
                pendingApplyBatch = nil
                applyPreview = result.preview
                previewBatchID = result.batch_id
                try await refresh()
                statusMessage = "Applied batch #\(result.batch_id) at \(result.applied_commit_sha)"
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func confirmDelete() {
        guard let batch = pendingDeleteBatch else { return }
        Task {
            do {
                let result = try helper.deleteBatch(
                    batchID: batch.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                isShowingDeleteConfirmation = false
                pendingDeleteBatch = nil
                if previewBatchID == result.batch_id {
                    previewBatchID = nil
                    applyPreview = nil
                }
                if selectedBatchID == result.batch_id {
                    selectedBatchID = nil
                }
                try await refresh()
                statusMessage = "Deleted batch #\(result.batch_id) and \(result.deleted_records) record(s)"
            } catch {
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
            ImportActionsView()
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
            Divider()
            NavigationSplitView {
                ReviewSidebarView()
            } detail: {
                DetailWorkspaceView()
            }
            .navigationSplitViewStyle(.balanced)
            Divider()
            WorkspaceFooterView()
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
        }
        .frame(width: 960, height: 720)
        .onAppear { model.bootstrapIfNeeded() }
        .alert("Apply accepted records and push to git?", isPresented: $model.isShowingApplyConfirmation) {
            Button("Cancel", role: .cancel) {
                model.pendingApplyBatch = nil
            }
            Button("Apply", role: .destructive) {
                model.confirmApply()
            }
        } message: {
            if let batch = model.pendingApplyBatch {
                Text("Batch #\(batch.id) will update aaajiao_works.json and aaajiao_portfolio.md, then commit and push.")
            }
        }
        .alert("Delete batch from local activity?", isPresented: $model.isShowingDeleteConfirmation) {
            Button("Cancel", role: .cancel) {
                model.pendingDeleteBatch = nil
            }
            Button("Delete", role: .destructive) {
                model.confirmDelete()
            }
        } message: {
            if let batch = model.pendingDeleteBatch {
                Text("Batch #\(batch.id) and all of its imported records will be removed from the local importer activity. This does not change the repository.")
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
                    .font(.title3.weight(.semibold))
                Text("Review imported portfolio records, then explicitly apply accepted changes.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 8) {
                HStack(spacing: 8) {
                    Button("Refresh") {
                        model.refreshFromUI()
                    }
                    .keyboardShortcut("r", modifiers: [.command])
                }

                Text(model.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: 260, alignment: .trailing)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
    }
}

private struct ImportActionsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                SummaryTile(
                    title: "OpenAI",
                    value: model.hasSavedOpenAIKey ? "Configured" : "Missing",
                    systemImage: model.hasSavedOpenAIKey ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                    tint: model.hasSavedOpenAIKey ? .green : .orange
                )
                SummaryTile(
                    title: "Model",
                    value: model.effectiveOpenAIModel,
                    systemImage: "cpu",
                    tint: .secondary
                )
                SummaryTile(
                    title: "Queue",
                    value: "\(model.pendingRecords.count) records",
                    systemImage: "tray.full",
                    tint: model.pendingRecords.isEmpty ? .secondary : .blue
                )
                SummaryTile(
                    title: "Workspace",
                    value: workspaceLabel(model.settings.workspace_status),
                    systemImage: "externaldrive",
                    tint: model.settings.workspace_status == "seed_version_mismatch" ? .orange : .secondary
                )
            }

            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Button("Start Sync") { model.startSync() }
                        .buttonStyle(.borderedProminent)
                        .disabled(!model.canRunProtectedActions)

                    TextField("Paste an eventstructure.com artwork URL", text: $model.manualURL)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {
                            model.submitURL()
                        }

                    Button("Import URL") { model.submitURL() }
                        .disabled(!model.canRunProtectedActions || model.manualURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                Text("Current model: \(model.effectiveOpenAIModel) (\(openAIModelSourceLabel(model.effectiveOpenAIModelSource)))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                if let workspaceStatus = model.settings.workspace_status, workspaceStatus == "seed_version_mismatch" {
                    Text("Bundled snapshot changed. Reset Workspace only if you want to replace the current local snapshot with the app's latest bundled copy.")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }

                if !model.hasSavedOpenAIKey {
                    Text("Imports and apply actions are disabled until an OpenAI key is saved below.")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
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

private struct ReviewSidebarView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Group {
            if model.visiblePendingRecords.isEmpty {
                ContentUnavailablePanel(
                    title: "No review records",
                    message: model.hasSavedOpenAIKey ? "Run a sync or import a URL to populate the review queue." : "Save an OpenAI key in Settings to enable imports."
                )
            } else {
                VStack(spacing: 0) {
                    if let selectedBatchID = model.selectedBatchID {
                        HStack(spacing: 8) {
                            Text("Filtered to batch #\(selectedBatchID)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Button("Show All") {
                                model.clearBatchFilter()
                            }
                            .buttonStyle(.link)
                        }
                        .padding(.horizontal, 12)
                        .padding(.top, 10)
                    }

                    List(selection: $model.selectedRecordID) {
                        Section(queueSectionTitle) {
                            ForEach(model.visiblePendingRecords) { record in
                                ReviewRow(record: record)
                                    .tag(record.id)
                            }
                        }
                    }
                    .listStyle(.sidebar)
                }
            }
        }
        .frame(minWidth: 280)
    }

    private var queueSectionTitle: String {
        if let selectedBatchID = model.selectedBatchID {
            return "Review Queue · Batch #\(selectedBatchID)"
        }
        return "Review Queue"
    }
}

private struct DetailWorkspaceView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                if let record = model.selectedRecord {
                    RecordDetailCard(record: record)
                } else {
                    ContentUnavailablePanel(
                        title: "No record selected",
                        message: "Choose a record from the sidebar to inspect its proposed fields."
                    )
                }

                BatchActivityCard()
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct RecordDetailCard: View {
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

            QuickFactsGrid(record: record)
            RecordActionsRow(record: record)

            Form {
                Section("Metadata") {
                    DetailContentRow(label: "URL", value: record.url)
                    DetailContentRow(label: "Year", value: record.year)
                    DetailContentRow(label: "Type", value: record.type)
                    DetailContentRow(label: "Materials", value: record.materials)
                    DetailContentRow(label: "Size", value: record.size)
                    DetailContentRow(label: "Duration", value: record.duration)
                    DetailContentRow(label: "Credits", value: record.credits)
                    DetailContentRow(label: "Mode", value: record.is_update ? "Update" : "New record")
                }

                if !record.description_en.isEmpty {
                    Section("Description EN") {
                        Text(record.description_en)
                            .textSelection(.enabled)
                    }
                }

                if !record.description_cn.isEmpty {
                    Section("Description CN") {
                        Text(record.description_cn)
                            .textSelection(.enabled)
                    }
                }

                if let errorMessage = record.error_message, !errorMessage.isEmpty {
                    Section("Validation Note") {
                        Text(errorMessage)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
            }

            HStack(spacing: 10) {
                Button("Accept") { model.acceptSelectedRecord() }
                    .buttonStyle(.borderedProminent)
                    .disabled(record.status == "accepted")
                Button("Reject") { model.rejectSelectedRecord() }
                    .disabled(record.status == "rejected")
            }
        }
    }
}

private struct BatchActivityCard: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Batch Activity")
                .font(.headline)
            Text("Open Queue shows this batch's records for accept/reject. Apply Check shows what would be written if you apply accepted records.")
                .font(.caption)
                .foregroundStyle(.secondary)

            if model.batches.isEmpty {
                ContentUnavailablePanel(
                    title: "No batches yet",
                    message: "Run a sync or import a URL to create a batch."
                )
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(model.batches) { batch in
                        let reviewCount = model.pendingRecords.filter { $0.batch_id == batch.id }.count

                        VStack(alignment: .leading, spacing: 10) {
                            HStack(alignment: .top, spacing: 12) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("#\(batch.id) \(batch.mode.capitalized)")
                                        .font(.body.weight(.semibold))
                                    Text("\(batch.status) · accepted \(batch.accepted_records) · ready \(batch.ready_records) · total \(batch.total_records)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    if reviewCount > 0 {
                                        Text("\(reviewCount) review record\(reviewCount == 1 ? "" : "s") available")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                    if !batch.last_error.isEmpty {
                                        Text(batch.last_error)
                                            .font(.caption)
                                            .foregroundStyle(.orange)
                                            .lineLimit(2)
                                    }
                                }
                                Spacer()
                                HStack(spacing: 8) {
                                    Button("Open Queue") { model.focusBatch(batch) }
                                        .disabled(reviewCount == 0)
                                    Button("Apply Check") { model.loadApplyPreview(for: batch) }
                                    Button("Delete", role: .destructive) { model.requestDelete(batch: batch) }
                                }
                            }
                        }
                        .padding(12)
                        .background(
                            Color(nsColor: .controlBackgroundColor),
                            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                        )
                    }
                }
            }

            if let preview = model.applyPreview, let batch = model.batches.first(where: { $0.id == preview.batch_id }) {
                Form {
                    Section("Apply Preview") {
                        DetailContentRow(label: "Batch", value: "#\(preview.batch_id)")
                        DetailContentRow(label: "Accepted", value: "\(preview.accepted_count)")
                        DetailContentRow(label: "New", value: "\(preview.new_count)")
                        DetailContentRow(label: "Updated", value: "\(preview.updated_count)")
                        DetailContentRow(label: "Will Push", value: preview.will_push ? "Yes" : "No")
                    }

                    Section("Target Files") {
                        ForEach(preview.target_files, id: \.self) { file in
                            Text(file)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }

                    if !preview.error_message.isEmpty {
                        Section("Preview Note") {
                            Text(preview.error_message)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }

                    Section {
                        Button("Apply Accepted Records") { model.requestApply(batch: batch) }
                            .buttonStyle(.borderedProminent)
                            .disabled(!model.canRunProtectedActions || !preview.will_push || preview.accepted_count == 0)
                    }
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
                Text("The importer runs against a local workspace snapshot until you explicitly apply accepted records.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Quit") {
                model.quitApplication()
            }
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

private struct SummaryTile: View {
    let title: String
    let value: String
    let systemImage: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: systemImage)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

private struct ReviewRow: View {
    let record: ProposedRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(record.displayTitle)
                .font(.body.weight(.medium))
                .lineLimit(2)
            Text("\(record.status) · \(record.page_type) · \(String(format: "%.2f", record.confidence))")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(record.url)
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .lineLimit(2)
        }
        .padding(.vertical, 3)
    }
}

private struct ContentUnavailablePanel: View {
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 8) {
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
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(32)
    }
}

private struct QuickFactsGrid: View {
    let record: ProposedRecord

    var body: some View {
        HStack(spacing: 12) {
            FactChip(label: "Status", value: record.status)
            FactChip(label: "Batch", value: "#\(record.batch_id)")
            FactChip(label: "Confidence", value: String(format: "%.2f", record.confidence))
        }
    }
}

private struct RecordActionsRow: View {
    let record: ProposedRecord

    var body: some View {
        HStack(spacing: 10) {
            if let url = URL(string: record.url), !record.url.isEmpty {
                Link("Open Source Page", destination: url)
            }
            Button("Copy URL") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(record.url, forType: .string)
            }
            .disabled(record.url.isEmpty)
        }
        .font(.callout)
    }
}

private struct FactChip: View {
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
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
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
            Button("Refresh") {
                model.refreshFromUI()
            }
            .keyboardShortcut("r", modifiers: [.command])

            Button("Start Sync") {
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
