import AppKit
import Foundation
import SwiftUI

enum ImporterBusyAction {
    case bootstrap
    case importURL
    case retryRecord
    case editRecord
    case checkOpenAIKey
    case syncSite
    case reloadResults
    case acceptRecord
    case deleteRecord
    case discardRun
    case resetWorkspace
    case prepareGitHubSync
    case syncGitHub
    case refreshBaseline
}

/// Incremental progress for `startSync()`, reported by the helper while it
/// works through a batch of URLs. nil until the first progress line arrives
/// (or for the whole run, on a helper build that doesn't emit any).
struct SyncProgress: Equatable {
    let completed: Int
    let total: Int
}

enum StatusTone: Equatable {
    case neutral
    case info
    case success
    case warning
    case error
}

@MainActor
final class AppModel: ObservableObject {
    private enum OpenAIAccessFailureKind { case authentication, permission, preflight }
    @Published var manualURL = ""
    @Published var searchText = "" { didSet { reconcileFilteredSelection() } }
    @Published var reviewFilter: ReviewFilter = .all { didSet { reconcileFilteredSelection() } }
    @Published var availableBatches: [BatchSummary] = []
    @Published var currentBatchID: Int?
    @Published var currentBatchDetail: BatchDetailResponse?
    @Published var selectedRecordID: Int?
    @Published var currentApplyPreview: ApplyPreview?
    @Published var currentBusyAction: ImporterBusyAction?
    @Published var syncProgress: SyncProgress?
    @Published var isCancellingImport = false
    @Published private(set) var isQuitRequested = false
    @Published var isShowingApplyConfirmation = false
    @Published var isShowingResetConfirmation = false
    @Published var isShowingImportSheet = false
    @Published var isShowingDeleteConfirmation = false
    @Published var isShowingDiscardConfirmation = false
    @Published var isShowingRecordEditor = false
    @Published var recordEditorValues: [String: String] = [:] {
        didSet { recordEditorError = recordEditorValidationError ?? "" }
    }
    @Published var recordEditorError = ""
    @Published var statusMessage = "Ready"
    @Published var statusTone: StatusTone = .neutral
    @Published var settings = AppSettings.empty
    @Published var settingsDraftOpenAIKey = "" {
        didSet {
            if oldValue != settingsDraftOpenAIKey {
                clearKeyValidation()
                settingsStatusMessage = ""
            }
        }
    }
    @Published var settingsDraftOpenAIModelPreset = OpenAIModelPreset.defaultPreset
    @Published var settingsDraftCustomOpenAIModel = ""
    @Published var settingsStatusMessage = ""
    @Published private(set) var keyValidationMessage = ""
    @Published private(set) var keyValidationTone: StatusTone = .neutral
    @Published private(set) var openAIAccessErrorMessage = ""
    @Published private(set) var openAIAccessErrorTitle = ""
    @Published private var accessFailureKind: OpenAIAccessFailureKind?

    private let helper: any ImporterHelper
    private let preferences: AppModelPreferences
    private let terminateApplication: @MainActor () -> Void
    private var quitCancellationTask: Task<Void, Never>?
    private var hasBootstrapped = false
    private var editingRecordID: Int?
    private var editingBatchID: Int?
    private var recordEditorOriginalValues: [String: String] = [:]
    private var validatedKeySnapshot: String?
    private var keyValidationRequestID: UUID?

    // Keychain reads are relatively expensive and the derived properties below
    // are re-evaluated on every view update, so the last load is cached; call
    // reloadKeychainCache() wherever the stored key may have changed or a
    // user-initiated action should re-check availability (e.g. after the user
    // unlocked their keychain).
    @Published private var cachedKeychainLoad: KeychainStore.LoadResult

    init(
        helper: any ImporterHelper = HelperClient(),
        preferences: AppModelPreferences = .live,
        terminateApplication: @escaping @MainActor () -> Void = { NSApplication.shared.terminate(nil) }
    ) {
        self.helper = helper
        self.preferences = preferences
        self.terminateApplication = terminateApplication
        cachedKeychainLoad = preferences.loadKey()
        let modelSelection = preferences.loadModel()
        settingsDraftOpenAIKey = savedOpenAIKey
        settingsDraftOpenAIModelPreset = modelSelection.preset
        settingsDraftCustomOpenAIModel = modelSelection.customModel
    }

    private func reloadKeychainCache() {
        cachedKeychainLoad = preferences.loadKey()
    }

    var savedOpenAIKey: String {
        if case .found(let value) = cachedKeychainLoad {
            return value
        }
        return ""
    }

    /// True when the last Keychain lookup failed with something other than
    /// "no item saved" (e.g. locked keychain, auth failure) — distinct from
    /// simply never having saved a key.
    var hasKeychainAccessFailure: Bool {
        if case .failure = cachedKeychainLoad {
            return true
        }
        return false
    }

    var savedOpenAIModelSelection: OpenAIModelSelection {
        preferences.loadModel()
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
        hasSavedOpenAIKey && !hasKeychainAccessFailure
    }

    var hasAuthenticationError: Bool { accessFailureKind == .authentication }

    var hasVerifiedOpenAIKey: Bool {
        validatedKeySnapshot == savedOpenAIKey && validatedKeySnapshot != nil && !hasAuthenticationError
    }

    var isCheckingOpenAIKey: Bool { currentBusyAction == .checkOpenAIKey }

