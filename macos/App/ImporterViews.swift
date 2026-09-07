import AppKit
import SwiftUI

private let focusReviewSearchNotification = Notification.Name("AaajiaoImporter.FocusReviewSearch")

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            if model.shouldShowStatusBanner { ContextBannerView() }
            NavigationSplitView {
                SidebarView()
                    .navigationSplitViewColumnWidth(min: 250, ideal: 290, max: 350)
            } detail: {
                DetailColumnView()
                    .safeAreaInset(edge: .bottom, spacing: 0) {
                        if model.hasSelectedRecord { SelectionActionBar() }
                    }
            }
        }
        .frame(minWidth: 900, minHeight: 620)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button { model.requestImportSheet() } label: {
                    Label("Import URL…", systemImage: "plus")
                        .labelStyle(.titleOnly)
                }
                .disabled(!model.canOpenImportSheet)
                .help("Import one artwork URL (⌘N)")

                Button { model.startSync() } label: {
                    Label("Check for Updates", systemImage: "arrow.triangle.2.circlepath")
                        .labelStyle(.titleOnly)
                }
                .disabled(!model.canStartImport)
                .help("Find new and changed artworks on eventstructure.com for review (⇧⌘I)")
            }
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button { model.refreshFromUI() } label: { Label("Reload Review Queue", systemImage: "arrow.clockwise") }
                        .disabled(model.isBusy || model.isShowingRecordEditor)
                    Button { model.refreshWorkspaceBaseline() } label: { Label("Get Latest Published Data", systemImage: "arrow.down.circle") }
                        .disabled(!model.canRefreshBaseline)
                    Button { model.openWorkspaceFolderOrCopyPath() } label: { Label("Show Workspace in Finder", systemImage: "folder") }
                        .disabled(model.settings.workspace_path.isEmpty)
                    Divider()
                    Button("Discard Current Run…", role: .destructive) { model.requestDiscardCurrentRun() }
                        .disabled(!model.canDiscardCurrentRun)
                    Button("Reset Workspace…", role: .destructive) { model.requestWorkspaceReset() }
                        .disabled(model.isBusy || model.isShowingRecordEditor)
                } label: { Label("More", systemImage: "ellipsis.circle") }
                .labelStyle(.iconOnly)
                .accessibilityLabel("More workspace actions")
                .help("Workspace actions")
            }
            ToolbarItem(placement: .primaryAction) {
                Button { model.requestApply() } label: {
                    Label(model.gitHubSyncActionTitle, systemImage: "arrow.up.circle")
                        .labelStyle(.titleOnly)
                }
                .disabled(!model.canRequestGitHubSync)
                .help("Publish accepted artworks to GitHub (⇧⌘P)")
            }
        }
        .sheet(isPresented: $model.isShowingImportSheet) { ImportURLSheet().environmentObject(model) }
        .sheet(isPresented: $model.isShowingRecordEditor) { RecordEditorSheet().environmentObject(model) }
        .sheet(isPresented: $model.isShowingApplyConfirmation) { ApplyReviewSheet().environmentObject(model) }
        .alert("Reset the local workspace?", isPresented: $model.isShowingResetConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Reset Workspace", role: .destructive) { model.confirmWorkspaceReset() }
        } message: {
            Text("This removes all local review results and reloads published artwork data. Artworks already on GitHub are kept.")
        }
        .confirmationDialog("Discard the current review run?", isPresented: $model.isShowingDiscardConfirmation, titleVisibility: .visible) {
            Button("Discard Run", role: .destructive) { model.confirmDiscardCurrentRun() }
            Button("Cancel", role: .cancel) {}
        } message: { Text("This removes the current run's unpublished review results.") }
        .confirmationDialog("Remove this artwork from review?", isPresented: $model.isShowingDeleteConfirmation, titleVisibility: .visible) {
            Button("Remove from Queue", role: .destructive) { model.confirmDeleteSelectedRecord() }
            Button("Cancel", role: .cancel) {}
        } message: { Text("This removes the result from the review queue. Published artwork data is unchanged.") }
        .onAppear { model.bootstrapIfNeeded() }
    }

}

