import Foundation

enum PreviewAuthenticationMode: String, CaseIterable, Identifiable {
    case valid
    case rejected
    case connectionUnavailable

    var id: String { rawValue }
    var title: String {
        switch self {
        case .valid: return "Valid Key"
        case .rejected: return "Rejected Key"
        case .connectionUnavailable: return "Connection Unavailable"
        }
    }
}

enum PreviewQueueScenario: String, CaseIterable, Identifiable {
    case emptyQueue
    case noSiteUpdates
    case allAccepted
    case sampleData

    var id: String { rawValue }
    var title: String {
        switch self {
        case .emptyQueue: return "Empty Queue"
        case .noSiteUpdates: return "No Site Updates"
        case .allAccepted: return "All Accepted"
        case .sampleData: return "Restore Sample Data"
        }
    }
}

/// A complete in-memory implementation of the production helper contract.
/// It has no HelperClient, subprocess, Git, filesystem-write or credential API.
@MainActor
final class PreviewHelper: ImporterHelper {
    // The scenario changes only this preview instance, never the stored key.
    var authenticationMode: PreviewAuthenticationMode = .valid
    private(set) var simulatedScrapeCount = 0
    private(set) var validationCheckCount = 0
    private var records: [[String: Any]] = []
    private var templateRecords: [[String: Any]] = []
    private var batchModes: [Int: String] = [:]
    private var templateBatchModes: [Int: String] = [:]
    private var completedBatchIDs: Set<Int> = []
    private(set) var queueScenario: PreviewQueueScenario = .sampleData
    private var nextBatchID = 303
    private var nextRecordID = 3001
    private var isImportRunning = false
    private var cancellationRequested = false
    private let fixtureURL: URL

    init(fixtureURL: URL) throws {
        self.fixtureURL = fixtureURL
        try loadFixtures()
    }

    private func loadFixtures() throws {
        let data = try Data(contentsOf: fixtureURL)
        guard let fixture = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let records = fixture["records"] as? [[String: Any]],
              let batches = fixture["batches"] as? [[String: Any]] else {
            throw PreviewError.invalidFixtures
        }
        self.records = records
        templateRecords = records
        batchModes = Dictionary(uniqueKeysWithValues: batches.compactMap { batch in
            guard let id = batch["id"] as? Int, let mode = batch["mode"] as? String else { return nil }
            return (id, mode)
        })
        templateBatchModes = batchModes
        nextBatchID = 303
        nextRecordID = 3001
    }

    func selectQueueScenario(_ scenario: PreviewQueueScenario) {
        guard !isImportRunning else { return }
        records = templateRecords
        batchModes = templateBatchModes
        completedBatchIDs = []
        nextBatchID = 303
        nextRecordID = 3001
        cancellationRequested = false
        queueScenario = scenario
        switch scenario {
        case .emptyQueue:
            records = []
            batchModes = [:]
        case .noSiteUpdates:
            records = []
            batchModes = [nextBatchID: "incremental"]
            completedBatchIDs.insert(nextBatchID)
            nextBatchID += 1
        case .allAccepted:
            for index in records.indices {
                records[index]["status"] = "accepted"
                records[index]["error_message"] = NSNull()
                records[index]["error_code"] = NSNull()
                records[index]["error_history"] = [[String: String]]()
            }
        case .sampleData:
            break
        }
    }

    private func settings(model: String = "gpt-4.1", source: String = "default", hasKey: Bool = true) -> AppSettings {
        AppSettings(
            workspace_path: "/Preview/in-memory-workspace",
            repo_path: "/Preview/no-git-repository",
            has_openai_key: hasKey,
            openai_model: model,
            openai_model_source: source,
            workspace_status: "ready",
            workspace_seed_version: "preview-fixture-v1",
            bundle_seed_version: "preview-fixture-v1",
            baseline_status: "synced",
            baseline_source_url: "preview://in-memory-baseline",
            baseline_branch: "preview",
            baseline_commit: "preview-baseline-0001",
            baseline_updated_at: "2026-09-07T08:00:00Z",
            baseline_error: ""
        )
    }

    private func dto(_ record: [String: Any]) throws -> ProposedRecord {
        try JSONDecoder().decode(ProposedRecord.self, from: JSONSerialization.data(withJSONObject: record))
    }

    private func summary(_ batchID: Int) -> BatchSummary {
        let rows = records.filter { $0["batch_id"] as? Int == batchID }
        let accepted = rows.filter { $0["status"] as? String == "accepted" }.count
        return BatchSummary(
            id: batchID,
            mode: batchModes[batchID] ?? "manual",
            status: completedBatchIDs.contains(batchID) ? "completed" : (accepted > 0 ? "ready_to_apply" : "reviewing"),
            total_records: rows.count,
            accepted_records: accepted,
            ready_records: rows.filter { $0["status"] as? String == "ready_for_review" }.count,
            last_error: ""
        )
    }

