import Foundation

@MainActor
func appModelTests() -> [AsyncAppTest] {
    [
        ("search and status filters never leave a hidden record actionable", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review", "accepted", "failed"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.reviewFilter = .failed
            try expectEqual(model.filteredCurrentRecords.map(\.id), [3], "Only failed rows match the filter")
            try expectEqual(model.selectedRecordID, 3, "Selection follows a visible row")
            model.searchText = "no matching artwork"
            try expectNil(model.selectedRecord, "An empty search result has no selected record")
            model.selectedRecordID = 1
            model.confirmDeleteSelectedRecord()
            try expect(!model.isBusy, "A stale hidden selection cannot start a delete")
            try expect(!model.canDeleteSelectedRecord, "Delete must be disabled for hidden selections")
            model.searchText = "WORK-2"
            try expectEqual(model.selectedRecord?.id, 3, "Search matches URLs without case sensitivity")
        }),
        ("accept advances to the next visible unreviewed result", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review", "failed", "needs_review", "accepted"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            helper.detail = modelBatch(["accepted", "failed", "needs_review", "accepted"])
            model.acceptSelectedRecord()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.acceptedIDs, [1], "Accept the selected result")
            try expectEqual(model.selectedRecord?.id, 3, "Skip failures and already-accepted rows when advancing")
        }),
        ("batch switching refreshes records and resets stale selection and filters", {
            let original = modelBatch(["failed"])
            let next = modelBatch(["ready_for_review"], batchID: 8, firstRecordID: 50)
            let helper = ModelTestHelper(detail: original)
            helper.detailsByID = [7: original, 8: next]
            helper.listedBatches = [next.batch, original.batch]
            let model = makeTestModel(helper)
            installBatch(original, in: model)
            model.refreshFromUI()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.availableBatches.map(\.id), [8, 7], "Keep all review batches discoverable")
            model.searchText = "work"
            model.reviewFilter = .failed
            model.currentApplyPreview = modelPreview(willPush: true)
            model.selectBatch(id: 8)
            try await waitForModel { !model.isBusy }
            try expectEqual(model.currentBatchID, 8, "Load the chosen batch")
            try expectEqual(model.selectedRecord?.id, 50, "Select a record belonging to the new batch")
            try expectEqual(model.searchText, "", "A prior batch's search should not hide the new run")
            try expectEqual(model.reviewFilter, .all, "Show the full chosen batch")
            try expectNil(model.currentApplyPreview, "A preview from another batch cannot survive switching")
        }),
        ("record field access preserves explicit empty corrections and unknown baselines", {
            let record = modelBatch(["needs_review"], effectiveFields: ["title": "Corrected", "description_en": ""], baselineFields: ["description_en": "Earlier description"], baselineAvailable: true).records[0]
            try expectEqual(record.value(for: .title), "Corrected", "Editor uses the helper's merged effective fields")
            try expectEqual(record.value(for: .descriptionEN), "", "An explicit cleared value must not fall back")
            try expectEqual(record.baselineValue(for: .descriptionEN), "Earlier description", "Keep the baseline comparison separate")
            try expectNil(modelBatch(["needs_review"]).records[0].baselineValue(for: .title), "An unavailable baseline must remain unknown")
        }),
        ("editor sends only changed fields and requires the result to be reviewed again", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted"], effectiveFields: ["credits": "Earlier credit"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.beginEditingSelectedRecord()
            try expect(!model.canSaveRecordEdits, "Opening an unchanged draft is not a saveable edit")
            let description = "First paragraph.\n\n第二段。"
            model.recordEditorValues["credits"] = ""
            model.recordEditorValues["description_en"] = description
            helper.detail = modelBatch(["needs_review"], effectiveFields: ["credits": "", "description_en": description])
            model.saveRecordEdits()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.updatedFields, [["credits": "", "description_en": description]], "Send only the changed values, preserving explicit clears and paragraph breaks")
            try expectEqual(model.selectedRecord?.status, "needs_review", "Saving corrections revokes acceptance")
            try expect(!model.isShowingRecordEditor, "Close the sheet only after a successful save")
            try expectNil(model.currentApplyPreview, "A correction invalidates the old publish preview")
        }),
        ("open editor blocks menu mutations and batch changes without losing the draft", {
            let helper = ModelTestHelper(detail: modelBatch(["needs_review"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.beginEditingSelectedRecord()
            model.recordEditorValues["title"] = "Unsaved correction"
            model.manualURL = "https://eventstructure.com/work"
            model.startSync()
            model.submitURL()
            model.acceptSelectedRecord()
            model.confirmDiscardCurrentRun()
            model.selectBatch(id: 8)
            model.refreshFromUI()
            model.requestImportSheet()
            try expect(!model.isBusy && !model.isShowingImportSheet, "No conflicting operation or sheet may open")
            try expectEqual(helper.submitCalls + helper.syncCalls + helper.listCalls + helper.acceptedIDs.count, 0, "Every menu entry respects the editor gate")
            try expectEqual(model.currentBatchID, 7, "The editing record's batch stays selected")
            try expectEqual(model.recordEditorValues["title"], "Unsaved correction", "Keep the draft intact")
        }),
        ("save failure leaves corrections open for retry", {
            let helper = ModelTestHelper(detail: modelBatch(["needs_review"]))
            helper.updateError = AppTestFailure(message: "Workspace is busy")
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.beginEditingSelectedRecord()
            model.recordEditorValues["title"] = "Preserve this correction"
            model.saveRecordEdits()
            try await waitForModel { !model.isBusy }
            try expect(model.isShowingRecordEditor, "A failed save must keep the sheet open")
            try expectEqual(model.recordEditorValues["title"], "Preserve this correction", "A save error cannot erase the draft")
            try expect(!model.recordEditorError.isEmpty, "Show the save failure inline")
            try expect(model.canSaveRecordEdits, "The unchanged draft can be retried")
        }),
        ("editor rejects blank titles and invalid changed media URLs", {
            let helper = ModelTestHelper(detail: modelBatch(["needs_review"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.beginEditingSelectedRecord()
            model.recordEditorValues["title"] = "  "
            try expect(!model.canSaveRecordEdits, "Titles must retain a nonempty value")
            model.recordEditorValues["title"] = "Valid title"
            model.recordEditorValues["images"] = "file:///tmp/local-image.jpg"
            model.saveRecordEdits()
            try expectEqual(helper.updatedFields.count, 0, "Invalid URLs must not reach the helper")
            try expect(!model.recordEditorError.isEmpty, "Explain the invalid field inline")
            model.recordEditorValues["images"] = "https://example.com/a.jpg\nhttps://example.com/a.jpg"
            try expect(model.canSaveRecordEdits, "Valid repeated image URLs preserve their intended order")
        }),
        ("manual URL validation is shared by button and direct submission", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review"]))
            let model = makeTestModel(helper)
            for invalid in ["https://example.com/work", "file:///tmp/work", "https://eventstructure.com/", "https://eventstructure.com.evil.example/work", "https://user@eventstructure.com/work"] {
                model.manualURL = invalid
                try expect(!model.canSubmitManualURL && model.manualURLValidationMessage != nil, "Reject unsupported artwork URL: \(invalid)")
                model.submitURL()
            }
            try expectEqual(helper.submitCalls, 0, "Direct command submission must use the same validation as the button")
            model.manualURL = "  https://www.eventstructure.com/foam-wave  "
            try expect(model.canSubmitManualURL, "Allow a full artwork URL with surrounding whitespace")
        }),
        ("import and publish sheets only allow their own confirmation action", {
            let helper = ModelTestHelper(detail: modelBatch(["needs_review", "accepted"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.manualURL = "https://eventstructure.com/work"
            model.requestImportSheet()
            try expect(model.canSubmitManualURL, "The Import sheet must allow its own valid submit")
            model.acceptSelectedRecord()
            model.confirmApply()
            model.selectBatch(id: 8)
            try expect(!model.isBusy && !model.canDeleteSelectedRecord && !model.canRequestGitHubSync, "Other review mutations are blocked while importing a URL")
            model.cancelImportSheet()
            model.currentApplyPreview = modelPreview(willPush: true)
            model.isShowingApplyConfirmation = true
            try expect(model.canConfirmGitHubSync, "The Publish sheet must allow its own confirmation")
            model.submitURL()
            model.acceptSelectedRecord()
            model.confirmDeleteSelectedRecord()
            try expectEqual(helper.submitCalls + helper.acceptedIDs.count, 0, "Keyboard and direct mutation entrypoints honor the Publish modal")
            try expect(!model.isBusy, "No conflicting action starts behind the Publish sheet")
            model.confirmApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.applyCalls, 1, "Only the explicit Publish confirmation starts an apply")
        }),
        ("cancelled import discovers its saved batch while keeping earlier runs reachable", {
            let original = modelBatch(["accepted"])
            let partial = modelBatch(["needs_review"], mode: "incremental", batchID: 8, firstRecordID: 80)
            let helper = ModelTestHelper(detail: original)
            helper.holdSubmit = true
            helper.listedBatches = [partial.batch, original.batch]
            helper.detailsByID = [7: original, 8: partial]
            let model = makeTestModel(helper)
            installBatch(original, in: model)
            model.manualURL = "https://eventstructure.com/work"
            model.submitURL()
            try await waitForModel { helper.submitContinuation != nil }
            model.cancelCurrentImport()
            helper.completeCancellation()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.availableBatches.map(\.id), [8, 7], "Cancelled partial results and older runs stay in the picker")
            try expectEqual(model.currentBatchID, 8, "Show the saved interrupted run")
            try expectEqual(model.selectedRecord?.id, 80, "Partial records are available for review")
        }),
        ("manual import reports persisted extraction failure", {
            let helper = ModelTestHelper(detail: modelBatch(["failed"]))
            let model = makeTestModel(helper)
            model.manualURL = "https://eventstructure.com/failed-work"
            model.submitURL()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .error, "A failed record must not show a green import success")
            try expect(model.statusMessage.contains("AI request failed"), "The actual extraction failure should be visible")
            try expectEqual(model.selectedRecord?.status, "failed", "The failed record remains available for retry")
        }),
        ("site sync distinguishes all-failed and mixed results", {
            let helper = ModelTestHelper(detail: modelBatch(["failed", "failed"], mode: "incremental"))
            let model = makeTestModel(helper)
            model.startSync()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .error, "All-failed site sync must be an error")
            helper.detail = modelBatch(["ready_for_review", "needs_review", "failed"], mode: "incremental")
            model.startSync()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .warning, "Mixed site sync should show partial success")
            try expect(model.statusMessage.contains("2 results") && model.statusMessage.contains("1 failed"), "Show both reviewable and failed counts")
        }),
        ("empty site sync reports no new results", {
            let model = makeTestModel(ModelTestHelper(detail: modelBatch([], mode: "incremental")))
            model.startSync()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .info, "An empty sync is informational")
            try expect(model.statusMessage.contains("No new URLs"), "Explain why no review rows were added")
        }),
        ("exclusive action gate prevents overlapping helper mutations", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review"]))
            helper.holdSubmit = true
            let model = makeTestModel(helper)
            model.manualURL = "https://eventstructure.com/work"
            model.submitURL()
            try await waitForModel { helper.submitContinuation != nil }
            model.submitURL()
            model.startSync()
            model.refreshFromUI()
            try expectEqual(helper.submitCalls, 1, "Only the original import may start")
            try expectEqual(helper.syncCalls, 0, "A site sync cannot overlap the import")
            try expectEqual(helper.listCalls, 0, "Reload must respect the same gate")
            helper.completeSubmit()
            try await waitForModel { !model.isBusy }
        }),
        ("cancellation holds the operation gate until the helper exits", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review"]))
            helper.holdSubmit = true
            let model = makeTestModel(helper)
            model.manualURL = "https://eventstructure.com/work"
            model.submitURL()
            try await waitForModel { helper.submitContinuation != nil }
            model.cancelCurrentImport()
            try expect(model.isCancellingImport && model.isBusy, "Requesting cancellation cannot unlock the workspace early")
            model.startSync()
            try expectEqual(helper.syncCalls, 0, "The next operation waits for actual termination")
            helper.completeCancellation()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .info, "User cancellation is not a generic action failure")
            try expect(!model.isCancellingImport, "Cancellation state resets after termination")
        }),
        ("idle quit terminates immediately and only once", {
            var terminations = 0
            let model = makeTestModel(ModelTestHelper(detail: modelBatch([])), terminateApplication: { terminations += 1 })
            model.quitApplication()
            model.quitApplication()
            try expectEqual(terminations, 1, "Repeated Quit commands must not enqueue duplicate termination")
            try expect(model.shouldTerminateApplication(), "An idle app permits system termination")
        }),
        ("quit cancels an import and waits for confirmed process termination", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review"]))
            helper.holdSubmit = true
            var terminations = 0
            let model = makeTestModel(helper, terminateApplication: { terminations += 1 })
            model.manualURL = "https://eventstructure.com/work"
            model.submitURL()
            try await waitForModel { helper.submitContinuation != nil }
            try expect(!model.shouldTerminateApplication(), "A Dock/system Quit must defer while importing")
            try expectEqual(terminations, 0, "Do not terminate before the subprocess stops")
            try expect(model.isCancellingImport, "Quit should request import cancellation")
            helper.completeCancellation()
            try await waitForModel { !model.isBusy }
            try expectEqual(terminations, 1, "Terminate once the helper confirms it has stopped")
            try expect(model.shouldTerminateApplication(), "The queued termination may now proceed")
        }),
        ("quit requested before helper registration still cancels the import", {
            let helper = ModelTestHelper(detail: modelBatch(["ready_for_review"]))
            helper.holdSubmit = true
            var terminations = 0
            let model = makeTestModel(helper, terminateApplication: { terminations += 1 })
            model.manualURL = "https://eventstructure.com/work"
            model.submitURL()
            model.quitApplication()
            try await waitForModel { model.isCancellingImport }
            try expectEqual(terminations, 0, "The scheduling gap must not terminate the app early")
            helper.completeCancellation()
            try await waitForModel { !model.isBusy }
            try expectEqual(terminations, 1, "The deferred cancellation eventually allows termination")
        }),
        ("quit waits for publication without cancelling it", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted"]))
            helper.holdApply = true
            var terminations = 0
            let model = makeTestModel(helper, terminateApplication: { terminations += 1 })
            installBatch(helper.detail, in: model)
            model.confirmApply()
            try await waitForModel { helper.applyContinuation != nil }
            model.quitApplication()
            try expectEqual(helper.cancelCalls, 0, "Quit must not cancel an in-flight publication")
            try expectEqual(terminations, 0, "Keep the app alive until publish reconciliation finishes")
            try expect(model.busyStatusMessage?.contains("Finishing GitHub sync") == true, "Explain why Quit is waiting")
            helper.completeApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(terminations, 1, "Terminate after the complete apply and refresh operation")
            try expectEqual(helper.listCalls, 1, "Publication's follow-up refresh is allowed to finish")
        }),
        ("quit waits for other workspace operations to finish", {
            let helper = ModelTestHelper(detail: modelBatch([]))
            helper.holdList = true
            var terminations = 0
            let model = makeTestModel(helper, terminateApplication: { terminations += 1 })
            model.refreshFromUI()
            try await waitForModel { helper.listContinuation != nil }
            model.quitApplication()
            try expectEqual(helper.cancelCalls, 0, "Read and maintenance operations are allowed to finish")
            try expectEqual(terminations, 0, "The app remains alive while a workspace operation runs")
            helper.completeList()
            try await waitForModel { !model.isBusy }
            try expectEqual(terminations, 1, "Terminate after the operation completes")
            model.refreshFromUI()
            try expectEqual(helper.listCalls, 1, "No new operation may start after Quit is queued")
        }),
        ("failed Git preview is rechecked after configuration is fixed", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted"]))
            helper.previews = [modelPreview(willPush: false), modelPreview(willPush: true)]
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.requestApply()
            try await waitForModel { !model.isBusy }
            try expectNil(model.currentApplyPreview, "A failed preview must not become a sticky cache entry")
            try expect(!model.isShowingApplyConfirmation, "Failed preflight must not open the push confirmation")
            model.requestApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.previewCalls, 2, "Retry must query the updated Git configuration")
            try expect(model.isShowingApplyConfirmation, "The corrected configuration can proceed to review")
        }),
        ("successful Git preview is also rechecked on the next attempt", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted"]))
            helper.previews = [modelPreview(willPush: true), modelPreview(willPush: false)]
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.requestApply()
            try await waitForModel { !model.isBusy }
            model.isShowingApplyConfirmation = false
            model.requestApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.previewCalls, 2, "External branch changes invalidate a previous success too")
            try expectNil(model.currentApplyPreview, "Stale publish eligibility is cleared")
        }),
        ("push success survives a subsequent results refresh failure", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted"]))
            helper.listError = AppTestFailure(message: "Review database unavailable")
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.confirmApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.applyCalls, 1, "The push happens exactly once")
            try expectEqual(model.statusTone, .warning, "A refresh failure is a warning after confirmed publication")
            try expect(model.statusMessage.contains("Synced to GitHub at verified-sha"), "Retain the confirmed commit as the leading outcome")
            try expect(!model.hasCurrentRun, "Published review rows are cleared")
        }),
        ("push cleanup warning retains the confirmed commit", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted"]))
            helper.applyWarning = "Published successfully, but local cleanup needs attention."
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.confirmApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .warning, "A helper cleanup warning must remain visible")
            try expect(model.statusMessage.contains("verified-sha") && model.statusMessage.contains("local cleanup"), "Report confirmed publication and the remaining cleanup work together")
        }),
        ("partial publication keeps failed and unreviewed rows in the same run", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted", "failed", "needs_review"], mode: "incremental"))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            helper.detail = modelBatch(["failed", "needs_review"], mode: "incremental", firstRecordID: 2)
            helper.remainingAfterApply = 2
            model.confirmApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.currentBatchID, 7, "Continue reviewing the original batch")
            try expectEqual(model.visibleCurrentRecords.map(\.id), [2, 3], "Keep the original IDs of unpublished records")
            try expectEqual(model.selectedRecord?.status, "failed", "The failed result remains directly retryable")
            try expect(model.statusMessage.contains("2 results remain for review"), "Do not imply the whole batch was published")
            try expectNil(model.currentApplyPreview, "The old acceptance preview is no longer valid")
        }),
        ("partial publication remains recoverable after cleanup and refresh warnings", {
            let helper = ModelTestHelper(detail: modelBatch(["accepted", "failed"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            helper.detail = modelBatch(["failed"], firstRecordID: 2)
            helper.remainingAfterApply = 1
            helper.applyWarning = "Local cleanup needs attention."
            helper.listError = AppTestFailure(message: "Review database unavailable")
            model.confirmApply()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.currentBatchID, 7, "Keep the batch address for Reload Results")
            try expectNil(model.currentBatchDetail, "Do not leave published acceptance rows visible after refresh failure")
            try expectEqual(model.statusTone, .warning, "Publication remains a confirmed success with follow-up warnings")
            try expect(model.statusMessage.contains("verified-sha") && model.statusMessage.contains("Local cleanup"), "Retain both confirmed publication and cleanup details")
            helper.listError = nil
            model.refreshFromUI()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.selectedRecord?.id, 2, "Reload restores the original remaining record")
        }),
        ("retry reloads the same failed record without starting a new batch", {
            let helper = ModelTestHelper(detail: modelBatch(["failed"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            helper.detail = modelBatch(["ready_for_review"])
            model.retrySelectedRecord()
            try await waitForModel { !model.isBusy }
            try expectEqual(helper.retryIDs, [1], "Retry must target the selected record")
            try expectEqual(helper.submitCalls, 0, "Retry must not create a separate manual import")
            try expectEqual(model.currentBatchID, 7, "Keep the current batch")
            try expectEqual(model.selectedRecord?.status, "ready_for_review", "Reload the revised record for review")
            try expectEqual(model.statusTone, .success, "A successful retry is clearly reported")
        }),
        ("a repeated extraction failure stays an error after retry", {
            let helper = ModelTestHelper(detail: modelBatch(["failed"]))
            let model = makeTestModel(helper)
            installBatch(helper.detail, in: model)
            model.retrySelectedRecord()
            try await waitForModel { !model.isBusy }
            try expectEqual(model.statusTone, .error, "Retry transport success does not imply successful extraction")
            try expect(model.canRetrySelectedRecord, "A failed retry remains retryable")
        }),
    ]
}

@MainActor
private func waitForModel(_ condition: () -> Bool) async throws {
    let deadline = Date().addingTimeInterval(3)
    while !condition() {
        if Date() >= deadline { throw AppTestFailure(message: "Timed out waiting for model operation") }
        try await Task.sleep(nanoseconds: 1_000_000)
    }
}

@MainActor
private func makeTestModel(_ helper: ModelTestHelper, terminateApplication: @escaping @MainActor () -> Void = { preconditionFailure("Unexpected app termination") }) -> AppModel {
    let selection = OpenAIModelSelection(preset: .gpt41, customModel: "")
    let preferences = AppModelPreferences(
        loadKey: { .found("offline-test-key") },
        saveKey: { _ in throw AppTestFailure(message: "Unexpected preferences write") },
        deleteKey: { throw AppTestFailure(message: "Unexpected preferences deletion") },
        loadModel: { selection },
        saveModel: { _ in }
    )
    return AppModel(helper: helper, preferences: preferences, terminateApplication: terminateApplication)
}

@MainActor
private func installBatch(_ detail: BatchDetailResponse, in model: AppModel) {
    model.currentBatchID = detail.batch.id
    model.currentBatchDetail = detail
    model.selectedRecordID = detail.records.first?.id
}

private func modelBatch(_ statuses: [String], mode: String = "manual", batchID: Int = 7, firstRecordID: Int = 1, effectiveFields: [String: String]? = nil, baselineFields: [String: String]? = nil, baselineAvailable: Bool? = nil) -> BatchDetailResponse {
    let records = statuses.enumerated().map { index, status in
        ProposedRecord(
            id: index + firstRecordID, batch_id: batchID, url: "https://eventstructure.com/work-\(index)", slug: "work-\(index)",
            status: status, page_type: "artwork", confidence: 0.9, is_update: false,
            title: "Work \(index)", title_cn: "", year: "", type: "", materials: "", size: "", duration: "", credits: "",
            description_en: "", description_cn: "", video_link: "", images: [], high_res_images: [],
            error_message: status == "failed" ? "AI request failed" : nil,
            baseline_fields: baselineFields, effective_fields: effectiveFields, baseline_available: baselineAvailable
        )
    }
    let accepted = statuses.filter { $0 == "accepted" }.count
    let failed = statuses.filter { $0 == "failed" }.count
    let deleted = statuses.filter { $0 == "rejected" }.count
    let pending = statuses.count - accepted - failed - deleted
    return BatchDetailResponse(
        batch: BatchSummary(id: batchID, mode: mode, status: "reviewing", total_records: records.count, accepted_records: accepted, ready_records: pending, last_error: ""),
        records: records, total_records: records.count, accepted_count: accepted, deleted_count: deleted,
        failed_count: failed, syncable_count: accepted, pending_count: pending
    )
}

private func modelPreview(willPush: Bool) -> ApplyPreview {
    ApplyPreview(batch_id: 7, accepted_count: 1, new_count: 1, updated_count: 0,
                 target_files: ["aaajiao_works.json"], will_push: willPush,
                 error_message: willPush ? "" : "Current branch does not match baseline branch")
}

@MainActor
private final class ModelTestHelper: ImporterHelper {
    var detail: BatchDetailResponse
    var detailsByID: [Int: BatchDetailResponse] = [:]
    var listedBatches: [BatchSummary] = []
    var previews: [ApplyPreview] = []
    var submitCalls = 0
    var syncCalls = 0
    var listCalls = 0
    var previewCalls = 0
    var applyCalls = 0
    var cancelCalls = 0
    var retryIDs: [Int] = []
    var acceptedIDs: [Int] = []
    var updatedFields: [[String: String]] = []
    var updateError: Error?
    var listError: Error?
    var applyWarning: String?
    var remainingAfterApply: Int?
    var holdSubmit = false
    var holdApply = false
    var holdList = false
    var submitContinuation: CheckedContinuation<SubmitURLResponse, Error>?
    var applyContinuation: CheckedContinuation<ApplyResponse, Error>?
    var listContinuation: CheckedContinuation<PendingRecordsResponse, Error>?

    init(detail: BatchDetailResponse) { self.detail = detail }

    func bootstrapWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        BootstrapResponse(settings: .empty, status: "baseline_synced")
    }
    func listPendingRecords(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> PendingRecordsResponse {
        listCalls += 1
        if let listError { throw listError }
        if holdList {
            return try await withCheckedThrowingContinuation { listContinuation = $0 }
        }
        return PendingRecordsResponse(settings: .empty, batches: listedBatches, pending_records: [])
    }
    func resetWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        throw AppTestFailure(message: "Unexpected workspace reset")
    }
    func refreshWorkspaceBaseline(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        throw AppTestFailure(message: "Unexpected baseline refresh")
    }
    func startIncrementalSync(openAIKey: String, openAIModel: String, openAIModelSource: String, onProgress: (@Sendable (HelperProgress) -> Void)?) async throws -> StartSyncResponse {
        syncCalls += 1
        return StartSyncResponse(batch_id: detail.batch.id, urls_processed: detail.total_records)
    }
    func submitManualURL(_ url: String, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> SubmitURLResponse {
        submitCalls += 1
        if holdSubmit {
            return try await withCheckedThrowingContinuation { submitContinuation = $0 }
        }
        return SubmitURLResponse(batch_id: detail.batch.id, url: url)
    }
    func completeSubmit() {
        submitContinuation?.resume(returning: SubmitURLResponse(batch_id: detail.batch.id, url: "https://eventstructure.com/work"))
        submitContinuation = nil
    }
    func completeCancellation() {
        submitContinuation?.resume(throwing: HelperClientError.cancelled)
        submitContinuation = nil
    }
    func cancelCurrentCommand() -> Bool {
        cancelCalls += 1
        return submitContinuation != nil
    }
    func completeApply() {
        applyContinuation?.resume(returning: ApplyResponse(batch_id: detail.batch.id, applied_commit_sha: "verified-sha", preview: modelPreview(willPush: true), warning_message: applyWarning, remaining_records: remainingAfterApply))
        applyContinuation = nil
    }
    func completeList() {
        listContinuation?.resume(returning: PendingRecordsResponse(settings: .empty, batches: [], pending_records: []))
        listContinuation = nil
    }
    func acceptRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        acceptedIDs.append(id)
        return RecordStatusResponse(id: id, status: "accepted")
    }
    func rejectRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        throw AppTestFailure(message: "Unexpected reject")
    }
    func retryRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        retryIDs.append(id)
        return RecordStatusResponse(id: id, status: detail.records.first(where: { $0.id == id })?.status ?? "failed")
    }
    func updateRecord(id: Int, fields: [String: String], openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        updatedFields.append(fields)
        if let updateError { throw updateError }
        return RecordStatusResponse(id: id, status: "needs_review")
    }
    func getBatchDetail(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BatchDetailResponse { detailsByID[batchID] ?? detail }
    func getApplyPreview(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyPreview {
        previewCalls += 1
        return previews.isEmpty ? modelPreview(willPush: true) : previews.removeFirst()
    }
    func applyAcceptedRecords(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyResponse {
        applyCalls += 1
        if holdApply {
            return try await withCheckedThrowingContinuation { applyContinuation = $0 }
        }
        return ApplyResponse(batch_id: batchID, applied_commit_sha: "verified-sha", preview: modelPreview(willPush: true), warning_message: applyWarning, remaining_records: remainingAfterApply)
    }
    func deleteBatch(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> DeleteBatchResponse {
        throw AppTestFailure(message: "Unexpected batch deletion")
    }
}
