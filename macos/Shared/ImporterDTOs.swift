import Foundation

struct RecordError: Codable, Hashable {
    let at: String
    let message: String
}

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
    let baseline_fields: [String: String]?
    let effective_fields: [String: String]?
    let baseline_available: Bool?
    let error_history: [RecordError]?
    let retry_count: Int?
    let error_code: String?

    init(
        id: Int, batch_id: Int, url: String, slug: String, status: String, page_type: String,
        confidence: Double, is_update: Bool, title: String, title_cn: String, year: String,
        type: String, materials: String, size: String, duration: String, credits: String,
        description_en: String, description_cn: String, video_link: String, images: [String],
        high_res_images: [String], error_message: String?, baseline_fields: [String: String]? = nil,
        effective_fields: [String: String]? = nil, baseline_available: Bool? = nil,
        error_history: [RecordError]? = nil, retry_count: Int? = nil, error_code: String? = nil
    ) {
        self.id = id
        self.batch_id = batch_id
        self.url = url
        self.slug = slug
        self.status = status
        self.page_type = page_type
        self.confidence = confidence
        self.is_update = is_update
        self.title = title
        self.title_cn = title_cn
        self.year = year
        self.type = type
        self.materials = materials
        self.size = size
        self.duration = duration
        self.credits = credits
        self.description_en = description_en
        self.description_cn = description_cn
        self.video_link = video_link
        self.images = images
        self.high_res_images = high_res_images
        self.error_message = error_message
        self.baseline_fields = baseline_fields
        self.effective_fields = effective_fields
        self.baseline_available = baseline_available
        self.error_history = error_history
        self.retry_count = retry_count
        self.error_code = error_code
    }

    var displayTitle: String {
        let effectiveTitle = effective_fields?["title"] ?? title
        return effectiveTitle.isEmpty ? slug : effectiveTitle
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
    let baseline_status: String?
    let baseline_source_url: String?
    let baseline_branch: String?
    let baseline_commit: String?
    let baseline_updated_at: String?
    let baseline_error: String?

    static let empty = AppSettings(
        workspace_path: "",
        repo_path: "",
        has_openai_key: false,
        openai_model: "",
        openai_model_source: "",
        workspace_status: nil,
        workspace_seed_version: nil,
        bundle_seed_version: nil,
        baseline_status: nil,
        baseline_source_url: nil,
        baseline_branch: nil,
        baseline_commit: nil,
        baseline_updated_at: nil,
        baseline_error: nil
    )
}

struct BootstrapResponse: Codable {
    let settings: AppSettings
    let status: String
}

struct OpenAIKeyValidationResponse: Codable {
    let status: String
    let message: String
    let reason: String?

    init(status: String, message: String, reason: String? = nil) {
        self.status = status
        self.message = message
        self.reason = reason
    }
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
    let warning_message: String?
    let remaining_records: Int?

    init(batch_id: Int, applied_commit_sha: String, preview: ApplyPreview, warning_message: String? = nil, remaining_records: Int? = nil) {
        self.batch_id = batch_id
        self.applied_commit_sha = applied_commit_sha
        self.preview = preview
        self.warning_message = warning_message
        self.remaining_records = remaining_records
    }
}

struct DeleteBatchResponse: Codable {
    let batch_id: Int
    let deleted_records: Int
}