private struct SidebarView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow
    @FocusState private var isSearchFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Review Queue").font(.headline)
                    Spacer()
                    Text("\(model.visibleCurrentRecords.count)")
                        .foregroundStyle(.secondary).monospacedDigit()
                }
                if !model.availableBatches.isEmpty {
                    Menu {
                        ForEach(model.availableBatches) { batch in
                            Button("\(batch.mode == "manual" ? "URL import" : "Site sync") · Run \(batch.id)") {
                                model.selectBatch(id: batch.id)
                            }
                        }
                    } label: {
                        HStack {
                            Label(model.hasCurrentRun ? model.currentRunTitle : "Choose review run", systemImage: "tray")
                            Spacer(minLength: 4)
                            if let id = model.currentBatchID { Text("#\(id)").foregroundStyle(.secondary) }
                        }
                    }
                    .disabled(model.isBusy || model.isShowingRecordEditor)
                    .accessibilityLabel("Choose review run")
                }
                if let detail = model.currentBatchDetail, !model.visibleCurrentRecords.isEmpty {
                    HStack(spacing: 12) {
                        QueueCount(title: "To review", count: detail.pending_count, tint: .secondary)
                        QueueCount(title: "Accepted", count: detail.accepted_count, tint: .green)
                        QueueCount(title: "Failed", count: detail.failed_count, tint: .orange)
                    }
                    Text(model.reviewGuidance)
                        .font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !model.visibleCurrentRecords.isEmpty {
                    TextField("Search title or URL", text: $model.searchText)
                        .textFieldStyle(.roundedBorder)
                        .focused($isSearchFocused)
                        .accessibilityLabel("Search review queue")
                    HStack {
                        Picker("Show", selection: $model.reviewFilter) {
                            ForEach(ReviewFilter.allCases) { filter in Text(filter.title).tag(filter) }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .accessibilityLabel("Filter review status")
                        Spacer()
                        Text("\(model.filteredCurrentRecords.count) shown")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(16)
            Divider()
            List(selection: $model.selectedRecordID) {
                ForEach(model.filteredCurrentRecords) { record in
                    ReviewQueueRow(record: record, isSelected: model.selectedRecordID == record.id).tag(record.id)
                }
            }
            .listStyle(.sidebar)
            .overlay {
                if model.filteredCurrentRecords.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: model.visibleCurrentRecords.isEmpty ? "tray" : "line.3.horizontal.decrease.circle")
                            .font(.title2).foregroundStyle(.secondary)
                        Text(model.visibleCurrentRecords.isEmpty ? "No artworks in review" : "No matching results")
                            .font(.headline)
                        Text(model.visibleCurrentRecords.isEmpty ? "Imported artworks will appear here." : "Try a different search or status filter.")
                            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        if !model.visibleCurrentRecords.isEmpty && (!model.searchText.isEmpty || model.reviewFilter != .all) {
                            Button("Clear Filters") { model.searchText = ""; model.reviewFilter = .all }
                        }
                    }
                    .padding(20)
                }
            }
            Divider()
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    if let url = model.baselineCommitURL {
                        Link(destination: url) { Label("Published data", systemImage: "arrow.down.circle") }
                            .help("View the published data used for comparison")
                        Spacer()
                        Text(String((model.settings.baseline_commit ?? "").prefix(7)))
                            .foregroundStyle(.secondary).monospaced()
                    } else { Text(baselineLabel(model.settings.baseline_status)) }
                }
                Button { presentSettingsWindow(openWindow) } label: {
                    Label(openAIKeyTitle, systemImage: model.hasAuthenticationError ? "key.slash" : "gearshape")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .foregroundStyle(model.hasAuthenticationError ? Color.red : Color.secondary)
                .help(openAIKeyLabel)
                .accessibilityLabel("Settings. \(openAIKeyLabel)")
                if model.hasBaselineWarning {
                    Text(baselineDetail(model.settings)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            .font(.caption).padding(14)
        }
        .navigationTitle("Importer")
        .onReceive(NotificationCenter.default.publisher(for: focusReviewSearchNotification)) { _ in
            isSearchFocused = true
        }
    }

    private var openAIKeyLabel: String {
        if model.hasAuthenticationError { return "OpenAI API key rejected. Open Settings to update it." }
        if model.hasVerifiedOpenAIKey { return "OpenAI account access verified. Model permissions are checked during import." }
        return model.hasSavedOpenAIKey ? "OpenAI key saved; access has not been checked." : "OpenAI key required"
    }

    private var openAIKeyTitle: String {
        if !model.openAIAccessErrorMessage.isEmpty { return "API needs attention · Settings…" }
        if model.hasVerifiedOpenAIKey { return "API checked · Settings…" }
        return model.hasSavedOpenAIKey ? "API key saved · Settings…" : "Set up API key…"
    }
}

private struct QueueCount: View {
    let title: String
    let count: Int
    let tint: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("\(count)").font(.title3.weight(.semibold)).monospacedDigit().foregroundStyle(tint)
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

private struct ReviewQueueRow: View {
    let record: ProposedRecord
    let isSelected: Bool
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: recordStatusSymbol(record.status))
                .foregroundStyle(isSelected ? Color.primary : recordStatusTint(record.status)).frame(width: 16).padding(.top, 2)
            VStack(alignment: .leading, spacing: 5) {
                Text(record.displayTitle).font(.body.weight(.medium)).lineLimit(2)
                if !record.title_cn.isEmpty && record.title_cn != record.displayTitle {
                    Text(record.title_cn).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                HStack(spacing: 5) {
                    Text(recordStatusLabel(record.status))
                    if !record.year.isEmpty { Text("· \(record.year)") }
                }
                .font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 7)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(record.displayTitle), \(recordStatusLabel(record.status))")
    }
}

private struct DetailColumnView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        Group {
            if let record = model.selectedRecord {
                RecordDetailView(record: record).id(record.id)
            } else {
                ReviewEmptyView()
            }
        }
    }
}