    var canCheckOpenAIKey: Bool {
        !trimmedDraftOpenAIKey.isEmpty && !isReviewInteractionLocked && !hasOpenReviewModal
    }

    var canSubmitManualURL: Bool {
        canRunProtectedActions && !isReviewInteractionLocked && !isShowingApplyConfirmation && !manualURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && manualURLValidationMessage == nil
    }

    var canStartImport: Bool {
        canRunProtectedActions && !isReviewInteractionLocked && !hasOpenReviewModal
    }

    var manualURLValidationMessage: String? {
        artworkURLValidationMessage(manualURL)
    }

    var isReviewInteractionLocked: Bool {
        isBusy || isShowingRecordEditor || isQuitRequested
    }

    private var hasOpenReviewModal: Bool {
        isShowingImportSheet || isShowingApplyConfirmation
    }

    var isBusy: Bool {
        currentBusyAction != nil
    }

    var isImportingURL: Bool {
        currentBusyAction == .importURL
    }

    var isSyncingSite: Bool {
        currentBusyAction == .syncSite
    }

    var isReloadingResults: Bool {
        currentBusyAction == .reloadResults
    }

    var isSyncingGitHub: Bool {
        currentBusyAction == .syncGitHub
    }

    var isPreparingGitHubSync: Bool {
        currentBusyAction == .prepareGitHubSync
    }

    var isRefreshingBaseline: Bool {
        currentBusyAction == .refreshBaseline
    }

    var currentBatchSummary: BatchSummary? {
        currentBatchDetail?.batch
    }

    var visibleCurrentRecords: [ProposedRecord] {
        (currentBatchDetail?.records ?? []).filter { $0.status != "rejected" }
    }

