import Foundation

/// The operations used by the review model. Tests supply an in-memory helper so
/// exercising operation state never reads the real workspace or starts a push.
@MainActor
protocol ImporterHelper: Sendable {
    func bootstrapWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse
    func listPendingRecords(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> PendingRecordsResponse
    func resetWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse
    func refreshWorkspaceBaseline(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse
    func startIncrementalSync(openAIKey: String, openAIModel: String, openAIModelSource: String, onProgress: (@Sendable (HelperProgress) -> Void)?) async throws -> StartSyncResponse
    func submitManualURL(_ url: String, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> SubmitURLResponse
    func acceptRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse
    func rejectRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse
    func retryRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse
    func updateRecord(id: Int, fields: [String: String], openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse
    func getBatchDetail(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BatchDetailResponse
    func getApplyPreview(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyPreview
    func applyAcceptedRecords(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyResponse
    func deleteBatch(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> DeleteBatchResponse
    @discardableResult func cancelCurrentCommand() -> Bool
}

extension HelperClient: ImporterHelper {}

/// Keychain and model preferences are injected separately from the helper; a
/// model test must never read, replace, or delete the user's actual API key.
struct AppModelPreferences {
    var loadKey: () -> KeychainStore.LoadResult
    var saveKey: (String) throws -> Void
    var deleteKey: () throws -> Void
    var loadModel: () -> OpenAIModelSelection
    var saveModel: (OpenAIModelSelection) -> Void

    static var live: Self {
        Self(
            loadKey: { KeychainStore.load() },
            saveKey: { try KeychainStore.save($0) },
            deleteKey: { try KeychainStore.delete() },
            loadModel: { OpenAIModelSettingsStore.load() },
            saveModel: { OpenAIModelSettingsStore.save($0) }
        )
    }
}
