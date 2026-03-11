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

final class HelperClient {
    func bootstrapWorkspace(openAIKey: String) throws -> BootstrapResponse {
        try runCommand(arguments: ["bootstrapWorkspace"], openAIKey: openAIKey, as: BootstrapResponse.self)
    }

    func listPendingRecords(openAIKey: String) throws -> PendingRecordsResponse {
        try runCommand(arguments: ["listPendingRecords"], openAIKey: openAIKey, as: PendingRecordsResponse.self)
    }

    func resetWorkspace(openAIKey: String) throws -> BootstrapResponse {
        try runCommand(arguments: ["resetWorkspace"], openAIKey: openAIKey, as: BootstrapResponse.self)
    }

    func startIncrementalSync(openAIKey: String) throws -> StartSyncResponse {
        try runCommand(arguments: ["startIncrementalSync"], openAIKey: openAIKey, as: StartSyncResponse.self)
    }

    func submitManualURL(_ url: String, openAIKey: String) throws -> SubmitURLResponse {
        try runCommand(arguments: ["submitManualURL", "--url", url], openAIKey: openAIKey, as: SubmitURLResponse.self)
    }

    func acceptRecord(id: Int, openAIKey: String) throws -> RecordStatusResponse {
        try runCommand(arguments: ["acceptRecord", "--id", "\(id)"], openAIKey: openAIKey, as: RecordStatusResponse.self)
    }

    func rejectRecord(id: Int, openAIKey: String) throws -> RecordStatusResponse {
        try runCommand(arguments: ["rejectRecord", "--id", "\(id)"], openAIKey: openAIKey, as: RecordStatusResponse.self)
    }

    func getApplyPreview(batchID: Int, openAIKey: String) throws -> ApplyPreview {
        try runCommand(arguments: ["getApplyPreview", "--batch-id", "\(batchID)"], openAIKey: openAIKey, as: ApplyPreview.self)
    }

    func applyAcceptedRecords(batchID: Int, openAIKey: String) throws -> ApplyResponse {
        try runCommand(arguments: ["applyAcceptedRecords", "--batch-id", "\(batchID)"], openAIKey: openAIKey, as: ApplyResponse.self)
    }

    private func runCommand<T: Decodable>(
        arguments: [String],
        openAIKey: String,
        as type: T.Type
    ) throws -> T {
        let data = try runRawCommand(arguments: arguments, openAIKey: openAIKey)
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            let raw = String(decoding: data, as: UTF8.self)
            throw HelperClientError.decodeFailure(raw.isEmpty ? error.localizedDescription : raw)
        }
    }

    private func runRawCommand(arguments: [String], openAIKey: String) throws -> Data {
        let helperURL = Bundle.main.bundleURL
            .appendingPathComponent("Contents/MacOS/AaajiaoHelper", isDirectory: false)
        guard FileManager.default.isExecutableFile(atPath: helperURL.path) else {
            throw HelperClientError.missingResources
        }
        let process = Process()
        process.executableURL = helperURL
        process.arguments = arguments
        process.environment = [
            "OPENAI_API_KEY": openAIKey
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