private struct ReviewEmptyView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    private var hasHiddenRecords: Bool { !model.visibleCurrentRecords.isEmpty }
    private var isImporting: Bool { model.isImportingURL || model.isSyncingSite }
    private var hasNoUpdates: Bool {
        model.hasCompletedEmptySiteCheck && !model.isBusy
    }
    private var publicationNeedsAttention: Bool {
        guard let publication = model.lastPublication else { return false }
        return publication.needsLocalCleanup || publication.remainingCount == nil
    }

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: symbol)
                .font(.system(size: 36, weight: .light)).foregroundStyle(.secondary)
                .accessibilityHidden(true)
            VStack(spacing: 10) {
                Text(title).font(.title2.weight(.semibold))
                Text(description).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !model.isBusy {
                if hasHiddenRecords {
                    if model.filteredCurrentRecords.isEmpty {
                        Button("Show All Results") { model.searchText = ""; model.reviewFilter = .all }
                    } else if model.canSelectNextPendingRecord {
                        Button("Review Next Artwork") { model.selectNextPendingRecord() }
                            .buttonStyle(.borderedProminent)
                    }
                    if model.canRequestGitHubSync {
                        Button(model.gitHubSyncActionTitle) { model.requestApply() }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    if !hasNoUpdates, let publication = model.lastPublication {
                        if let url = publication.commitURL {
                            Link(destination: url) { Label("View on GitHub", systemImage: "arrow.up.right.square") }
                        }
                    }
                    if publicationNeedsAttention {
                        Button("Reload Review Queue") { model.refreshFromUI() }
                            .buttonStyle(.borderedProminent)
                    } else if !model.canRunProtectedActions || model.hasAuthenticationError {
                        Button(model.hasAuthenticationError ? "Open Settings…" : "Set Up API Key…") { presentSettingsWindow(openWindow) }
                            .buttonStyle(.borderedProminent)
                    } else {
                        HStack(spacing: 12) {
                            Button("Check for Updates") { model.startSync() }
                                .buttonStyle(.borderedProminent).disabled(!model.canStartImport)
                            Button("Import URL…") { model.requestImportSheet() }
                                .disabled(!model.canOpenImportSheet)
                        }
                    }
                    if model.lastPublication == nil && !hasNoUpdates {
                        VStack(alignment: .leading, spacing: 12) {
                            workflowStep("1", title: "Import", detail: "Find website updates or add one artwork URL.")
                            workflowStep("2", title: "Review", detail: "Check the details, edit if needed, then accept.")
                            workflowStep("3", title: "Publish", detail: "Upload accepted artworks to GitHub.")
                        }
                        .padding(.top, 12)
                    }
                }
            }
        }
        .frame(maxWidth: 440)
        .padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func workflowStep(_ number: String, title: String, detail: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text(number).font(.callout.monospacedDigit()).foregroundStyle(.tertiary)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.callout.weight(.medium))
                Text(detail).font(.callout).foregroundStyle(.secondary)
            }
        }.accessibilityElement(children: .combine)
    }

    private var symbol: String {
        if isImporting { return "tray.and.arrow.down" }
        if hasHiddenRecords { return "sidebar.left" }
        return hasNoUpdates || model.lastPublication != nil ? "checkmark.circle" : "tray.and.arrow.down"
    }
    private var title: String {
        if isImporting { return "Your results will appear here" }
        if hasHiddenRecords { return model.filteredCurrentRecords.isEmpty ? "No matching results" : "Choose an artwork to review" }
        if hasNoUpdates { return "No new website updates found" }
        if let publication = model.lastPublication { return publication.title }
        return "Bring your artwork archive up to date"
    }
    private var description: String {
        if isImporting { return "You can review each artwork after the import finishes." }
        if hasHiddenRecords { return model.reviewGuidance }
        if hasNoUpdates { return "This check found no new or changed artwork pages to import. You can still import a specific URL." }
        if let publication = model.lastPublication { return "\(publication.changesDescription). \(publication.nextStep)" }
        return "Import from eventstructure.com, review locally, and publish when you are ready."
    }
}

