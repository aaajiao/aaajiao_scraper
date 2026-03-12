import Foundation

struct ProposedRecord: Codable, Identifiable, Hashable {
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
    let video_link: String
    let images: [String]
    let high_res_images: [String]
    let error_message: String?

    var displayTitle: String {
        title.isEmpty ? slug : title
    }
}

struct BatchSummary: Codable, Identifiable, Hashable {
    let id: Int
    let mode: String
    let status: String
    let total_records: Int
    let accepted_records: Int
    let ready_records: Int
    let last_error: String
}

struct BatchDetailResponse: Codable, Hashable {
    let batch: BatchSummary
    let records: [ProposedRecord]
    let total_records: Int
    let accepted_count: Int
    let deleted_count: Int
    let failed_count: Int
    let syncable_count: Int
    let pending_count: Int
}

struct ApplyPreview: Codable, Hashable {
    let batch_id: Int
    let accepted_count: Int
    let new_count: Int
    let updated_count: Int
    let target_files: [String]
    let will_push: Bool
    let error_message: String
}

struct AppSettings: Codable, Hashable {
    let workspace_path: String
    let repo_path: String
    let has_openai_key: Bool
    let openai_model: String
    let openai_model_source: String
    let workspace_status: String?
    let workspace_seed_version: String?
    let bundle_seed_version: String?

    static let empty = AppSettings(
        workspace_path: "",
        repo_path: "",
        has_openai_key: false,
        openai_model: "",
        openai_model_source: "",
        workspace_status: nil,
        workspace_seed_version: nil,
        bundle_seed_version: nil
    )
}

struct BootstrapResponse: Codable {
    let settings: AppSettings
    let status: String
}

struct PendingRecordsResponse: Codable {
    let settings: AppSettings
    let batches: [BatchSummary]
    let pending_records: [ProposedRecord]
}

struct RecordStatusResponse: Codable {
    let id: Int
    let status: String
}

struct StartSyncResponse: Codable {
    let batch_id: Int
    let urls_processed: Int
}

struct SubmitURLResponse: Codable {
    let batch_id: Int
    let url: String
}

struct ApplyResponse: Codable {
    let batch_id: Int
    let applied_commit_sha: String
    let preview: ApplyPreview
}

struct DeleteBatchResponse: Codable {
    let batch_id: Int
    let deleted_records: Int
}