    private func detail(_ batchID: Int) throws -> BatchDetailResponse {
        guard batchModes[batchID] != nil else { throw PreviewError.recordNotFound }
        let rows = try records.filter { $0["batch_id"] as? Int == batchID }.map(dto)
        let accepted = rows.filter { $0.status == "accepted" }.count
        return BatchDetailResponse(
            batch: summary(batchID),
            records: rows,
            total_records: rows.count,
            accepted_count: accepted,
            deleted_count: rows.filter { $0.status == "rejected" }.count,
            failed_count: rows.filter { $0.status == "failed" }.count,
            syncable_count: accepted,
            pending_count: rows.filter { ["ready_for_review", "needs_review"].contains($0.status) }.count
        )
    }

    private func index(_ id: Int) throws -> Int {
        guard let index = records.firstIndex(where: { $0["id"] as? Int == id }) else { throw PreviewError.recordNotFound }
        return index
    }

    private func changeStatus(id: Int, status: String) throws -> RecordStatusResponse {
        let index = try index(id)
        records[index]["status"] = status
        return RecordStatusResponse(id: id, status: status)
    }

    func validateOpenAIKey(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> OpenAIKeyValidationResponse {
        validationCheckCount += 1
        switch authenticationMode {
        case .valid:
            return OpenAIKeyValidationResponse(status: "valid", message: "Preview API key check succeeded. No API was contacted.")
        case .rejected:
            throw HelperClientError.authenticationFailed("OpenAI authentication failed. Check the API key in Settings, then retry.")
        case .connectionUnavailable:
            return OpenAIKeyValidationResponse(
                status: "unverified",
                message: "Preview connection is unavailable. The key has not been rejected; try checking again when the connection is restored.",
                reason: "connection_failed"
            )
        }
    }

    private func requireImportAuthentication(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws {
        let check = try await validateOpenAIKey(openAIKey: openAIKey, openAIModel: openAIModel, openAIModelSource: openAIModelSource)
        if check.status == "unverified" {
            throw HelperClientError.preflightFailed("Could not reach OpenAI to check the API key. No import was started; check the connection and retry.")
        }
    }

    private func pauseImport(total: Int = 4, onProgress: (@Sendable (HelperProgress) -> Void)? = nil) async throws {
        if total > 0 { simulatedScrapeCount += 1 }
        isImportRunning = true
        cancellationRequested = false
        defer { isImportRunning = false }

        func emit(_ line: String) {
            if let progress = HelperProgress(stderrLine: Data(line.utf8)) {
                onProgress?(progress)
            }
        }

        func pause() async throws {
            try await Task.sleep(nanoseconds: 400_000_000)
            if cancellationRequested { throw HelperClientError.cancelled }
        }

        emit("STAGE checking_access")
        try await pause()
        emit("STAGE discovering_urls")
        try await pause()
        guard total > 0 else { return }
        emit("PROGRESS 0/\(total) https://eventstructure.com/preview-1")
        for step in 1...total {
            let url = "https://eventstructure.com/preview-\(step)"
            emit("STAGE reading_page \(url)")
            try await pause()
            emit("STAGE validating_record \(url)")
            try await pause()
            emit("PROGRESS \(step)/\(total) \(url)")
        }
    }

    func bootstrapWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        BootstrapResponse(settings: settings(model: openAIModel, source: openAIModelSource, hasKey: !openAIKey.isEmpty), status: "baseline_synced")
    }

    func listPendingRecords(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> PendingRecordsResponse {
        PendingRecordsResponse(
            settings: settings(model: openAIModel, source: openAIModelSource, hasKey: !openAIKey.isEmpty),
            batches: batchModes.keys.sorted(by: >).map(summary),
            pending_records: try records.filter { $0["status"] as? String != "rejected" }.map(dto)
        )
    }

    func resetWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        selectQueueScenario(.sampleData)
        return BootstrapResponse(settings: settings(model: openAIModel, source: openAIModelSource, hasKey: !openAIKey.isEmpty), status: "reset_synced")
    }

    func refreshWorkspaceBaseline(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        BootstrapResponse(settings: settings(model: openAIModel, source: openAIModelSource, hasKey: !openAIKey.isEmpty), status: "baseline_synced")
    }

    func startIncrementalSync(openAIKey: String, openAIModel: String, openAIModelSource: String, onProgress: (@Sendable (HelperProgress) -> Void)?) async throws -> StartSyncResponse {
        try await requireImportAuthentication(openAIKey: openAIKey, openAIModel: openAIModel, openAIModelSource: openAIModelSource)
        if queueScenario == .noSiteUpdates {
            try await pauseImport(total: 0, onProgress: onProgress)
            let batchID = nextBatchID
            nextBatchID += 1
            batchModes[batchID] = "incremental"
            completedBatchIDs.insert(batchID)
            return StartSyncResponse(batch_id: batchID, urls_processed: 0)
        }
        try await pauseImport(onProgress: onProgress)
        if batchModes[202] == nil {
            records.append(contentsOf: templateRecords.filter { $0["batch_id"] as? Int == 202 })
            batchModes[202] = "incremental"
        }
        return StartSyncResponse(batch_id: 202, urls_processed: records.filter { $0["batch_id"] as? Int == 202 }.count)
    }

    func submitManualURL(_ url: String, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> SubmitURLResponse {
        try await requireImportAuthentication(openAIKey: openAIKey, openAIModel: openAIModel, openAIModelSource: openAIModelSource)
        try await pauseImport()
        guard var record = templateRecords.first else { throw PreviewError.recordNotFound }
        let batchID = nextBatchID
        let recordID = nextRecordID
        nextBatchID += 1
        nextRecordID += 1
        record["id"] = recordID
        record["batch_id"] = batchID
        record["url"] = url
        record["slug"] = URL(string: url)?.lastPathComponent ?? "preview-import"
        record["title"] = "Imported preview artwork"
        record["title_cn"] = "预览导入作品"
        record["status"] = "ready_for_review"
        record["is_update"] = false
        record["baseline_record"] = NSNull()
        record["baseline_fields"] = [String: String]()
        record["error_message"] = NSNull()
        record["error_history"] = [[String: String]]()
        record["retry_count"] = 0
        record["effective_fields"] = Self.fieldStrings(record)
        batchModes[batchID] = "manual"
        records.append(record)
        return SubmitURLResponse(batch_id: batchID, url: url)
    }

    func acceptRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try changeStatus(id: id, status: "accepted")
    }

    func rejectRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try changeStatus(id: id, status: "rejected")
    }