private struct RecordDetailView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow
    let record: ProposedRecord
    @State private var showChanges = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 8) {
                        Label(recordStatusLabel(record.status), systemImage: recordStatusSymbol(record.status))
                            .foregroundStyle(recordStatusTint(record.status))
                        Text("·").foregroundStyle(.tertiary)
                        Text(record.is_update ? "Artwork update" : "New artwork").foregroundStyle(.secondary)
                        Spacer()
                        if record.confidence > 0 {
                            Text("Confidence \(record.confidence, format: .percent.precision(.fractionLength(0)))")
                                .foregroundStyle(.secondary)
                                .help("AI confidence is a review hint; verify the artwork details before accepting.")
                        }
                    }
                    .font(.caption)
                    Text(record.displayTitle).font(.largeTitle.weight(.semibold)).textSelection(.enabled)
                    if !record.title_cn.isEmpty && record.title_cn != record.displayTitle {
                        Text(record.title_cn).font(.title3).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                    if let url = webURL(record.url) {
                        Link(destination: url) { Label(record.url, systemImage: "arrow.up.right.square").lineLimit(1) }
                            .font(.callout)
                    }
                }

                if let message = record.error_message, !message.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Label(record.error_code == "openai_authentication_failed" ? "OpenAI API key rejected" : (record.status == "failed" ? "Import failed" : "Review note"), systemImage: "exclamationmark.bubble")
                            .font(.headline)
                        Text(message).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                        HStack {
                            if record.error_code == "openai_authentication_failed" || record.error_code == "openai_permission_denied" {
                                Button("Open Settings") { presentSettingsWindow(openWindow) }
                            }
                            if record.status == "failed" || record.error_code == "openai_authentication_failed" || record.error_code == "openai_permission_denied" {
                                Button("Retry Import") { model.retrySelectedRecord() }
                                    .disabled(!model.canRetrySelectedRecord)
                            }
                        }
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }

                Picker("Review view", selection: $showChanges) {
                    Text("Details").tag(false)
                    Text("Changes").tag(true)
                }
                .pickerStyle(.segmented).labelsHidden().frame(maxWidth: 260)

                if showChanges {
                    RecordChangesView(record: record)
                } else {
                    if !record.images.isEmpty || !record.high_res_images.isEmpty {
                        ArtworkImagesView(record: record)
                    }
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Artwork details").font(.headline)
                        ForEach(RecordField.allCases.filter { ["year", "type", "materials", "size", "duration", "credits"].contains($0.rawValue) }) { field in
                            if !record.value(for: field).isEmpty {
                                LabeledContent(field.label) {
                                    Text(record.value(for: field)).multilineTextAlignment(.trailing).textSelection(.enabled)
                                }
                            }
                        }
                        if let video = webURL(record.video_link) {
                            LabeledContent("Video") { Link("Open video", destination: video) }
                        }
                    }
                    if !record.description_en.isEmpty { DescriptionBlock(title: "Description · English", text: record.description_en) }
                    if !record.description_cn.isEmpty { DescriptionBlock(title: "Description · 中文", text: record.description_cn) }
                }

                if let history = record.error_history, !history.isEmpty {
                    DisclosureGroup("Import history · \(history.count) issue\(history.count == 1 ? "" : "s")") {
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(Array(history.enumerated()), id: \.offset) { _, entry in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(entry.at).font(.caption).foregroundStyle(.secondary)
                                    Text(entry.message).font(.callout).textSelection(.enabled)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 10)
                    }
                    .font(.callout)
                }
            }
            .frame(maxWidth: 880, alignment: .leading)
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .onAppear { showChanges = record.is_update && record.status != "failed" }
        .navigationTitle("Importer")
    }
}

private struct DescriptionBlock: View {
    let title: String
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.headline)
            Text(text).lineSpacing(4).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ArtworkImagesView: View {
    let record: ProposedRecord
    private var links: [String] {
        var seen = Set<String>()
        return (record.images.isEmpty ? record.high_res_images : record.images).filter { seen.insert($0).inserted }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Images").font(.headline)
                Text("\(links.count)").foregroundStyle(.secondary).font(.callout)
            }
            ScrollView(.horizontal) {
                LazyHStack(spacing: 12) {
                    ForEach(Array(links.enumerated()), id: \.offset) { index, link in
                        if let url = webURL(link) {
                            Link(destination: url) {
                                VStack(alignment: .leading, spacing: 6) {
                                    AsyncImage(url: url) { phase in
                                        switch phase {
                                        case .success(let image):
                                            image.resizable().scaledToFit()
                                        case .failure:
                                            VStack(spacing: 6) {
                                                Image(systemName: "photo").font(.title2)
                                                Text("Open original").font(.caption)
                                            }.foregroundStyle(.secondary)
                                        case .empty: ProgressView().controlSize(.small)
                                        @unknown default: Image(systemName: "photo")
                                        }
                                    }
                                    .frame(width: 164, height: 124)
                                    .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                                    .clipShape(RoundedRectangle(cornerRadius: 8))
                                    Text("Image \(index + 1)").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Open artwork image \(index + 1)")
                        }
                    }
                }.padding(.bottom, 4)
            }
            DisclosureGroup("Image URLs and full-resolution originals") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array((record.images + record.high_res_images).enumerated()), id: \.offset) { index, link in
                        if let url = webURL(link) {
                            Link("\(index + 1). \(link)", destination: url).font(.caption)
                        } else {
                            Text("\(index + 1). \(link)").font(.caption).textSelection(.enabled)
                        }
                    }
                }.padding(.top, 8).frame(maxWidth: .infinity, alignment: .leading)
            }.font(.caption)
        }
    }
}

