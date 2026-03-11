import AppKit
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var manualURL = ""
    @Published var openAIKey = ""
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

    private let helper = HelperClient()

    init() {
        openAIKey = KeychainStore.load()
    }

    var selectedRecord: ProposedRecord? {
        pendingRecords.first { $0.id == selectedRecordID }
    }

    func bootstrapAndRefresh() {
        Task {
            do {
                try saveKeyIfNeeded()
                let response = try helper.bootstrapWorkspace(openAIKey: openAIKey)
                settings = response.settings
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

    func refresh() async throws {
        let response = try helper.listPendingRecords(openAIKey: openAIKey)
        settings = response.settings
        batches = response.batches
        pendingRecords = response.pending_records

        if let selectedRecordID, pendingRecords.contains(where: { $0.id == selectedRecordID }) {
            self.selectedRecordID = selectedRecordID
        } else {
            selectedRecordID = pendingRecords.first?.id
        }

        if let previewBatchID, !batches.contains(where: { $0.id == previewBatchID }) {
            self.previewBatchID = nil
            applyPreview = nil
        }

        statusMessage = pendingRecords.isEmpty ? "No pending records" : "Loaded \(pendingRecords.count) review records"
    }

    func startSync() {
        Task {
            do {
                try saveKeyIfNeeded()
                let result = try helper.startIncrementalSync(openAIKey: openAIKey)
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
                let response = try helper.resetWorkspace(openAIKey: openAIKey)
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
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        Task {
            do {
                try saveKeyIfNeeded()
                let result = try helper.submitManualURL(trimmed, openAIKey: openAIKey)
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
                _ = try helper.acceptRecord(id: record.id, openAIKey: openAIKey)
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
                _ = try helper.rejectRecord(id: record.id, openAIKey: openAIKey)
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
                let preview = try helper.getApplyPreview(batchID: batch.id, openAIKey: openAIKey)
                previewBatchID = batch.id
                applyPreview = preview
                statusMessage = preview.error_message.isEmpty ? "Preview ready for batch #\(batch.id)" : preview.error_message
            } catch {
                statusMessage = display(error)
            }
        }
    }

    func requestApply(batch: BatchSummary) {
        pendingApplyBatch = batch
        isShowingApplyConfirmation = true
    }

    func confirmApply() {
        guard let batch = pendingApplyBatch else { return }
        Task {
            do {
                let result = try helper.applyAcceptedRecords(batchID: batch.id, openAIKey: openAIKey)
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

    private func saveKeyIfNeeded() throws {
        if openAIKey.isEmpty {
            return
        }
        try KeychainStore.save(openAIKey)
    }

    private func display(_ error: Error) -> String {
        error.localizedDescription
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Aaajiao Importer")
                .font(.headline)

            SecureField("OpenAI API Key", text: $model.openAIKey)
                .textFieldStyle(.roundedBorder)

            HStack {
                Button("Start Sync") { model.startSync() }
                Button("Reset Workspace") { model.requestWorkspaceReset() }
                Button("Refresh") {
                    Task {
                        do {
                            try await model.refresh()
                        } catch {
                            model.statusMessage = error.localizedDescription
                        }
                    }
                }
            }

            HStack {
                TextField("Manual URL", text: $model.manualURL)
                    .textFieldStyle(.roundedBorder)
                Button("Import") { model.submitURL() }
            }

            if !model.settings.workspace_path.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.settings.workspace_path)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                    Text(model.settings.has_openai_key ? "OpenAI key available" : "OpenAI key missing")
                        .font(.caption2)
                        .foregroundColor(model.settings.has_openai_key ? .secondary : .orange)
                    if let workspaceStatus = model.settings.workspace_status, workspaceStatus == "seed_version_mismatch" {
                        Text("Workspace seed differs from bundle seed")
                            .font(.caption2)
                            .foregroundColor(.orange)
                    }
                }
            }

            Text(model.statusMessage)
                .font(.caption)

            Divider()

            HStack(alignment: .top, spacing: 12) {
                GroupBox("Review Queue") {
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
                    .frame(minWidth: 220, minHeight: 260)
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
                        Text("Select a record to inspect its proposed fields.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 260)
            }

            Divider()

            GroupBox("Batches") {
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

            if let preview = model.applyPreview, let batch = model.batches.first(where: { $0.id == preview.batch_id }) {
                Divider()

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
                        }

                        if !preview.error_message.isEmpty {
                            Text(preview.error_message)
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }

                        Button("Apply Accepted Records") { model.requestApply(batch: batch) }
                            .disabled(!preview.will_push || preview.accepted_count == 0)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(14)
        .frame(width: 640)
        .onAppear { model.bootstrapAndRefresh() }
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

@main
struct AaajiaoImporterApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra("Aaajiao Importer", systemImage: "tray.full") {
            ContentView()
                .environmentObject(model)
        }
    }
}
