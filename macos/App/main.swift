import AppKit
import Foundation
import SwiftUI

struct ProposedRecord: Codable, Identifiable {
    let id: Int
    let batch_id: Int
    let url: String
    let slug: String
    let status: String
    let page_type: String
    let confidence: Double
    let is_update: Bool
    let title: String
    let title_cn: String
    let year: String
    let type: String
    let materials: String
    let size: String
    let duration: String
    let credits: String
    let description_en: String
    let description_cn: String
    let error_message: String?
}

struct BatchSummary: Codable, Identifiable {
    let id: Int
    let mode: String
    let status: String
    let total_records: Int
    let accepted_records: Int
    let ready_records: Int
}

struct OverviewResponse: Codable {
    let batches: [BatchSummary]
    let pending_records: [ProposedRecord]
    let workspace: String
}

enum PythonCommandError: Error {
    case missingResources
    case nonZeroExit(String)
    case decodeFailure(String)
}

@MainActor
final class AppModel: ObservableObject {
    @Published var manualURL = ""
    @Published var openAIKey = ""
    @Published var batches: [BatchSummary] = []
    @Published var pendingRecords: [ProposedRecord] = []
    @Published var statusMessage = "Ready"
    @Published var workspacePath = ""

    init() {
        openAIKey = KeychainStore.load()
    }

    func bootstrapAndRefresh() {
        Task {
            do {
                if !openAIKey.isEmpty {
                    try KeychainStore.save(openAIKey)
                }
                _ = try runPython(arguments: ["bootstrap"])
                try await refresh()
            } catch {
                statusMessage = error.localizedDescription
            }
        }
    }

    func refresh() async throws {
        let data = try runPython(arguments: ["overview"])
        let overview = try JSONDecoder().decode(OverviewResponse.self, from: data)
        batches = overview.batches
        pendingRecords = overview.pending_records
        workspacePath = overview.workspace
        statusMessage = "Loaded \(pendingRecords.count) pending records"
    }

    func startSync() {
        Task {
            do {
                try saveKeyIfNeeded()
                _ = try runPython(arguments: ["start-incremental-sync"])
                try await refresh()
            } catch {
                statusMessage = error.localizedDescription
            }
        }
    }

    func submitURL() {
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        Task {
            do {
                try saveKeyIfNeeded()
                _ = try runPython(arguments: ["submit-url", "--url", trimmed])
                manualURL = ""
                try await refresh()
            } catch {
                statusMessage = error.localizedDescription
            }
        }
    }

    func setRecordStatus(id: Int, status: String) {
        Task {
            do {
                _ = try runPython(arguments: ["set-record-status", "--id", "\(id)", "--status", status])
                try await refresh()
            } catch {
                statusMessage = error.localizedDescription
            }
        }
    }

    func applyBatch(id: Int) {
        Task {
            do {
                _ = try runPython(arguments: ["apply-accepted", "--batch-id", "\(id)"])
                try await refresh()
            } catch {
                statusMessage = error.localizedDescription
            }
        }
    }

    private func saveKeyIfNeeded() throws {
        guard !openAIKey.isEmpty else { return }
        try KeychainStore.save(openAIKey)
    }

    private func runPython(arguments: [String]) throws -> Data {
        guard let resourcesURL = Bundle.main.resourceURL else {
            throw PythonCommandError.missingResources
        }

        let pythonCandidates = [
            resourcesURL.appendingPathComponent("python_runtime/bin/python3").path,
            resourcesURL.appendingPathComponent("python_runtime/bin/python3.9").path,
            resourcesURL.appendingPathComponent("python_runtime/bin/python").path
        ]
        guard let pythonPath = pythonCandidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            throw PythonCommandError.missingResources
        }

        let enginePath = resourcesURL.appendingPathComponent("engine/aaajiao_importer.py").path
        let sitePackages = resourcesURL.appendingPathComponent("python_runtime/lib/python3.9/site-packages").path
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [enginePath] + arguments
        process.environment = [
            "AAAJIAO_IMPORTER_BUNDLE_ROOT": resourcesURL.path,
            "AAAJIAO_REPO_ROOT": "/Users/aaajiao/Documents/aaajiao_scraper",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": sitePackages,
            "OPENAI_API_KEY": openAIKey,
        ].merging(ProcessInfo.processInfo.environment) { new, _ in new }

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        try process.run()
        process.waitUntilExit()

        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        let errorData = stderr.fileHandleForReading.readDataToEndOfFile()

        guard process.terminationStatus == 0 else {
            let err = String(data: errorData, encoding: .utf8) ?? "Python engine failed"
            throw PythonCommandError.nonZeroExit(err)
        }

        return output
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
                Button("Refresh") { model.bootstrapAndRefresh() }
            }

            HStack {
                TextField("Manual URL", text: $model.manualURL)
                    .textFieldStyle(.roundedBorder)
                Button("Import") { model.submitURL() }
            }

            if !model.workspacePath.isEmpty {
                Text(model.workspacePath)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Text(model.statusMessage)
                .font(.caption)

            Divider()

            Text("Pending Records")
                .font(.subheadline)

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(model.pendingRecords) { record in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(record.title.isEmpty ? record.slug : record.title)
                                .font(.headline)
                            if !record.title_cn.isEmpty {
                                Text(record.title_cn)
                                    .font(.caption)
                            }
                            Text(record.url)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text("type: \(record.page_type)  confidence: \(String(format: "%.2f", record.confidence))  batch: \(record.batch_id)")
                                .font(.caption2)
                            if !record.materials.isEmpty {
                                Text(record.materials)
                                    .font(.caption2)
                                    .lineLimit(2)
                            }

                            HStack {
                                Button("Accept") { model.setRecordStatus(id: record.id, status: "accepted") }
                                Button("Reject") { model.setRecordStatus(id: record.id, status: "rejected") }
                            }
                        }
                        .padding(.bottom, 8)
                        Divider()
                    }
                }
            }
            .frame(maxHeight: 280)

            Divider()

            Text("Batches")
                .font(.subheadline)

            ForEach(model.batches) { batch in
                HStack {
                    Text("#\(batch.id) \(batch.mode) \(batch.accepted_records)/\(batch.total_records)")
                        .font(.caption)
                    Spacer()
                    Button("Apply") { model.applyBatch(id: batch.id) }
                        .disabled(batch.accepted_records == 0)
                }
            }
        }
        .padding(14)
        .frame(width: 420)
        .onAppear { model.bootstrapAndRefresh() }
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