private struct RecordChangesView: View {
    let record: ProposedRecord
    private var changedFields: [RecordField] {
        RecordField.allCases.filter { record.value(for: $0) != (record.baselineValue(for: $0) ?? "") }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if record.is_update && record.baseline_available != true {
                Label("Original baseline unavailable", systemImage: "exclamationmark.triangle")
                    .font(.headline).foregroundStyle(.orange)
                Text("This result was imported before baseline snapshots were saved. Re-import it to compare against the current artwork data.")
                    .foregroundStyle(.secondary)
            } else if changedFields.isEmpty {
                Label("No field changes", systemImage: "checkmark.circle")
                    .font(.headline).foregroundStyle(.secondary)
                Text("The reviewed fields match the saved baseline.").foregroundStyle(.secondary)
            } else {
                Text(record.is_update ? "\(changedFields.count) changed fields" : "New artwork · \(changedFields.count) populated fields")
                    .font(.headline)
                Text("Compare the saved baseline with the values this result will publish. You can correct fields before accepting.")
                    .foregroundStyle(.secondary).font(.callout)
                ForEach(changedFields) { field in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(field.label).font(.headline)
                        if record.is_update {
                            ComparisonValue(title: "BASELINE", value: record.baselineValue(for: field) ?? "", isProposed: false)
                        }
                        ComparisonValue(title: "PROPOSED", value: record.value(for: field), isProposed: true)
                    }
                    .padding(.vertical, 8)
                    Divider()
                }
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ComparisonValue: View {
    let title: String
    let value: String
    let isProposed: Bool
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(title).font(.caption2.weight(.medium)).foregroundStyle(.secondary).frame(width: 72, alignment: .leading).padding(.top, 2)
            Text(value.isEmpty ? (isProposed ? "Empty / removed" : "Not set") : value)
                .foregroundStyle(value.isEmpty ? Color.secondary : Color.primary)
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12)
        .background(isProposed ? Color.accentColor.opacity(0.07) : Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
        .accessibilityElement(children: .combine)
    }
}

private struct SelectionActionBar: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.selectedRecord?.status == "accepted" {
                Label("Accepted locally. Publish to add this artwork to GitHub.", systemImage: "checkmark.circle")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 10) {
                Menu {
                    Button { model.openSelectedRecordSourcePage() } label: { Label("Open Source Page", systemImage: "arrow.up.right.square") }
                    Button {
                        guard let record = model.selectedRecord else { return }
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(record.url, forType: .string)
                    } label: { Label("Copy URL", systemImage: "doc.on.doc") }
                } label: { Label("More artwork actions", systemImage: "ellipsis") }
                .labelStyle(.iconOnly)
                .help("Open the source page or copy its URL")
                .accessibilityLabel("More artwork actions")
                .fixedSize()
                Button("Remove…", role: .destructive) { model.requestDeleteSelectedRecord() }
                    .disabled(!model.canDeleteSelectedRecord)
                    .help("Remove this artwork from the review queue")
                Spacer(minLength: 8)
                Button("Edit Fields…") { model.beginEditingSelectedRecord() }
                    .disabled(!model.canEditSelectedRecord)
                if model.selectedRecord?.status == "failed" || model.selectedRecord?.error_code == "openai_authentication_failed" || model.selectedRecord?.error_code == "openai_permission_denied" {
                    Button("Retry Import") { model.retrySelectedRecord() }
                        .buttonStyle(.borderedProminent).disabled(!model.canRetrySelectedRecord)
                } else if model.selectedRecord?.status == "accepted" {
                    if model.canSelectNextPendingRecord {
                        Button("Review Next") { model.selectNextPendingRecord() }
                            .buttonStyle(.borderedProminent)
                            .help("Show the next artwork awaiting review")
                    } else {
                        Button(model.gitHubSyncActionTitle) { model.requestApply() }
                            .buttonStyle(.borderedProminent).disabled(!model.canRequestGitHubSync)
                    }
                } else {
                    Button(model.acceptActionTitle) { model.acceptSelectedRecord() }
                        .buttonStyle(.borderedProminent).disabled(!model.canAcceptSelectedRecord)
                        .help("Accept this artwork for publishing (⌘Return)")
                }
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 14).background(.bar)
    }
}