    var filteredCurrentRecords: [ProposedRecord] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        return visibleCurrentRecords.filter { record in
            guard reviewFilter.matches(record) else { return false }
            guard !query.isEmpty else { return true }
            let values = [record.url, record.slug] + [RecordField.title, .titleCN, .year, .type, .materials, .descriptionEN, .descriptionCN].map { record.value(for: $0) }
            return values.contains { $0.localizedStandardContains(query) }
        }
    }

    var selectedRecord: ProposedRecord? {
        // No selection means no selection: the default "select the first row"
        // behavior is applied once at data-load time in syncSelection(with:),
        // not implicitly on every read here.
        guard let selectedRecordID else { return nil }
        return filteredCurrentRecords.first { $0.id == selectedRecordID }
    }

    var hasAcceptedRecords: Bool {
        (currentBatchDetail?.accepted_count ?? 0) > 0
    }

    var hasCurrentRun: Bool {
        currentBatchDetail != nil
    }

    var hasSelectedRecord: Bool {
        selectedRecord != nil
    }

    var currentRunTitle: String {
        guard let batch = currentBatchSummary else { return "No current results" }
        return batch.mode == "manual" ? "Single URL import" : "Site sync in review"
    }

    var reviewStatusValue: String {
        guard let detail = currentBatchDetail else { return "Nothing to review" }
        if detail.accepted_count > 0 {
            return "\(detail.accepted_count) accepted"
        }
        if detail.pending_count > 0 {
            return "\(detail.pending_count) pending"
        }
        if detail.failed_count > 0 {
            return "\(detail.failed_count) failed"
        }
        return "Ready"
    }

    var canRequestGitHubSync: Bool {
        hasAcceptedRecords && !isReviewInteractionLocked && !hasOpenReviewModal
    }

    var canConfirmGitHubSync: Bool {
        guard let preview = currentApplyPreview else { return false }
        return hasAcceptedRecords && preview.will_push && !isReviewInteractionLocked && !isShowingImportSheet
    }

    var gitHubSyncActionTitle: String {
        "Sync GitHub…"
    }

    var gitHubSyncActionSymbol: String {
        "arrow.up.circle.fill"
    }

    var canAcceptSelectedRecord: Bool {
        guard let record = selectedRecord else { return false }
        return !isReviewInteractionLocked && !hasOpenReviewModal && ReviewFilter.pending.matches(record) && recordAccessError(record) == nil
    }

    var canDeleteSelectedRecord: Bool {
        hasSelectedRecord && !isReviewInteractionLocked && !hasOpenReviewModal
    }

    var canRetrySelectedRecord: Bool {
        guard let record = selectedRecord else { return false }
        let retryable = record.status == "failed" || (record.status == "needs_review" && record.error_code == "openai_authentication_failed")
        return !isReviewInteractionLocked && !hasOpenReviewModal && canRunProtectedActions && retryable
    }

    var canCancelCurrentImport: Bool {
        guard let currentBusyAction else { return false }
        return !isCancellingImport && [.importURL, .syncSite, .retryRecord].contains(currentBusyAction)
    }

    var canDiscardCurrentRun: Bool {
        hasCurrentRun && !isReviewInteractionLocked && !hasOpenReviewModal
    }

    var canEditSelectedRecord: Bool {
        guard let record = selectedRecord else { return false }
        return !isReviewInteractionLocked && !hasOpenReviewModal && ["ready_for_review", "needs_review", "accepted"].contains(record.status) && record.error_code != "openai_authentication_failed"
    }

    var canSaveRecordEdits: Bool {
        isShowingRecordEditor && !isBusy && !isQuitRequested && editingRecordID != nil && !changedRecordFields.isEmpty && recordEditorValidationError == nil
    }

    var selectedRecordSourceURL: URL? {
        guard let record = selectedRecord else { return nil }
        return URL(string: record.url)
    }

    var hasBlockingReviewState: Bool {
        if settings.baseline_status == "sync_skipped_pending_review" {
            return true
        }
        return (currentBatchDetail?.total_records ?? 0) > 0
    }

    var canRefreshBaseline: Bool {
        !isReviewInteractionLocked && !hasOpenReviewModal && !hasBlockingReviewState
    }

    var shouldAnimateGitHubSyncReady: Bool {
        hasAcceptedRecords && !isBusy && !isPreparingGitHubSync && !isSyncingGitHub
    }

    var baselineCommitURL: URL? {
        githubCommitURL(sourceURL: settings.baseline_source_url, commit: settings.baseline_commit)
    }

    var busyStatusMessage: String? {
        if isQuitRequested {
            switch currentBusyAction {
            case .importURL, .syncSite, .retryRecord:
                return "Stopping import before quitting..."
            case .syncGitHub:
                return "Finishing GitHub sync before quitting..."
            case .none:
                return "Quitting..."
            default:
                return "Finishing current operation before quitting..."
            }
        }
        if isCancellingImport { return "Stopping import..." }
        switch currentBusyAction {
        case .bootstrap:
            return "Preparing workspace..."
        case .importURL:
            return "Importing URL..."
        case .retryRecord:
            return "Retrying failed result..."
        case .editRecord:
            return "Saving corrections..."
        case .checkOpenAIKey:
            return "Checking OpenAI account access..."
        case .syncSite:
            guard let syncProgress else { return "Checking OpenAI access and finding artworks..." }
            return "Syncing site... (\(syncProgress.completed)/\(syncProgress.total))"
        case .reloadResults:
            return "Reloading results..."
        case .acceptRecord:
            return "Accepting result..."
        case .deleteRecord:
            return "Removing result..."
        case .discardRun:
            return "Discarding results..."
        case .resetWorkspace:
            return "Resetting workspace..."
        case .prepareGitHubSync:
            return "Preparing GitHub sync preview..."
        case .syncGitHub:
            return "Syncing accepted results..."
        case .refreshBaseline:
            return "Refreshing workspace baseline..."
        case .none:
            return nil
        }
    }

    var shouldShowStatusBanner: Bool {
        hasSavedOpenAIKey == false || hasKeychainAccessFailure || !openAIAccessErrorMessage.isEmpty || busyStatusMessage != nil || statusTone != .neutral || hasBaselineWarning
    }

    var hasBaselineWarning: Bool {
        if let error = settings.baseline_error, !error.isEmpty {
            return true
        }
        if settings.baseline_status == "seed_fallback" || settings.baseline_status == "sync_skipped_pending_review" {
            return true
        }
        return false
    }

    /// Single gate for every helper-backed action. Returns false (and does
    /// nothing) when another action is already in flight, so only one helper
    /// subprocess touches the workspace at a time. Callers that pass the gate
    /// must balance it with endExclusive(), typically via `defer` inside the
    /// Task that runs the async work.
    private func beginExclusive(_ action: ImporterBusyAction) -> Bool {
        guard !isBusy && !isQuitRequested else { return false }
        guard !isShowingRecordEditor || action == .editRecord else { return false }
        guard !isShowingImportSheet || action == .importURL else { return false }
        guard !isShowingApplyConfirmation || action == .syncGitHub else { return false }
        currentBusyAction = action
        return true
    }

    private func endExclusive() {
        isCancellingImport = false
        currentBusyAction = nil
        quitCancellationTask?.cancel()
        quitCancellationTask = nil
        if isQuitRequested { terminateApplication() }
    }

    func bootstrapIfNeeded() {
        guard !hasBootstrapped else { return }
        hasBootstrapped = true
        bootstrapAndRefresh()
    }

    func bootstrapAndRefresh() {
        guard beginExclusive(.bootstrap) else { return }
        Task {
            defer { endExclusive() }
            let response: BootstrapResponse
            do {
                response = try await helper.bootstrapWorkspace(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                syncDraftWithSavedSettingsIfNeeded()
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            // Read-only refresh is separate: a failure to load the review
            // results must not be reported as the workspace bootstrap failing.
            do {
                try await refresh(allowFallbackBatch: true)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus("Workspace ready, but loading review results failed: \(display(error))", tone: .warning)
            }
        }
    }

    func refreshFromUI() {
        guard beginExclusive(.reloadResults) else { return }
        Task {
            defer { endExclusive() }
            do {
                try await refresh(allowFallbackBatch: currentBatchID == nil)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func selectBatch(id: Int) {
        guard id != currentBatchID else { return }
        guard beginExclusive(.reloadResults) else { return }
        Task {
            defer { endExclusive() }
            do {
                try await loadBatch(batchID: id, updateStatusMessage: true)
            } catch {
                setStatus("Could not load the selected results: \(display(error))", tone: .error)
            }
        }
    }

    /// Reloads settings and the active/latest batch. A failure to load a batch
    /// is propagated to the caller (after clearing the now-unloadable run) so
    /// the current review results are never dropped silently — the caller is
    /// responsible for surfacing the error.
    func refresh(allowFallbackBatch: Bool) async throws {
        let response = try await helper.listPendingRecords(
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        settings = response.settings
        availableBatches = response.batches
        syncDraftWithSavedSettingsIfNeeded()

        if let currentBatchID {
            do {
                try await loadBatch(batchID: currentBatchID, updateStatusMessage: false)
            } catch {
                clearCurrentRun()
                throw error
            }
            return
        }

        if allowFallbackBatch, let latestBatch = response.batches.first {
            do {
                try await loadBatch(batchID: latestBatch.id, updateStatusMessage: false)
            } catch {
                clearCurrentRun()
                throw error
            }
            setStatus("Loaded the latest review results", tone: .info)
            return
        }

        if hasKeychainAccessFailure {
            setStatus("Could not read the OpenAI key from Keychain. Unlock your keychain and try again.", tone: .error)
        } else if !hasSavedOpenAIKey {
            setStatus("OpenAI key missing. Save a key to enable imports.", tone: .warning)
        } else {
            setStatus("Ready for a new import", tone: .neutral)
        }
    }

    func startSync() {
        guard !isReviewInteractionLocked && !hasOpenReviewModal else { return }
        reloadKeychainCache()
        guard canRunProtectedActions else {
            if hasKeychainAccessFailure {
                setStatus("Could not read the OpenAI key from Keychain. Unlock your keychain and try again.", tone: .error)
            } else {
                setStatus("OpenAI key missing. Save a key to continue.", tone: .warning)
            }
            return
        }
        guard beginExclusive(.syncSite) else { return }
        let importKey = savedOpenAIKey
        syncProgress = nil
        setStatus("Syncing site...", tone: .info)
        Task {
            defer {
                endExclusive()
                syncProgress = nil
            }
            do {
                let result = try await helper.startIncrementalSync(
                    openAIKey: importKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source,
                    onProgress: { [weak self] progress in
                        Task { @MainActor in
                            // Ignore stray progress lines that arrive after this
                            // sync has already finished/been superseded.
                            guard let self, self.currentBusyAction == .syncSite else { return }
                            self.syncProgress = SyncProgress(completed: progress.completed, total: progress.total)
                        }
                    }
                )
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                reportImportOutcome(isSiteSync: true, usedKey: importKey)
            } catch {
                await reportImportError(error, usedKey: importKey)
            }
        }
    }

    func requestImportSheet() {
        guard canStartImport else { return }
        isShowingImportSheet = true
    }

    func cancelImportSheet() {
        isShowingImportSheet = false
    }

    func requestWorkspaceReset() {
        guard !isReviewInteractionLocked && !hasOpenReviewModal else { return }
        isShowingResetConfirmation = true
    }

    func confirmWorkspaceReset() {
        guard beginExclusive(.resetWorkspace) else { return }
        setStatus("Resetting workspace and refreshing the GitHub baseline...", tone: .info)
        Task {
            defer { endExclusive() }
            let response: BootstrapResponse
            do {
                response = try await helper.resetWorkspace(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                availableBatches = []
                clearCurrentRun()
                isShowingResetConfirmation = false
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            do {
                try await refresh(allowFallbackBatch: false)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus("\(workspaceStatusMessage(for: response)) Reloading results failed — use Reload Results.", tone: .warning)
            }
        }
    }

    func refreshWorkspaceBaseline() {
        guard canRefreshBaseline else {
            setStatus("Finish or discard the current review results before refreshing the baseline.", tone: .warning)
            return
        }
        guard beginExclusive(.refreshBaseline) else { return }
        setStatus("Refreshing the GitHub baseline...", tone: .info)
        Task {
            defer { endExclusive() }
            let response: BootstrapResponse
            do {
                response = try await helper.refreshWorkspaceBaseline(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            do {
                try await refresh(allowFallbackBatch: false)
                setStatus(workspaceStatusMessage(for: response), tone: workspaceStatusTone(for: response.status))
            } catch {
                setStatus("\(workspaceStatusMessage(for: response)) Reloading results failed — use Reload Results.", tone: .warning)
            }
        }
    }

    func submitURL() {
        guard !isReviewInteractionLocked && !isShowingApplyConfirmation else { return }
        reloadKeychainCache()
        guard canRunProtectedActions else {
            if hasKeychainAccessFailure {
                setStatus("Could not read the OpenAI key from Keychain. Unlock your keychain and try again.", tone: .error)
            } else {
                setStatus("OpenAI key missing. Save a key to continue.", tone: .warning)
            }
            return
        }
        let trimmed = manualURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if let validationMessage = manualURLValidationMessage {
            setStatus(validationMessage, tone: .warning)
            return
        }
        guard beginExclusive(.importURL) else { return }
        let importKey = savedOpenAIKey
        setStatus("Importing URL...", tone: .info)
        Task {
            defer { endExclusive() }
            do {
                let result = try await helper.submitManualURL(
                    trimmed,
                    openAIKey: importKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                manualURL = ""
                isShowingImportSheet = false
                try await loadBatch(batchID: result.batch_id, updateStatusMessage: false)
                reportImportOutcome(isSiteSync: false, usedKey: importKey)
            } catch {
                await reportImportError(error, usedKey: importKey)
            }
        }
    }

    func cancelCurrentImport() {
        guard canCancelCurrentImport, helper.cancelCurrentCommand() else { return }
        isCancellingImport = true
        setStatus("Stopping import...", tone: .info)
        // Keep the exclusive gate until the awaiting operation confirms that
        // its process has stopped. A cancellation request is not completion.
    }

    func beginEditingSelectedRecord() {
        guard canEditSelectedRecord, let record = selectedRecord else { return }
        editingRecordID = record.id
        editingBatchID = record.batch_id
        recordEditorOriginalValues = Dictionary(uniqueKeysWithValues: RecordField.allCases.map { ($0.rawValue, record.value(for: $0)) })
        recordEditorValues = recordEditorOriginalValues
        recordEditorError = ""
        currentApplyPreview = nil
        isShowingRecordEditor = true
    }

    func cancelRecordEditing() {
        guard !isBusy else { return }
        finishRecordEditing()
    }

    func saveRecordEdits() {
        guard isShowingRecordEditor, !isBusy, let recordID = editingRecordID, let batchID = editingBatchID else { return }
        if let error = recordEditorValidationError {
            recordEditorError = error
            return
        }
        let fields = changedRecordFields
        guard !fields.isEmpty, beginExclusive(.editRecord) else { return }
        recordEditorError = ""
        Task {
            defer { endExclusive() }
            do {
                _ = try await helper.updateRecord(
                    id: recordID,
                    fields: fields,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
            } catch {
                // Keep the draft open so a temporary save failure never loses
                // the user's corrections or forces them to retype their work.
                recordEditorError = display(error)
                return
            }
            finishRecordEditing()
            currentApplyPreview = nil
            do {
                try await loadBatch(batchID: batchID, updateStatusMessage: false)
                if !filteredCurrentRecords.contains(where: { $0.id == recordID }) {
                    searchText = ""
                    reviewFilter = .all
                }
                selectedRecordID = recordID
                setStatus("Corrections saved. Review and accept the updated result before publishing.", tone: .success)
            } catch {
                currentBatchID = batchID
                currentBatchDetail = nil
                selectedRecordID = nil
                setStatus("Corrections saved, but reloading the result failed — use Reload Results.", tone: .warning)
            }
        }
    }

    private var changedRecordFields: [String: String] {
        var changes: [String: String] = [:]
        for field in RecordField.allCases {
            guard let value = recordEditorValues[field.rawValue], value != recordEditorOriginalValues[field.rawValue] else { continue }
            changes[field.rawValue] = value
        }
        return changes
    }

    private var recordEditorValidationError: String? {
        guard isShowingRecordEditor else { return nil }
        if (recordEditorValues[RecordField.title.rawValue] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "The English title cannot be empty."
        }
        let changes = changedRecordFields
        for field in [RecordField.images, .highResImages] {
            guard let changed = changes[field.rawValue] else { continue }
            let urls = changed.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            if urls.contains(where: { !isAbsoluteWebURL($0) }) {
                return "\(field.label) must contain one full http(s) URL per line."
            }
        }
        if let video = changes[RecordField.videoLink.rawValue]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !video.isEmpty && !isAbsoluteWebURL(video) {
            return "The video URL must be a full http(s) URL."
        }
        return nil
    }

    private func finishRecordEditing() {
        isShowingRecordEditor = false
        recordEditorValues = [:]
        recordEditorOriginalValues = [:]
        recordEditorError = ""
        editingRecordID = nil
        editingBatchID = nil
    }

    func retrySelectedRecord() {
        reloadKeychainCache()
        guard canRetrySelectedRecord, let record = selectedRecord, let batchID = currentBatchID else { return }
        guard beginExclusive(.retryRecord) else { return }
        let importKey = savedOpenAIKey
        Task {
            defer { endExclusive() }
            do {
                _ = try await helper.retryRecord(
                    id: record.id,
                    openAIKey: importKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await loadBatch(batchID: batchID, updateStatusMessage: false)
                let retriedRecord = currentBatchDetail?.records.first(where: { $0.id == record.id })
                if let retriedRecord, let accessError = recordAccessError(retriedRecord) {
                    recordAccessFailure(accessError, usedKey: importKey)
                    setStatus(display(accessError), tone: .error)
                } else if let retriedRecord, retriedRecord.status == "failed" {
                    setStatus("Retry failed: \(retriedRecord.error_message ?? "The URL could not be imported.")", tone: .error)
                } else {
                    setStatus("Retried \(record.displayTitle). Review the updated result.", tone: .success)
                }
            } catch {
                await reportImportError(error, usedKey: importKey)
            }
        }
    }

    private func reportImportOutcome(isSiteSync: Bool, usedKey: String) {
        guard let detail = currentBatchDetail else { return }
        if let error = detail.records.compactMap({ recordAccessError($0) }).first {
            recordAccessFailure(error, usedKey: usedKey)
            setStatus(display(error), tone: .error)
            return
        }
        if usedKey == savedOpenAIKey && detail.records.contains(where: { ["ready_for_review", "needs_review"].contains($0.status) }) {
            clearOpenAIAccessFailure()
        }
        if detail.total_records == 0 {
            setStatus("No new URLs to import.", tone: .info)
        } else if detail.failed_count == detail.total_records {
            let failure = detail.records.first(where: { $0.status == "failed" })?.error_message
            let reason = failure.flatMap { $0.isEmpty ? nil : $0 } ?? "The URLs could not be imported."
            setStatus("Import failed: \(reason)", tone: .error)
        } else if detail.failed_count > 0 {
            let reviewable = detail.total_records - detail.failed_count - detail.deleted_count
            setStatus("Imported \(reviewable) results for review; \(detail.failed_count) failed. Select a failed result to retry.", tone: .warning)
        } else if isSiteSync {
            setStatus("Imported \(detail.total_records) results for review.", tone: .success)
        } else {
            setStatus("Imported result is ready for review.", tone: .success)
        }
    }

    private func reportImportError(_ error: Error, usedKey: String) async {
        // Surface authentication/permission failures before doing any recovery
        // reads. The absence of a new batch must never erase this diagnosis.
        recordAccessFailure(error, usedKey: usedKey)
        if case HelperClientError.cancelled = error {
            setStatus("Import cancelled. Loading any saved results...", tone: .info)
        } else {
            setStatus(display(error), tone: .error)
        }
        syncProgress = nil
        if !isQuitRequested {
            // The helper may have committed partial records before cancellation
            // or an error. Refresh the batch inventory so that run remains
            // reachable without restarting the app or discarding an older run.
            do {
                let response = try await helper.listPendingRecords(
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                settings = response.settings
                availableBatches = response.batches
                let recoveryBatchID = currentBusyAction == .retryRecord ? currentBatchID : response.batches.first?.id
                if let recoveryBatchID {
                    try await loadBatch(batchID: recoveryBatchID, updateStatusMessage: false)
                }
            } catch {
                // Keep the original operation error visible. A later Reload
                // Results can retry this read without rerunning the import.
            }
        }
        if case HelperClientError.cancelled = error {
            setStatus("Import cancelled. Use Reload Results to inspect any saved progress.", tone: .info)
        } else {
            setStatus(display(error), tone: .error)
        }
    }

    private func recordAccessError(_ record: ProposedRecord) -> HelperClientError? {
        switch record.error_code {
        case "openai_authentication_failed":
            return .authenticationFailed("OpenAI authentication failed. Check the API key in Settings, then try again.")
        case "openai_permission_denied":
            return .permissionDenied("OpenAI permission denied. Check the project's access to the selected model, then retry.")
        default:
            return nil
        }
    }

    private func recordAccessFailure(_ error: Error, usedKey: String) {
        guard usedKey == savedOpenAIKey else { return }
        switch error {
        case HelperClientError.authenticationFailed:
            accessFailureKind = .authentication
            openAIAccessErrorTitle = "OpenAI authentication failed"
        case HelperClientError.permissionDenied:
            accessFailureKind = .permission
            openAIAccessErrorTitle = "OpenAI permission denied"
        case HelperClientError.preflightFailed:
            accessFailureKind = .preflight
            openAIAccessErrorTitle = "OpenAI access check failed"
        default:
            return
        }
        openAIAccessErrorMessage = display(error)
        if trimmedDraftOpenAIKey == usedKey {
            clearKeyValidation()
            keyValidationMessage = display(error)
            keyValidationTone = .error
        }
        settingsStatusMessage = display(error)
    }

    private func clearOpenAIAccessFailure() {
        accessFailureKind = nil
        openAIAccessErrorTitle = ""
        openAIAccessErrorMessage = ""
    }

    private func clearKeyValidation() {
        keyValidationRequestID = nil
        validatedKeySnapshot = nil
        keyValidationMessage = ""
        keyValidationTone = .neutral
    }

    func checkOpenAIKey() {
        guard canCheckOpenAIKey, beginExclusive(.checkOpenAIKey) else { return }
        let key = trimmedDraftOpenAIKey
        let requestID = UUID()
        keyValidationRequestID = requestID
        validatedKeySnapshot = nil
        keyValidationMessage = "Checking account access without generating content..."
        keyValidationTone = .info
        settingsStatusMessage = ""
        Task {
            defer { endExclusive() }
            do {
                let result = try await helper.validateOpenAIKey(
                    openAIKey: key,
                    openAIModel: draftOpenAIModelSelection.effectiveModel,
                    openAIModelSource: draftOpenAIModelSelection.source
                )
                guard keyValidationRequestID == requestID, trimmedDraftOpenAIKey == key else { return }
                if result.status == "valid" {
                    validatedKeySnapshot = key
                    keyValidationMessage = "Account access checked. Access to each model is checked during import."
                    keyValidationTone = .success
                    if key == savedOpenAIKey && accessFailureKind != .permission {
                        clearOpenAIAccessFailure()
                    }
                } else {
                    keyValidationMessage = result.message.isEmpty ? "Account access could not be verified. Retry the check when the connection is available." : result.message
                    keyValidationTone = .warning
                }
            } catch {
                guard keyValidationRequestID == requestID, trimmedDraftOpenAIKey == key else { return }
                recordAccessFailure(error, usedKey: key)
                keyValidationMessage = display(error)
                keyValidationTone = .error
            }
        }
    }

    func acceptSelectedRecord() {
        guard canAcceptSelectedRecord else { return }
        guard let record = selectedRecord else { return }
        let recordsBeforeAccept = filteredCurrentRecords
        let index = recordsBeforeAccept.firstIndex(where: { $0.id == record.id }) ?? 0
        let nextIDs = Array(recordsBeforeAccept.dropFirst(index + 1)) + Array(recordsBeforeAccept.prefix(index))
        guard beginExclusive(.acceptRecord) else { return }
        Task {
            defer { endExclusive() }
            do {
                _ = try await helper.acceptRecord(
                    id: record.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                if let batchID = currentBatchID {
                    try await loadBatch(batchID: batchID, updateStatusMessage: false)
                }
                let pending = filteredCurrentRecords.filter { ReviewFilter.pending.matches($0) }
                if let next = nextIDs.first(where: { candidate in pending.contains(where: { $0.id == candidate.id }) }) ?? pending.first {
                    selectedRecordID = next.id
                }
                setStatus("Accepted \(record.displayTitle)", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestDeleteSelectedRecord() {
        guard canDeleteSelectedRecord else { return }
        isShowingDeleteConfirmation = true
    }

    func confirmDeleteSelectedRecord() {
        guard let record = selectedRecord else { return }
        guard let batchID = currentBatchID else { return }
        isShowingDeleteConfirmation = false
        guard beginExclusive(.deleteRecord) else { return }
        Task {
            defer { endExclusive() }
            do {
                if visibleCurrentRecords.count <= 1 {
                    _ = try await helper.deleteBatch(
                        batchID: batchID,
                        openAIKey: savedOpenAIKey,
                        openAIModel: savedOpenAIModelSelection.effectiveModel,
                        openAIModelSource: savedOpenAIModelSelection.source
                    )
                    availableBatches.removeAll { $0.id == batchID }
                    clearCurrentRun()
                    try await refresh(allowFallbackBatch: false)
                    setStatus("Discarded current results", tone: .success)
                    return
                }

                _ = try await helper.rejectRecord(
                    id: record.id,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                try await loadBatch(batchID: batchID, updateStatusMessage: false)
                setStatus("Deleted \(record.displayTitle)", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestDiscardCurrentRun() {
        guard canDiscardCurrentRun else { return }
        isShowingDiscardConfirmation = true
    }

    func confirmDiscardCurrentRun() {
        guard let batchID = currentBatchID else { return }
        isShowingDiscardConfirmation = false
        guard beginExclusive(.discardRun) else { return }
        Task {
            defer { endExclusive() }
            do {
                _ = try await helper.deleteBatch(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                availableBatches.removeAll { $0.id == batchID }
                clearCurrentRun()
                try await refresh(allowFallbackBatch: false)
                setStatus("Discarded current results", tone: .success)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    func requestApply() {
        guard hasAcceptedRecords else { return }
        guard let batchID = currentBatchID else { return }
        guard beginExclusive(.prepareGitHubSync) else { return }
        // Git branch/upstream configuration may have changed outside the app.
        // Recheck on every explicit attempt, including after a failed preview.
        currentApplyPreview = nil
        setStatus("Preparing GitHub sync preview...", tone: .info)
        Task {
            defer { endExclusive() }
            do {
                let preview = try await helper.getApplyPreview(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                currentApplyPreview = preview.will_push ? preview : nil
                presentApplyPreview(preview)
            } catch {
                setStatus(display(error), tone: .error)
            }
        }
    }

    private func presentApplyPreview(_ preview: ApplyPreview) {
        if preview.will_push {
            isShowingApplyConfirmation = true
        } else {
            let message = preview.error_message.isEmpty
                ? "Accepted results are not ready to sync to GitHub yet."
                : preview.error_message
            setStatus(message, tone: .warning)
        }
    }

    func confirmApply() {
        guard let batchID = currentBatchID else { return }
        guard beginExclusive(.syncGitHub) else { return }
        setStatus("Syncing accepted results to GitHub...", tone: .info)
        Task {
            defer { endExclusive() }
            let result: ApplyResponse
            do {
                result = try await helper.applyAcceptedRecords(
                    batchID: batchID,
                    openAIKey: savedOpenAIKey,
                    openAIModel: savedOpenAIModelSelection.effectiveModel,
                    openAIModelSource: savedOpenAIModelSelection.source
                )
                isShowingApplyConfirmation = false
                if (result.remaining_records ?? 0) > 0 {
                    // Only accepted results were published. Keep the same run
                    // addressable so its failed/unreviewed rows can be resumed.
                    currentApplyPreview = nil
                } else {
                    availableBatches.removeAll { $0.id == batchID }
                    clearCurrentRun()
                }
            } catch {
                setStatus(display(error), tone: .error)
                return
            }
            // The push already happened and is irreversible. Report success up
            // front so a failing read-only refresh can only downgrade it to a
            // warning, never present it as the sync itself having failed.
            let remaining = result.remaining_records ?? 0
            let remainingMessage = remaining > 0 ? " \(remaining) results remain for review." : ""
            do {
                try await refresh(allowFallbackBatch: false)
                if let warning = result.warning_message, !warning.isEmpty {
                    setStatus("Synced to GitHub at \(result.applied_commit_sha).\(remainingMessage) \(warning)", tone: .warning)
                } else {
                    setStatus("Synced to GitHub at \(result.applied_commit_sha).\(remainingMessage)", tone: .success)
                }
            } catch {
                if remaining > 0 {
                    // refresh() clears an unloadable run; preserve its ID so
                    // Reload Results can recover the remaining review records.
                    currentBatchID = batchID
                    currentBatchDetail = nil
                    selectedRecordID = nil
                    currentApplyPreview = nil
                }
                let cleanupWarning = result.warning_message.map { " \($0)" } ?? ""
                setStatus("Synced to GitHub at \(result.applied_commit_sha).\(remainingMessage) Reloading results failed — use Reload Results.\(cleanupWarning)", tone: .warning)
            }
        }
    }

    @discardableResult
    func saveSettings() -> Bool {
        let newValue = trimmedDraftOpenAIKey
        let keyChanged = newValue != savedOpenAIKey
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
                try preferences.deleteKey()
            } else {
                try preferences.saveKey(newValue)
            }
            preferences.saveModel(modelSelection)
            reloadKeychainCache()
            if keyChanged {
                clearKeyValidation()
                clearOpenAIAccessFailure()
                setStatus(newValue.isEmpty ? "OpenAI key cleared." : "OpenAI key saved. Check account access in Settings before importing.", tone: .neutral)
            }
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
            try preferences.deleteKey()
            reloadKeychainCache()
            clearKeyValidation()
            clearOpenAIAccessFailure()
            setStatus("OpenAI key cleared.", tone: .neutral)
            settingsDraftOpenAIKey = ""
            settingsStatusMessage = "OpenAI key cleared from macOS Keychain."
            refreshFromUI()
        } catch {
            settingsStatusMessage = display(error)
        }
    }

    func quitApplication() {
        guard !isQuitRequested else { return }
        isQuitRequested = true
        guard isBusy else {
            terminateApplication()
            return
        }
        setStatus(busyStatusMessage ?? "Waiting to quit...", tone: .info)
        guard canCancelCurrentImport else { return }
        cancelCurrentImport()
        // A quit event can arrive in the gap between scheduling a helper call
        // and registering its subprocess. Retry the cancellation request until
        // it is acknowledged; never terminate the app while that import runs.
        if !isCancellingImport {
            quitCancellationTask = Task { [weak self] in
                while !Task.isCancelled {
                    guard let self, self.isBusy, self.isQuitRequested, self.canCancelCurrentImport else { return }
                    self.cancelCurrentImport()
                    if self.isCancellingImport { return }
                    do { try await Task.sleep(nanoseconds: 50_000_000) }
                    catch { return }
                }
            }
        }
    }

    /// Shared by Dock/system termination and the app's explicit Quit command.
    /// Returning false defers termination until endExclusive() requests it again.
    func shouldTerminateApplication() -> Bool {
        guard isBusy else { return true }
        quitApplication()
        return false
    }

    func openSelectedRecordSourcePage() {
        guard let url = selectedRecordSourceURL else { return }
        NSWorkspace.shared.open(url)
    }

    func openWorkspaceFolderOrCopyPath() {
        let trimmedPath = settings.workspace_path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPath.isEmpty else {
            setStatus("Workspace path is unavailable.", tone: .warning)
            return
        }

        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: trimmedPath, isDirectory: &isDirectory)
        if exists && isDirectory.boolValue {
            let didOpen = NSWorkspace.shared.open(URL(fileURLWithPath: trimmedPath, isDirectory: true))
            if didOpen {
                setStatus("Opened workspace folder in Finder.", tone: .info)
                return
            }
        }

        copyToPasteboard(trimmedPath)
        setStatus("Could not open folder. Workspace path copied to clipboard.", tone: .warning)
    }

    private func loadBatch(batchID: Int, updateStatusMessage: Bool) async throws {
        let detail = try await helper.getBatchDetail(
            batchID: batchID,
            openAIKey: savedOpenAIKey,
            openAIModel: savedOpenAIModelSelection.effectiveModel,
            openAIModelSource: savedOpenAIModelSelection.source
        )
        let switchedBatch = currentBatchID != batchID
        currentBatchID = batchID
        currentBatchDetail = detail
        if switchedBatch {
            selectedRecordID = nil
            searchText = ""
            reviewFilter = .all
        }
        availableBatches.removeAll { $0.id == batchID }
        availableBatches.append(detail.batch)
        availableBatches.sort { $0.id > $1.id }
        reconcileFilteredSelection()
        // The apply preview is a full-merge computation; fetch it lazily when
        // the user actually requests a GitHub sync (requestApply), not eagerly
        // after every data reload. Any preview from a prior load is now stale.
        currentApplyPreview = nil
        if updateStatusMessage {
            setStatus("Loaded current results", tone: .info)
        }
    }

    private func clearCurrentRun() {
        // Intentionally does not touch currentBusyAction: callers invoke this
        // mid-operation (e.g. before a follow-up refresh) and the busy gate
        // must stay held until the whole action finishes via endExclusive().
        currentBatchID = nil
        currentBatchDetail = nil
        selectedRecordID = nil
        currentApplyPreview = nil
    }

    private func syncSelection(with records: [ProposedRecord]) {
        if let selectedRecordID, records.contains(where: { $0.id == selectedRecordID }) {
            return
        }
        selectedRecordID = records.first?.id
    }

    private func reconcileFilteredSelection() {
        syncSelection(with: filteredCurrentRecords)
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

    private func setStatus(_ message: String, tone: StatusTone) {
        statusMessage = message
        statusTone = tone
    }

    private func copyToPasteboard(_ value: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }

    private func workspaceStatusMessage(for response: BootstrapResponse) -> String {
        switch response.status {
        case "initialized_synced":
            return "Workspace initialized from the latest GitHub baseline."
        case "initialized_seed_fallback":
            return "GitHub baseline unavailable. Workspace initialized from the bundled seed."
        case "baseline_synced":
            return "Workspace baseline refreshed from GitHub."
        case "baseline_seed_fallback":
            return "GitHub baseline refresh failed. Using bundled seed files."
        case "baseline_sync_skipped_pending_review":
            return "Skipped baseline refresh to protect current review results."
        case "reset_synced":
            return "Workspace reset and refreshed from the latest GitHub baseline."
        case "reset_seed_fallback":
            return "Workspace reset with bundled seed because GitHub was unavailable."
        default:
            return "Workspace updated."
        }
    }

    private func workspaceStatusTone(for status: String) -> StatusTone {
        switch status {
        case "initialized_seed_fallback", "baseline_seed_fallback", "baseline_sync_skipped_pending_review", "reset_seed_fallback":
            return .warning
        case "initialized_synced", "baseline_synced", "reset_synced":
            return .success
        default:
            return .info
        }
    }
}
