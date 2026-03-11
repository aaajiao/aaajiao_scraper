import AppKit
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var manualURL = ""
    @Published var batches: [BatchSummary] = []
    @Published var pendingRecords: [ProposedRecord] = []
    @Published var selectedRecordID: Int?
    @Published var applyPreview: ApplyPreview?
    @Published var previewBatchID: Int?
    @Published var pendingApplyBatch: BatchSummary?
    @Published var isShowingApplyConfirmation = false
    @Published var isShowingResetConfirmation = false
    @Published var statusMessage = "Ready"
    @Published var settings = AppSettings.empty
    @Published var settingsDraftOpenAIKey = ""
    @Published var settingsStatusMessage = ""

    private let helper = HelperClient()
    private var hasBootstrapped = false

    init() {
        let savedKey = KeychainStore.load()
        settingsDraftOpenAIKey = savedKey
    }

    var selectedRecord: ProposedRecord? {
        pendingRecords.first { $0.id == selectedRecordID }
    }

    var savedOpenAIKey: String {
        KeychainStore.load()
    }

    var hasSavedOpenAIKey: Bool {
        !savedOpenAIKey.isEmpty
    }

    var trimmedDraftOpenAIKey: String {
        settingsDraftOpenAIKey.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var isSettingsDirty: Bool {
        trimmedDraftOpenAIKey != savedOpenAIKey
    }

    var canRunProtectedActions: Bool {
        hasSavedOpenAIKey
    }

    func bootstrapIfNeeded() {
        guard !hasBootstrapped else { return }
        hasBootstrapped = true
        bootstrapAndRefresh()
    }

    func bootstrapAndRefresh() {
        Task {
            do {
                let response = try helper.bootstrapWorkspace(openAIKey: savedOpenAIKey)
                settings = response.settings
                syncDraftWithSavedKeyIfNeeded()
                try await refresh()
                if response.status == "initialized" {
                    statusMessage = "Workspace initialized from bundled seed"
                } else if response.status == "seed_version_mismatch" {
                    statusMessage = "Workspace seed differs from bundled seed. Manual reset required."
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
        let response = try helper.listPendingRecords(openAIKey: savedOpenAIKey)
        settings = response.settings
        batches = response.batches
        pendingRecords = response.pending_records
        syncDraftWithSavedKeyIfNeeded()

        if let selectedRecordID, pendingRecords.contains(where: { $0.id == selectedRecordID }) {
            self.selectedRecordID = selectedRecordID
        } else {
            selectedRecordID = pendingRecords.first?.id
        }

        if let previewBatchID, !batches.contains(where: { $0.id == previewBatchID }) {
            self.previewBatchID = nil
            applyPreview = nil
        }

        if pendingRecords.isEmpty {
            statusMessage = hasSavedOpenAIKey ? "No pending records" : "OpenAI key missing. Configure Settings to enable imports."
        } else {
            statusMessage = "Loaded \(pendingRecords.count) review records"
        }
    }

    func startSync() {
        guard canRunProtectedActions else {
            statusMessage = "OpenAI key missing. Open Settings to continue."
            return
        }
        Task {
            do {
                let result = try helper.startIncrementalSync(openAIKey: savedOpenAIKey)
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
                let response = try helper.resetWorkspace(openAIKey: savedOpenAIKey)
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
            statusMessage = "OpenAI key missing. Open Settings to continue."
            return
        }
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        Task {
            do {
                let result = try helper.submitManualURL(trimmed, openAIKey: savedOpenAIKey)
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
                _ = try helper.acceptRecord(id: record.id, openAIKey: savedOpenAIKey)
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
                _ = try helper.rejectRecord(id: record.id, openAIKey: savedOpenAIKey)
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
                let preview = try helper.getApplyPreview(batchID: batch.id, openAIKey: savedOpenAIKey)
                previewBatchID = batch.id
                applyPreview = preview
                statusMessage = preview.error_message.isEmpty ? "Preview ready for batch #\(batch.id)" : preview.error_message
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func requestApply(batch: BatchSummary) {
        guard canRunProtectedActions else {
            statusMessage = "OpenAI key missing. Open Settings to continue."
            return
        }
        pendingApplyBatch = batch
        isShowingApplyConfirmation = true
    }

    func confirmApply() {
        guard let batch = pendingApplyBatch else { return }
        Task {
            do {
                let result = try helper.applyAcceptedRecords(batchID: batch.id, openAIKey: savedOpenAIKey)
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

    func saveSettings() {
        let newValue = trimmedDraftOpenAIKey
        do {
            if newValue.isEmpty {
                try KeychainStore.delete()
            } else {
                try KeychainStore.save(newValue)
            }
            settingsDraftOpenAIKey = newValue
            settingsStatusMessage = newValue.isEmpty ? "OpenAI key cleared from macOS Keychain." : "OpenAI key saved to macOS Keychain."
            refreshFromUI()
        } catch {
            settingsStatusMessage = display(error)
        }
    }

    func revertSettings() {
        settingsDraftOpenAIKey = savedOpenAIKey
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

    func openSettings() {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }

    func quitApplication() {
        NSApplication.shared.terminate(nil)
    }

    private func syncDraftWithSavedKeyIfNeeded() {
        guard !isSettingsDirty else { return }
        settingsDraftOpenAIKey = savedOpenAIKey
    }

    private func display(_ error: Error) -> String {
        error.localizedDescription
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HeaderView()
            StatusSummaryView()
            PrimaryActionsView()
            ReviewSectionView()
            BatchesSectionView()
            FooterCommandsView()
        }
        .padding(14)
        .frame(width: 680)
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

private struct HeaderView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Aaajiao Importer")
                    .font(.headline)
                Text("Local review workspace for portfolio imports")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(model.statusMessage)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: 220, alignment: .trailing)
        }
    }
}

private struct StatusSummaryView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        GroupBox("Status") {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 16) {
                    StatusBadge(
                        title: "OpenAI",
                        value: model.hasSavedOpenAIKey ? "Configured" : "Missing",
                        tint: model.hasSavedOpenAIKey ? .green : .orange
                    )
                    StatusBadge(
                        title: "Review Queue",
                        value: "\(model.pendingRecords.count) pending",
                        tint: model.pendingRecords.isEmpty ? .secondary : .blue
                    )
                    StatusBadge(
                        title: "Workspace",
                        value: workspaceLabel(model.settings.workspace_status),
                        tint: model.settings.workspace_status == "seed_version_mismatch" ? .orange : .secondary
                    )
                }

                if !model.settings.workspace_path.isEmpty {
                    Text(model.settings.workspace_path)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }

                if let workspaceStatus = model.settings.workspace_status, workspaceStatus == "seed_version_mismatch" {
                    Text("Workspace seed differs from the bundled seed. Reset the workspace if you want to realign the local snapshot.")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }

                if !model.hasSavedOpenAIKey {
                    HStack {
                        Text("Imports and apply actions are disabled until an OpenAI key is saved.")
                            .font(.caption2)
                            .foregroundStyle(.orange)
                        Spacer()
                        Button("Open Settings") {
                            model.openSettings()
                        }
                    }
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
            return "Seed mismatch"
        case "missing":
            return "Missing"
        default:
            return "Unknown"
        }
    }
}

private struct PrimaryActionsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        GroupBox("Actions") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button("Start Sync") { model.startSync() }
                        .disabled(!model.canRunProtectedActions)
                    Button("Refresh") { model.refreshFromUI() }
                    Button("Reset Workspace") { model.requestWorkspaceReset() }
                }

                HStack {
                    TextField("Manual URL", text: $model.manualURL)
                        .textFieldStyle(.roundedBorder)
                    Button("Import URL") { model.submitURL() }
                        .disabled(!model.canRunProtectedActions || model.manualURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}

private struct ReviewSectionView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            GroupBox("Review Queue") {
                if model.pendingRecords.isEmpty {
                    EmptyStateView(
                        title: "No records pending review",
                        message: model.hasSavedOpenAIKey ? "Run a sync or import a manual URL to create review items." : "Save an OpenAI key in Settings to enable imports."
                    )
                } else {
                    List(model.pendingRecords, selection: $model.selectedRecordID) { record in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(record.displayTitle)
                                .font(.headline)
                                .lineLimit(2)
                            Text("\(record.status) · \(record.page_type) · \(String(format: "%.2f", record.confidence))")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(record.url)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        .padding(.vertical, 4)
                    }
                    .frame(minWidth: 240, minHeight: 280)
                }
            }

            GroupBox("Record Detail") {
                if let record = model.selectedRecord {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(record.displayTitle)
                                .font(.headline)
                            if !record.title_cn.isEmpty {
                                Text(record.title_cn)
                                    .font(.subheadline)
                            }

                            DetailLine(label: "Status", value: record.status)
                            DetailLine(label: "Batch", value: "#\(record.batch_id)")
                            DetailLine(label: "Confidence", value: String(format: "%.2f", record.confidence))
                            DetailLine(label: "URL", value: record.url)
                            DetailLine(label: "Year", value: record.year)
                            DetailLine(label: "Type", value: record.type)
                            DetailLine(label: "Materials", value: record.materials)
                            DetailLine(label: "Size", value: record.size)
                            DetailLine(label: "Duration", value: record.duration)
                            DetailLine(label: "Credits", value: record.credits)
                            DetailLine(label: "Mode", value: record.is_update ? "Update" : "New record")

                            if !record.description_en.isEmpty {
                                DetailBlock(label: "Description EN", value: record.description_en)
                            }
                            if !record.description_cn.isEmpty {
                                DetailBlock(label: "Description CN", value: record.description_cn)
                            }
                            if let errorMessage = record.error_message, !errorMessage.isEmpty {
                                DetailBlock(label: "Validation Note", value: errorMessage)
                            }

                            HStack {
                                Button("Accept") { model.acceptSelectedRecord() }
                                    .disabled(record.status == "accepted")
                                Button("Reject") { model.rejectSelectedRecord() }
                                    .disabled(record.status == "rejected")
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                } else {
                    EmptyStateView(
                        title: "No record selected",
                        message: "Select a record to inspect its proposed fields."
                    )
                }
            }
            .frame(maxWidth: .infinity, minHeight: 280)
        }
    }
}

private struct BatchesSectionView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            GroupBox("Batches") {
                if model.batches.isEmpty {
                    EmptyStateView(
                        title: "No batches yet",
                        message: "Run a sync or import a URL to create a batch."
                    )
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(model.batches) { batch in
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("#\(batch.id) \(batch.mode)")
                                        .font(.headline)
                                    Text("\(batch.status) · accepted \(batch.accepted_records) / ready \(batch.ready_records) / total \(batch.total_records)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                    if !batch.last_error.isEmpty {
                                        Text(batch.last_error)
                                            .font(.caption2)
                                            .foregroundStyle(.orange)
                                            .lineLimit(2)
                                    }
                                }
                                Spacer()
                                Button("Preview") { model.loadApplyPreview(for: batch) }
                                    .disabled(batch.accepted_records == 0)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            if let preview = model.applyPreview, let batch = model.batches.first(where: { $0.id == preview.batch_id }) {
                GroupBox("Apply Preview") {
                    VStack(alignment: .leading, spacing: 8) {
                        DetailLine(label: "Batch", value: "#\(preview.batch_id)")
                        DetailLine(label: "Accepted", value: "\(preview.accepted_count)")
                        DetailLine(label: "New", value: "\(preview.new_count)")
                        DetailLine(label: "Updated", value: "\(preview.updated_count)")
                        DetailLine(label: "Will Push", value: preview.will_push ? "Yes" : "No")

                        ForEach(preview.target_files, id: \.self) { file in
                            Text(file)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }

                        if !preview.error_message.isEmpty {
                            Text(preview.error_message)
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }

                        Button("Apply Accepted Records") { model.requestApply(batch: batch) }
                            .disabled(!model.canRunProtectedActions || !preview.will_push || preview.accepted_count == 0)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }
}

private struct FooterCommandsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Divider()
        HStack {
            Button("Settings…") {
                model.openSettings()
            }
            Spacer()
            Button("Quit Aaajiao Importer") {
                model.quitApplication()
            }
        }
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Form {
            Section("OpenAI") {
                SecureField("OpenAI API Key", text: $model.settingsDraftOpenAIKey)
                    .textFieldStyle(.roundedBorder)
                Text("The key is stored only in your macOS Keychain and is injected into the bundled Python helper at runtime.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                HStack {
                    Button("Save") {
                        model.saveSettings()
                    }
                    .keyboardShortcut("s", modifiers: [.command])
                    .disabled(!model.isSettingsDirty)

                    Button("Revert") {
                        model.revertSettings()
                    }
                    .disabled(!model.isSettingsDirty)

                    Button("Clear Saved Key", role: .destructive) {
                        model.clearSavedKey()
                    }
                    .disabled(!model.hasSavedOpenAIKey && model.trimmedDraftOpenAIKey.isEmpty)
                }

                if !model.settingsStatusMessage.isEmpty {
                    Text(model.settingsStatusMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .padding(20)
        .frame(width: 460)
    }
}

private struct StatusBadge: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.callout.weight(.semibold))
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct EmptyStateView: View {
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 6) {
            Text(title)
                .font(.callout.weight(.semibold))
            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.vertical, 24)
    }
}

private struct DetailLine: View {
    let label: String
    let value: String

    var body: some View {
        if !value.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.caption)
                    .textSelection(.enabled)
            }
        }
    }
}

private struct DetailBlock: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
                .textSelection(.enabled)
        }
    }
}

private struct AppCommands: Commands {
    @ObservedObject var model: AppModel

    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") {
                model.openSettings()
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
            Button("Quit Aaajiao Importer") {
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
        MenuBarExtra("Aaajiao Importer", systemImage: "tray.full") {
            ContentView()
                .environmentObject(model)
        }

        Settings {
            SettingsView()
                .environmentObject(model)
        }

        .commands {
            AppCommands(model: model)
        }
    }
}