private struct ContextBannerView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        HStack(spacing: 12) {
            if model.isBusy { ProgressView().controlSize(.small) }
            else { Image(systemName: icon).foregroundStyle(tint) }
            VStack(alignment: .leading, spacing: 4) {
                if let busy = model.busyStatusMessage {
                    Text(busy).font(.callout.weight(.medium))
                    if let progress = model.syncProgress, progress.total > 0 {
                        ProgressView(value: Double(progress.completed), total: Double(progress.total)).frame(maxWidth: 240)
                    }
                    if !model.syncCurrentURL.isEmpty {
                        Text(model.syncCurrentURL).font(.caption).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                    }
                    if model.canCancelCurrentImport {
                        Text("Stopping keeps completed results for review.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else {
                    Text(message).font(.callout).textSelection(.enabled)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
            if model.canCancelCurrentImport {
                Button("Stop Import") { model.cancelCurrentImport() }
            } else if model.isCancellingImport {
                Text("Stopping…").font(.caption).foregroundStyle(.secondary)
            }
            if !model.hasSavedOpenAIKey || !model.openAIAccessErrorMessage.isEmpty {
                Button("Settings…") { presentSettingsWindow(openWindow) }
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 10)
        .fixedSize(horizontal: false, vertical: true)
        .layoutPriority(1)
        .background(Color(nsColor: .controlBackgroundColor))
    }
    private var message: String {
        if !model.openAIAccessErrorMessage.isEmpty { return model.openAIAccessErrorMessage }
        if model.hasKeychainAccessFailure { return "The OpenAI key could not be read. Unlock Keychain and try again." }
        if !model.hasSavedOpenAIKey { return "Add your OpenAI key in Settings to import and validate artworks." }
        return model.statusMessage
    }
    private var tint: Color {
        if !model.openAIAccessErrorMessage.isEmpty { return .red }
        if !model.hasSavedOpenAIKey { return .orange }
        switch model.statusTone {
        case .error: return .red
        case .warning: return .orange
        case .success: return .green
        default: return .secondary
        }
    }
    private var icon: String {
        if model.hasAuthenticationError { return "key.slash" }
        if !model.openAIAccessErrorMessage.isEmpty { return "exclamationmark.triangle" }
        if !model.hasSavedOpenAIKey { return "key" }
        switch model.statusTone {
        case .error: return "xmark.circle"
        case .warning: return "exclamationmark.triangle"
        case .success: return "checkmark.circle"
        default: return "info.circle"
        }
    }
}

private struct ImportURLSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow
    @FocusState private var isFieldFocused: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("Import artwork", systemImage: "plus.circle").font(.title2.weight(.semibold))
            Text("Paste an eventstructure.com artwork URL. The result will be saved for your review.").foregroundStyle(.secondary)
            TextField("https://eventstructure.com/artwork", text: $model.manualURL)
                .textFieldStyle(.roundedBorder).focused($isFieldFocused)
                .disabled(model.isImportingURL)
                .onSubmit { if model.canSubmitManualURL { model.submitURL() } }
            if let message = model.manualURLValidationMessage {
                Label(message, systemImage: "exclamationmark.circle").font(.callout).foregroundStyle(.orange)
            }
            if !model.canRunProtectedActions {
                HStack {
                    Text("Set up an OpenAI key to enable import.").font(.callout).foregroundStyle(.secondary)
                    Spacer()
                    Button("Open Settings…") {
                        model.cancelImportSheet()
                        presentSettingsWindow(openWindow)
                    }
                }
            }
            if model.isImportingURL {
                HStack { ProgressView().controlSize(.small); Text(model.isCancellingImport ? "Stopping import…" : "Importing and validating artwork…") }
                    .font(.callout)
            } else if model.statusTone == .error {
                Text(model.statusMessage).font(.callout).foregroundStyle(.red).textSelection(.enabled)
            }
            HStack {
                Button(model.isImportingURL ? "Stop Import" : "Cancel", role: .cancel) {
                    if model.isImportingURL { model.cancelCurrentImport() } else { model.cancelImportSheet() }
                }
                .disabled(model.isImportingURL && !model.canCancelCurrentImport)
                .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Import") { model.submitURL() }
                    .buttonStyle(.borderedProminent).disabled(!model.canSubmitManualURL)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 500)
        .interactiveDismissDisabled(model.isImportingURL)
        .onAppear { isFieldFocused = true }
    }
}

private struct RecordEditorSheet: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Edit artwork fields").font(.title2.weight(.semibold))
                    Text("Saved corrections return to review. Accept the result when you are ready to publish.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
            }.padding(24)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(RecordField.allCases) { field in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(field.label).font(.headline)
                            if field.isMultiline {
                                TextEditor(text: binding(for: field))
                                    .font(.body).frame(minHeight: field.rawValue.hasPrefix("description") ? 110 : 64)
                                    .padding(5)
                                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.25)))
                                    .accessibilityLabel(field.label)
                            } else {
                                TextField(field.label, text: binding(for: field)).textFieldStyle(.roundedBorder)
                                    .accessibilityLabel(field.label)
                            }
                            if ["images", "high_res_images"].contains(field.rawValue) {
                                Text("One image URL per line. Remove a line to remove that image.").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }.padding(24)
            }
            .disabled(model.isBusy)
            Divider()
            HStack {
                Button("Cancel", role: .cancel) { model.cancelRecordEditing() }
                    .disabled(model.isBusy).keyboardShortcut(.cancelAction)
                Text(model.recordEditorError).font(.caption).foregroundStyle(.red).lineLimit(3)
                Spacer()
                if model.isBusy { ProgressView().controlSize(.small) }
                Button("Save for Review") { model.saveRecordEdits() }
                    .buttonStyle(.borderedProminent).disabled(!model.canSaveRecordEdits)
                    .keyboardShortcut("s", modifiers: .command)
            }.padding(20)
        }
        .frame(width: 640, height: 680)
        .interactiveDismissDisabled()
    }
    private func binding(for field: RecordField) -> Binding<String> {
        Binding(get: { model.recordEditorValues[field.rawValue] ?? "" }, set: { model.recordEditorValues[field.rawValue] = $0 })
    }
}

