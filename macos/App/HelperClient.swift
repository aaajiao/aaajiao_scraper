import Foundation

enum HelperClientError: LocalizedError {
    case missingResources
    case nonZeroExit(String)
    case decodeFailure(String)

    var errorDescription: String? {
        switch self {
        case .missingResources:
            return "Bundled helper resources are missing."
        case .nonZeroExit(let message):
            return message.trimmingCharacters(in: .whitespacesAndNewlines)
        case .decodeFailure(let message):
            return "Failed to decode helper output: \(message)"
        }
    }
}

final class HelperClient: @unchecked Sendable {
    func bootstrapWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        try await runCommandAsync(
            arguments: ["bootstrapWorkspace"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: BootstrapResponse.self
        )
    }

    func listPendingRecords(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> PendingRecordsResponse {
        try await runCommandAsync(
            arguments: ["listPendingRecords"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: PendingRecordsResponse.self
        )
    }

    func resetWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        try await runCommandAsync(
            arguments: ["resetWorkspace"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: BootstrapResponse.self
        )
    }

    func refreshWorkspaceBaseline(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        try await runCommandAsync(
            arguments: ["refreshWorkspaceBaseline"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: BootstrapResponse.self
        )
    }

    func startIncrementalSync(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> StartSyncResponse {
        try await runCommandAsync(
            arguments: ["startIncrementalSync"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: StartSyncResponse.self
        )
    }

    func submitManualURL(_ url: String, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> SubmitURLResponse {
        try await runCommandAsync(
            arguments: ["submitManualURL", "--url", url],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: SubmitURLResponse.self
        )
    }

    func acceptRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try await runCommandAsync(
            arguments: ["acceptRecord", "--id", "\(id)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: RecordStatusResponse.self
        )
    }

    func rejectRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try await runCommandAsync(
            arguments: ["rejectRecord", "--id", "\(id)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: RecordStatusResponse.self
        )
    }

    func getBatchDetail(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BatchDetailResponse {
        try await runCommandAsync(
            arguments: ["getBatchDetail", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: BatchDetailResponse.self
        )
    }

    func getApplyPreview(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyPreview {
        try await runCommandAsync(
            arguments: ["getApplyPreview", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: ApplyPreview.self
        )
    }

    func applyAcceptedRecords(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyResponse {
        try await runCommandAsync(
            arguments: ["applyAcceptedRecords", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: ApplyResponse.self
        )
    }

    func deleteBatch(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> DeleteBatchResponse {
        try await runCommandAsync(
            arguments: ["deleteBatch", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            as: DeleteBatchResponse.self
        )
    }

    private func runCommandAsync<T: Decodable & Sendable>(
        arguments: [String],
        openAIKey: String,
        openAIModel: String,
        openAIModelSource: String,
        as type: T.Type
    ) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let result = try self.runCommand(
                        arguments: arguments,
                        openAIKey: openAIKey,
                        openAIModel: openAIModel,
                        openAIModelSource: openAIModelSource,
                        as: type
                    )
                    continuation.resume(returning: result)
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private func runCommand<T: Decodable & Sendable>(
        arguments: [String],
        openAIKey: String,
        openAIModel: String,
        openAIModelSource: String,
        as type: T.Type
    ) throws -> T {
        let data = try runRawCommand(
            arguments: arguments,
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource
        )
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            let raw = String(decoding: data, as: UTF8.self)
            throw HelperClientError.decodeFailure(raw.isEmpty ? error.localizedDescription : raw)
        }
    }

    private func runRawCommand(arguments: [String], openAIKey: String, openAIModel: String, openAIModelSource: String) throws -> Data {
        let helperURL = Bundle.main.bundleURL
            .appendingPathComponent("Contents/MacOS/AaajiaoHelper", isDirectory: false)
        guard FileManager.default.isExecutableFile(atPath: helperURL.path) else {
            throw HelperClientError.missingResources
        }
        let process = Process()
        process.executableURL = helperURL
        process.arguments = arguments
        process.environment = [
            "OPENAI_API_KEY": openAIKey,
            "OPENAI_MODEL": openAIModel,
            "OPENAI_MODEL_SOURCE": openAIModelSource
        ].merging(ProcessInfo.processInfo.environment) { new, _ in new }

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        try process.run()
        process.waitUntilExit()

        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        let errorOutput = stderr.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0 else {
            let message = String(decoding: errorOutput, as: UTF8.self)
            throw HelperClientError.nonZeroExit(message.isEmpty ? "Helper failed." : message)
        }
        return output
    }
}