    func retryRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try await requireImportAuthentication(openAIKey: openAIKey, openAIModel: openAIModel, openAIModelSource: openAIModelSource)
        try await pauseImport()
        let index = try index(id)
        records[index]["error_message"] = NSNull()
        records[index]["confidence"] = 0.92
        records[index]["retry_count"] = (records[index]["retry_count"] as? Int ?? 0) + 1
        return try changeStatus(id: id, status: "ready_for_review")
    }

    func updateRecord(id: Int, fields: [String: String], openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        let index = try index(id)
        for (key, value) in fields {
            if ["images", "high_res_images"].contains(key) {
                records[index][key] = value.split(separator: "\n").map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            } else {
                records[index][key] = value
            }
        }
        records[index]["effective_fields"] = Self.fieldStrings(records[index])
        records[index]["error_message"] = NSNull()
        return try changeStatus(id: id, status: "needs_review")
    }

    func getBatchDetail(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BatchDetailResponse {
        try detail(batchID)
    }

    func getApplyPreview(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyPreview {
        let detail = try detail(batchID)
        let accepted = detail.records.filter { $0.status == "accepted" }
        return ApplyPreview(
            batch_id: batchID,
            accepted_count: accepted.count,
            new_count: accepted.filter { !$0.is_update }.count,
            updated_count: accepted.filter(\.is_update).count,
            target_files: ["Preview memory / aaajiao_works.json", "Preview memory / aaajiao_portfolio.md"],
            will_push: !accepted.isEmpty,
            error_message: accepted.isEmpty ? "Accept a preview record first." : ""
        )
    }

    func applyAcceptedRecords(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyResponse {
        let preview = try await getApplyPreview(batchID: batchID, openAIKey: openAIKey, openAIModel: openAIModel, openAIModelSource: openAIModelSource)
        try await Task.sleep(nanoseconds: 250_000_000)
        records.removeAll { $0["batch_id"] as? Int == batchID && ["accepted", "rejected"].contains($0["status"] as? String ?? "") }
        let remaining = records.filter { $0["batch_id"] as? Int == batchID }.count
        if remaining == 0 {
            batchModes.removeValue(forKey: batchID)
            completedBatchIDs.remove(batchID)
        }
        return ApplyResponse(
            batch_id: batchID,
            applied_commit_sha: "preview-only-no-git-push",
            preview: preview,
            warning_message: nil,
            remaining_records: remaining
        )
    }

    func deleteBatch(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> DeleteBatchResponse {
        let deleted = records.filter { $0["batch_id"] as? Int == batchID }.count
        records.removeAll { $0["batch_id"] as? Int == batchID }
        batchModes.removeValue(forKey: batchID)
        completedBatchIDs.remove(batchID)
        return DeleteBatchResponse(batch_id: batchID, deleted_records: deleted)
    }

    @discardableResult
    func cancelCurrentCommand() -> Bool {
        guard isImportRunning else { return false }
        cancellationRequested = true
        return true
    }

    private static func fieldStrings(_ record: [String: Any]) -> [String: String] {
        let keys = ["title", "title_cn", "year", "type", "materials", "size", "duration", "credits", "description_en", "description_cn", "video_link", "images", "high_res_images"]
        return Dictionary(uniqueKeysWithValues: keys.map { key in
            if let array = record[key] as? [String] { return (key, array.joined(separator: "\n")) }
            return (key, record[key] as? String ?? "")
        })
    }
}

private enum PreviewError: LocalizedError {
    case invalidFixtures
    case recordNotFound

    var errorDescription: String? {
        switch self {
        case .invalidFixtures: return "The bundled preview fixtures are invalid."
        case .recordNotFound: return "This preview record or batch no longer exists. Reset Workspace to restore the sample data."
        }
    }
}