private struct ApplyReviewSheet: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Label("Publish accepted artworks", systemImage: "arrow.up.circle").font(.title2.weight(.semibold))
            if let preview = model.currentApplyPreview {
                HStack(spacing: 28) {
                    QueueCount(title: "Accepted", count: preview.accepted_count, tint: .primary)
                    QueueCount(title: "New", count: preview.new_count, tint: .primary)
                    QueueCount(title: "Updates", count: preview.updated_count, tint: .primary)
                }
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(model.visibleCurrentRecords.filter { $0.status == "accepted" }) { record in
                            HStack(alignment: .firstTextBaseline) {
                                Text(record.displayTitle).lineLimit(2)
                                Spacer()
                                Text(record.is_update ? "Update" : "New").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 150)
                .accessibilityLabel("Artworks included in this publication")
                LabeledContent("Branch", value: model.settings.baseline_branch ?? "main")
                if let remote = model.settings.baseline_source_url, !remote.isEmpty {
                    LabeledContent("Repository") { Text(remote).font(.callout).multilineTextAlignment(.trailing).textSelection(.enabled) }
                }
                Text("These accepted artworks will be published to GitHub. If the same artwork changed there, publication stops so you can review the conflict.")
                    .font(.callout).foregroundStyle(.secondary)
                if (model.currentBatchDetail?.pending_count ?? 0) + (model.currentBatchDetail?.failed_count ?? 0) > 0 {
                    Label("Unreviewed and failed results will stay in this queue.", systemImage: "tray")
                        .font(.callout).foregroundStyle(.secondary)
                }
                DisclosureGroup("\(preview.target_files.count) files will be updated") {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(preview.target_files, id: \.self) { path in
                            Text(URL(fileURLWithPath: path).lastPathComponent).font(.callout.monospaced())
                        }
                    }.padding(.top, 8)
                }.font(.callout)
            }
            HStack {
                Button("Cancel", role: .cancel) { model.isShowingApplyConfirmation = false }
                    .disabled(model.isBusy).keyboardShortcut(.cancelAction)
                Spacer()
                if model.isSyncingGitHub { ProgressView().controlSize(.small) }
                Button(model.isSyncingGitHub ? "Publishing…" : "Publish to GitHub") { model.confirmApply() }
                    .buttonStyle(.borderedProminent).disabled(!model.canConfirmGitHubSync)
                    .keyboardShortcut(.defaultAction)
            }
            if model.statusTone == .error && !model.isBusy {
                Text(model.statusMessage).font(.callout).foregroundStyle(.red).textSelection(.enabled)
            }
        }.padding(28).frame(width: 520)
        .interactiveDismissDisabled(model.isBusy)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    SecureField("API key", text: $model.settingsDraftOpenAIKey)
                    Picker("Model", selection: $model.settingsDraftOpenAIModelPreset) {
                        ForEach(OpenAIModelPreset.allCases) { preset in Text(preset.displayName).tag(preset) }
                    }
                    if model.settingsDraftOpenAIModelPreset == .custom {
                        TextField("Custom model", text: $model.settingsDraftCustomOpenAIModel)
                    }
                    HStack {
                        Button("Check API Key") { model.checkOpenAIKey() }
                            .disabled(!model.canCheckOpenAIKey)
                        if model.isCheckingOpenAIKey { ProgressView().controlSize(.small) }
                    }
                } header: { Text("OpenAI") } footer: {
                    VStack(alignment: .leading, spacing: 6) {
                        if !model.keyValidationMessage.isEmpty {
                            Text(model.keyValidationMessage)
                                .foregroundStyle(model.keyValidationTone == .error ? Color.red : (model.keyValidationTone == .success ? Color.green : Color.secondary))
                                .textSelection(.enabled)
                        }
                        if !model.canSaveSettings {
                            Text("Enter a custom model name to enable Save.").foregroundStyle(.orange)
                        }
                        if model.isSettingsDirty {
                            Text("Unsaved changes. Check tests the key shown above; Save & Close uses it for future imports.")
                        }
                        Text("Your API key is stored in macOS Keychain. Model selection is saved on this Mac.")
                    }
                }
                Section("About") {
                    LabeledContent("Version", value: AppVersionInfo.current.valueText)
                    Text("Import, review, and publish artwork records from a local workspace.")
                        .foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
            .disabled(model.isBusy || model.isShowingRecordEditor)
            Divider()
            if !model.settingsStatusMessage.isEmpty && model.settingsStatusMessage != model.keyValidationMessage {
                Text(model.settingsStatusMessage).font(.callout).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading).padding([.horizontal, .top], 20)
            }
            HStack {
                Button("Remove Key", role: .destructive) { model.clearSavedKey() }
                    .disabled(!model.hasSavedOpenAIKey && model.trimmedDraftOpenAIKey.isEmpty)
                Spacer()
                Button("Revert Changes") { model.revertSettings() }.disabled(!model.isSettingsDirty)
                Button(model.isSettingsDirty ? "Save & Close" : "Done") {
                    if model.saveSettings() { closeSettingsWindow() }
                }
                .buttonStyle(.borderedProminent).disabled(!model.canSaveSettings)
                .keyboardShortcut(.defaultAction)
            }
            .padding(20).disabled(model.isBusy || model.isShowingRecordEditor)
        }
        .frame(width: 540, height: 500)
    }
}

struct MenuBarMenuView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        Text(model.busyStatusMessage ?? model.reviewStatusValue)
        Button { presentImporterWindow(openWindow) } label: { Label("Open Importer", systemImage: "sidebar.left") }
        Button { presentImporterWindow(openWindow); model.requestImportSheet() } label: { Label("Import URL…", systemImage: "plus") }
            .disabled(!model.canOpenImportSheet)
        Button { presentImporterWindow(openWindow); model.startSync() } label: { Label("Check for Updates", systemImage: "arrow.triangle.2.circlepath") }
            .disabled(!model.canStartImport)
        if model.canCancelCurrentImport { Button("Stop Import") { model.cancelCurrentImport() } }
        Divider()
        Button { presentSettingsWindow(openWindow) } label: { Label("Settings…", systemImage: "gearshape") }
        Text(AppVersionInfo.current.menuText)
        Button("Quit aaajiao Importer") { model.quitApplication() }
    }
}

struct AppCommands: Commands {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") { presentSettingsWindow(openWindow) }.keyboardShortcut(",", modifiers: .command)
        }
        CommandGroup(replacing: .newItem) {
            Button("Import URL…") { presentImporterWindow(openWindow); model.requestImportSheet() }
                .keyboardShortcut("n", modifiers: .command).disabled(!model.canOpenImportSheet)
        }
        CommandGroup(after: .textEditing) {
            Button("Find in Review Queue") { NotificationCenter.default.post(name: focusReviewSearchNotification, object: nil) }
                .keyboardShortcut("f", modifiers: .command)
                .disabled(model.isShowingRecordEditor || model.isShowingImportSheet || model.isShowingApplyConfirmation)
        }
        CommandMenu("Actions") {
            Button("Reload Review Queue") { model.refreshFromUI() }
                .keyboardShortcut("r", modifiers: .command).disabled(model.isBusy || model.isShowingRecordEditor)
            Button("Check for Updates") { presentImporterWindow(openWindow); model.startSync() }
                .keyboardShortcut("i", modifiers: [.command, .shift]).disabled(!model.canStartImport)
            Button("Stop Import") { model.cancelCurrentImport() }.disabled(!model.canCancelCurrentImport)
            Divider()
            Button("Get Latest Published Data") { model.refreshWorkspaceBaseline() }
                .keyboardShortcut("r", modifiers: [.command, .option]).disabled(!model.canRefreshBaseline)
            Button("Publish Accepted Artworks…") { presentImporterWindow(openWindow); model.requestApply() }
                .keyboardShortcut("p", modifiers: [.command, .shift]).disabled(!model.canRequestGitHubSync)
        }
        CommandMenu("Review") {
            Button(model.acceptActionTitle) { model.acceptSelectedRecord() }
                .keyboardShortcut(.return, modifiers: .command).disabled(!model.canAcceptSelectedRecord)
            Button("Review Next Artwork") { model.selectNextPendingRecord() }
                .keyboardShortcut("]", modifiers: [.command, .option]).disabled(!model.canSelectNextPendingRecord)
            Button("Edit Fields…") { model.beginEditingSelectedRecord() }
                .keyboardShortcut("e", modifiers: .command).disabled(!model.canEditSelectedRecord)
            Button("Retry Import") { model.retrySelectedRecord() }
                .keyboardShortcut("r", modifiers: [.command, .shift]).disabled(!model.canRetrySelectedRecord)
            Divider()
            Button("Open Source Page") { model.openSelectedRecordSourcePage() }
                .disabled(model.selectedRecordSourceURL == nil)
            Button("Remove from Review Queue…") { model.requestDeleteSelectedRecord() }
                .keyboardShortcut(.delete, modifiers: .command).disabled(!model.canDeleteSelectedRecord)
        }
        CommandGroup(replacing: .appTermination) {
            Button("Quit aaajiao Importer") { model.quitApplication() }.keyboardShortcut("q", modifiers: .command)
        }
    }
}

private func webURL(_ value: String) -> URL? {
    guard let url = URL(string: value), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme), url.host != nil else { return nil }
    return url
}

private func recordStatusLabel(_ status: String) -> String {
    switch status {
    case "accepted": return "Accepted"
    case "needs_review", "ready_for_review": return "To review"
    case "failed": return "Failed"
    default: return status.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
private func recordStatusSymbol(_ status: String) -> String {
    switch status {
    case "accepted": return "checkmark.circle.fill"
    case "failed": return "exclamationmark.circle"
    case "needs_review": return "circle.lefthalf.filled"
    default: return "circle"
    }
}
private func recordStatusTint(_ status: String) -> Color {
    switch status {
    case "accepted": return .green
    case "failed", "needs_review": return .orange
    default: return .secondary
    }
}
private func baselineLabel(_ status: String?) -> String {
    switch status {
    case "synced": return "GitHub baseline"
    case "seed_fallback": return "Bundled baseline"
    case "sync_skipped_pending_review": return "Review baseline protected"
    default: return "Baseline unavailable"
    }
}
private func baselineDetail(_ settings: AppSettings) -> String {
    if let error = settings.baseline_error, !error.isEmpty { return error }
    if settings.baseline_status == "sync_skipped_pending_review" { return "Finish or discard review results to refresh the baseline." }
    if settings.baseline_status == "seed_fallback" { return "Using bundled data. Refresh the baseline when GitHub is available." }
    return "Baseline needs attention."
}
