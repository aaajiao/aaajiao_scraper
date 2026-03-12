import AppKit
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 280, ideal: 320, max: 360)
        } detail: {
            DetailColumnView()
        }
        .frame(minWidth: 980, minHeight: 680)
        .background(Color(nsColor: .windowBackgroundColor))
        .safeAreaInset(edge: .top, spacing: 0) {
            if model.shouldShowStatusBanner {
                ContextBannerView()
                    .environmentObject(model)
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            SelectionActionBar()
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    model.requestImportSheet()
                } label: {
                    Label("Import URL…", systemImage: "plus.circle")
                }
                .help("Import a single artwork URL")

                Button {
                    model.startSync()
                } label: {
                    Label("Sync Entire Site", systemImage: "arrow.trianglehead.2.clockwise")
                }
                .disabled(!model.canRunProtectedActions || model.isBusy)

                Button {
                    model.refreshFromUI()
                } label: {
                    Label("Reload Results", systemImage: "arrow.clockwise")
                }
                .disabled(model.isBusy)

                Button {
                    model.refreshWorkspaceBaseline()
                } label: {
                    Label("Refresh Baseline", systemImage: "arrow.down.circle")
                }
                .disabled(!model.canRefreshBaseline)

                Button {
                    model.requestApply()
                } label: {
                    Label("Apply Accepted", systemImage: "arrow.up.circle.fill")
                }
                .disabled(!model.canSyncCurrentRun || model.isBusy)

                Menu {
                    Button("Discard Current Run", role: .destructive) {
                        model.requestDiscardCurrentRun()
                    }
                    .disabled(!model.canDiscardCurrentRun)

                    Button("Reset Workspace", role: .destructive) {
                        model.requestWorkspaceReset()
                    }
                } label: {
                    Label("More", systemImage: "ellipsis.circle")
                }
            }
        }
        .sheet(isPresented: $model.isShowingImportSheet) {
            ImportURLSheet()
                .environmentObject(model)
        }
        .alert("Sync accepted results to GitHub?", isPresented: $model.isShowingApplyConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Sync", role: .destructive) {
                model.confirmApply()
            }
        } message: {
            if let preview = model.currentApplyPreview {
                Text("This will sync \(preview.accepted_count) accepted result(s) to GitHub.")
            } else {
                Text("This will sync accepted results to GitHub.")
            }
        }
        .alert("Reset workspace from bundled seed?", isPresented: $model.isShowingResetConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Reset", role: .destructive) {
                model.confirmWorkspaceReset()
            }
        } message: {
            Text("This removes the local importer workspace, restores bundled code and cache, then refreshes artwork data from the latest GitHub baseline when available.")
        }
        .confirmationDialog(
            "Discard the current review run?",
            isPresented: $model.isShowingDiscardConfirmation,
            titleVisibility: .visible
        ) {
            Button("Discard Run", role: .destructive) {
                model.confirmDiscardCurrentRun()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This removes all current review results from the local workspace.")
        }
        .confirmationDialog(
            "Delete the selected result?",
            isPresented: $model.isShowingDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button("Delete Result", role: .destructive) {
                model.confirmDeleteSelectedRecord()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(model.visibleCurrentRecords.count <= 1
                ? "This also discards the current run because no reviewable results will remain."
                : "The selected result will be removed from the current review run.")
        }
        .onAppear {
            model.bootstrapIfNeeded()
        }
    }
}

private struct SidebarView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(spacing: 0) {
            SidebarOverviewPanel()
                .padding(16)

            Divider()

            if model.hasCurrentRun {
                ReviewQueueList()
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    Label("No current results", systemImage: "tray")
                        .font(.headline)
                    Text("Import one URL or run a site sync to start a review queue.")
                        .foregroundStyle(.secondary)
                    HStack {
                        Button("Import URL…") {
                            model.requestImportSheet()
                        }
                        .buttonStyle(.borderedProminent)

                        Button("Sync Entire Site") {
                            model.startSync()
                        }
                        .disabled(!model.canRunProtectedActions || model.isBusy)
                    }

                    if !model.hasSavedOpenAIKey {
                        Button("Open Settings") {
                            presentSettingsWindow(openWindow)
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(20)
            }
        }
        .navigationTitle("Importer")
    }
}

private struct SidebarOverviewPanel: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Review Workspace")
                    .font(.headline)
                Text(model.currentRunTitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if let detail = model.currentBatchDetail {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                    SummaryTile(title: "Mode", value: detail.batch.mode == "manual" ? "Single URL" : "Site Sync")
                    SummaryTile(title: "Total", value: "\(detail.total_records)")
                    SummaryTile(title: "Accepted", value: "\(detail.accepted_count)")
                    SummaryTile(title: "Pending", value: "\(detail.pending_count)")
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                StatusSummaryRow(
                    title: "OpenAI",
                    value: model.hasSavedOpenAIKey ? model.effectiveOpenAIModel : "Missing key",
                    systemImage: model.hasSavedOpenAIKey ? "checkmark.circle.fill" : "key.slash",
                    tint: model.hasSavedOpenAIKey ? .green : .orange
                )
                StatusSummaryRow(
                    title: "Workspace",
                    value: workspaceLabel(model.settings.workspace_status),
                    systemImage: "internaldrive",
                    tint: model.settings.workspace_status == "seed_version_mismatch" ? .orange : .secondary
                )
                StatusSummaryRow(
                    title: "Baseline",
                    value: baselineLabel(model.settings.baseline_status),
                    systemImage: "arrow.down.circle",
                    tint: baselineTint(model.settings)
                )
            }

            if let commitURL = model.baselineCommitURL {
                Link("Open baseline commit on GitHub", destination: commitURL)
                    .font(.caption)
            }

            if !model.settings.workspace_path.isEmpty {
                Text(model.settings.workspace_path)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }
        }
    }
}

private struct ReviewQueueList: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        List(selection: $model.selectedRecordID) {
            Section("Review Queue") {
                ForEach(model.visibleCurrentRecords) { record in
                    ReviewQueueRow(record: record)
                        .tag(record.id)
                }
            }
        }
        .listStyle(.sidebar)
    }
}

private struct ReviewQueueRow: View {
    let record: ProposedRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(record.displayTitle)
                    .lineLimit(2)
                Spacer(minLength: 8)
                StatusBadge(text: recordStatusLabel(record.status), tint: recordStatusTint(record.status))
            }

            Text(record.url)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(record.displayTitle), \(recordStatusLabel(record.status))")
    }
}

private struct DetailColumnView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Group {
            if let record = model.selectedRecord {
                RecordDetailView(record: record)
            } else if model.hasCurrentRun, model.visibleCurrentRecords.isEmpty {
                EmptyDetailState(
                    title: "No reviewable results",
                    message: "This run no longer has any visible items. Start a new import or sync."
                )
            } else if model.hasCurrentRun {
                EmptyDetailState(
                    title: "Select a result",
                    message: "Choose an item from the queue to inspect its details."
                )
            } else {
                WelcomeDetailState()
            }
        }
    }
}

private struct RecordDetailView: View {
    @EnvironmentObject private var model: AppModel
    let record: ProposedRecord

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(record.displayTitle)
                        .font(.title2.weight(.semibold))
                    if !record.title_cn.isEmpty {
                        Text(record.title_cn)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                GroupBox("Summary") {
                    VStack(alignment: .leading, spacing: 10) {
                        DetailFieldRow(label: "Status", value: recordStatusLabel(record.status))
                        DetailFieldRow(label: "Confidence", value: String(format: "%.2f", record.confidence))
                        DetailFieldRow(label: "Type", value: record.type.isEmpty ? "Unknown" : record.type)
                        DetailFieldRow(label: "Mode", value: record.is_update ? "Update" : "New record")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Metadata") {
                    VStack(alignment: .leading, spacing: 10) {
                        DetailFieldRow(label: "URL", value: record.url)
                        DetailFieldRow(label: "Year", value: record.year)
                        DetailFieldRow(label: "Materials", value: record.materials)
                        DetailFieldRow(label: "Size", value: record.size)
                        DetailFieldRow(label: "Duration", value: record.duration)
                        DetailFieldRow(label: "Credits", value: record.credits)
                        DetailFieldRow(label: "Video", value: record.video_link)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                DetailLinksGroup(title: "Image URLs", links: record.images, emptyMessage: "No image URLs found")
                DetailLinksGroup(title: "High-Res Image URLs", links: record.high_res_images, emptyMessage: "No high-res image URLs found")

                if !record.description_en.isEmpty {
                    GroupBox("Description EN") {
                        Text(record.description_en)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                }

                if !record.description_cn.isEmpty {
                    GroupBox("Description CN") {
                        Text(record.description_cn)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                }

                if let errorMessage = record.error_message, !errorMessage.isEmpty {
                    GroupBox(record.status == "failed" ? "Import Error" : "Validation Note") {
                        Text(errorMessage)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(record.displayTitle)
    }
}

private struct WelcomeDetailState: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("Ready for a new import", systemImage: "sparkles.rectangle.stack")
                .font(.title3.weight(.semibold))

            Text("Import one artwork URL or run an incremental site sync. Review results in the sidebar, then apply accepted changes to GitHub.")
                .foregroundStyle(.secondary)

            HStack {
                Button("Import URL…") {
                    model.requestImportSheet()
                }
                .buttonStyle(.borderedProminent)

                Button("Sync Entire Site") {
                    model.startSync()
                }
                .disabled(!model.canRunProtectedActions || model.isBusy)

                if !model.hasSavedOpenAIKey {
                    Button("Open Settings") {
                        presentSettingsWindow(openWindow)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .padding(32)
    }
}

private struct EmptyDetailState: View {
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "sidebar.right")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text(title)
                .font(.headline)
            Text(message)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(32)
    }
}

private struct DetailLinksGroup: View {
    let title: String
    let links: [String]
    let emptyMessage: String

    var body: some View {
        GroupBox(title) {
            if links.isEmpty {
                Text(emptyMessage)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Array(links.enumerated()), id: \.offset) { index, link in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(index + 1). \(link)")
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            if let url = URL(string: link), !link.isEmpty {
                                Link("Open Link", destination: url)
                                    .font(.caption)
                            }
                        }
                    }
                }
            }
        }
    }
}

private struct DetailFieldRow: View {
    let label: String
    let value: String

    var body: some View {
        if !value.isEmpty {
            LabeledContent(label) {
                Text(value)
                    .multilineTextAlignment(.trailing)
                    .textSelection(.enabled)
            }
        }
    }
}

private struct SelectionActionBar: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(primarySummary)
                    .font(.subheadline.weight(.medium))
                Text(secondarySummary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer()

            Button("Open Source Page") {
                model.openSelectedRecordSourcePage()
            }
            .disabled(model.selectedRecordSourceURL == nil)

            Button("Copy URL") {
                guard let record = model.selectedRecord else { return }
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(record.url, forType: .string)
            }
            .disabled(!model.hasSelectedRecord)

            Button("Delete", role: .destructive) {
                model.requestDeleteSelectedRecord()
            }
            .disabled(!model.canDeleteSelectedRecord)

            Button("Accept") {
                model.acceptSelectedRecord()
            }
            .disabled(!model.canAcceptSelectedRecord)

            Button("Apply Accepted") {
                model.requestApply()
            }
            .buttonStyle(.borderedProminent)
            .disabled(!model.canSyncCurrentRun || model.isBusy)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .background(.bar)
    }

    private var primarySummary: String {
        if let preview = model.currentApplyPreview, model.hasAcceptedRecords {
            return "\(preview.accepted_count) accepted ready to apply"
        }
        if let detail = model.currentBatchDetail {
            return "\(detail.pending_count) pending • \(detail.failed_count) failed"
        }
        return model.statusMessage
    }

    private var secondarySummary: String {
        if let record = model.selectedRecord {
            return record.displayTitle
        }
        if let preview = model.currentApplyPreview, !preview.target_files.isEmpty {
            return preview.target_files.joined(separator: " • ")
        }
        return "Use the toolbar to import a URL, sync the site, or refresh results."
    }
}

private struct ContextBannerView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(color)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if !model.hasSavedOpenAIKey {
                Button("Open Settings") {
                    presentSettingsWindow(openWindow)
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private var title: String {
        if !model.hasSavedOpenAIKey {
            return "OpenAI key required"
        }
        if let busyMessage = model.busyStatusMessage {
            return busyMessage
        }
        switch model.statusTone {
        case .success:
            return "Ready"
        case .warning:
            return "Attention needed"
        case .error:
            return "Action failed"
        case .info:
            return "Status update"
        case .neutral:
            return "Workspace status"
        }
    }

    private var message: String {
        if !model.hasSavedOpenAIKey {
            return "Save your API key in Settings before importing or syncing."
        }
        if model.hasBaselineWarning {
            return baselineDetail(model.settings)
        }
        return model.statusMessage
    }

    private var icon: String {
        if !model.hasSavedOpenAIKey {
            return "key.slash"
        }
        switch model.statusTone {
        case .success:
            return "checkmark.circle.fill"
        case .warning:
            return "exclamationmark.triangle.fill"
        case .error:
            return "xmark.octagon.fill"
        case .info:
            return "info.circle.fill"
        case .neutral:
            return "circle.fill"
        }
    }

    private var color: Color {
        if !model.hasSavedOpenAIKey {
            return .orange
        }
        switch model.statusTone {
        case .success:
            return .green
        case .warning:
            return .orange
        case .error:
            return .red
        case .info:
            return .blue
        case .neutral:
            return .secondary
        }
    }
}

private struct ImportURLSheet: View {
    @EnvironmentObject private var model: AppModel
    @FocusState private var isFieldFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Import URL")
                .font(.title3.weight(.semibold))
            Text("Paste one eventstructure.com artwork URL and import it into the current review queue.")
                .foregroundStyle(.secondary)

            TextField("Paste an artwork URL", text: $model.manualURL)
                .textFieldStyle(.roundedBorder)
                .focused($isFieldFocused)
                .onSubmit {
                    model.submitURL()
                }

            if model.isImportingURL {
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Importing URL...")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            HStack {
                Button("Cancel") {
                    model.cancelImportSheet()
                }
                .disabled(model.isImportingURL)

                Spacer()

                Button("Import") {
                    model.submitURL()
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.canSubmitManualURL)
            }
        }
        .padding(24)
        .frame(minWidth: 480)
        .onAppear {
            isFieldFocused = true
        }
    }
}

private struct SummaryTile: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.subheadline.weight(.medium))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

private struct StatusSummaryRow: View {
    let title: String
    let value: String
    let systemImage: String
    let tint: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .foregroundStyle(tint)
                .frame(width: 14)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.caption)
                .lineLimit(1)
        }
    }
}

private struct StatusBadge: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption2.weight(.medium))
            .foregroundStyle(tint)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(tint.opacity(0.12), in: Capsule())
    }
}

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("OpenAI") {
                    SecureField("OpenAI API Key", text: $model.settingsDraftOpenAIKey)
                    Picker("Model", selection: $model.settingsDraftOpenAIModelPreset) {
                        ForEach(OpenAIModelPreset.allCases) { preset in
                            Text(preset.displayName).tag(preset)
                        }
                    }

                    if model.settingsDraftOpenAIModelPreset == .custom {
                        TextField("Custom model name", text: $model.settingsDraftCustomOpenAIModel)
                    }
                }

                Section("Current Selection") {
                    LabeledContent("Effective model") {
                        Text(model.draftOpenAIModelSelection.effectiveModel)
                    }
                    LabeledContent("Model source") {
                        Text(openAIModelSourceLabel(model.draftOpenAIModelSelection.source).capitalized)
                    }
                }

                Section {
                    Text("The OpenAI key is stored only in macOS Keychain. The selected model is stored in local app preferences.")
                        .font(.callout)
                    if !model.settingsStatusMessage.isEmpty {
                        Text(model.settingsStatusMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .formStyle(.grouped)

            Divider()

            HStack {
                Button("Clear Key", role: .destructive) {
                    model.clearSavedKey()
                }
                .disabled(!model.hasSavedOpenAIKey && model.trimmedDraftOpenAIKey.isEmpty)

                Spacer()

                Button("Revert") {
                    model.revertSettings()
                }
                .disabled(!model.isSettingsDirty)

                Button(model.isSettingsDirty ? "Save" : "Done") {
                    if model.saveSettings() {
                        closeSettingsWindow()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.canSaveSettings)
            }
            .padding(20)
        }
        .frame(width: 500, height: 360)
    }
}

struct MenuBarMenuView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.hasSavedOpenAIKey ? model.reviewStatusValue : "OpenAI key missing")
                .font(.caption)
                .foregroundStyle(.secondary)

            Button {
                presentImporterWindow(openWindow)
            } label: {
                Label("Open Importer", systemImage: "sidebar.left")
            }

            Button {
                presentImporterWindow(openWindow)
                model.requestImportSheet()
            } label: {
                Label("Import URL…", systemImage: "plus.circle")
            }

            Button {
                model.startSync()
            } label: {
                Label("Sync Entire Site", systemImage: "arrow.trianglehead.2.clockwise")
            }
            .disabled(!model.canRunProtectedActions || model.isBusy)

            Button {
                model.refreshFromUI()
            } label: {
                Label("Reload Results", systemImage: "arrow.clockwise")
            }

            Divider()

            Button {
                presentSettingsWindow(openWindow)
            } label: {
                Label("Settings…", systemImage: "gearshape")
            }

            Button {
                model.quitApplication()
            } label: {
                Label("Quit aaajiao Importer", systemImage: "power")
            }
        }
        .padding(.vertical, 4)
    }
}

struct AppCommands: Commands {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") {
                presentSettingsWindow(openWindow)
            }
            .keyboardShortcut(",", modifiers: [.command])
        }

        CommandGroup(replacing: .newItem) {
            Button("Import URL…") {
                presentImporterWindow(openWindow)
                model.requestImportSheet()
            }
            .keyboardShortcut("n", modifiers: [.command])
        }

        CommandMenu("Actions") {
            Button("Reload Results") {
                model.refreshFromUI()
            }
            .keyboardShortcut("r", modifiers: [.command])

            Button("Sync Entire Site") {
                model.startSync()
            }
            .keyboardShortcut("i", modifiers: [.command, .shift])
            .disabled(!model.canRunProtectedActions || model.isBusy)

            Button("Refresh Baseline") {
                model.refreshWorkspaceBaseline()
            }
            .keyboardShortcut("r", modifiers: [.command, .option])
            .disabled(!model.canRefreshBaseline)

            Button("Apply Accepted") {
                model.requestApply()
            }
            .disabled(!model.canSyncCurrentRun || model.isBusy)
        }

        CommandMenu("Review") {
            Button("Accept Selected Result") {
                model.acceptSelectedRecord()
            }
            .keyboardShortcut(.return, modifiers: [.command])
            .disabled(!model.canAcceptSelectedRecord)

            Button("Delete Selected Result") {
                model.requestDeleteSelectedRecord()
            }
            .keyboardShortcut(.delete, modifiers: [])
            .disabled(!model.canDeleteSelectedRecord)

            Button("Open Source Page") {
                model.openSelectedRecordSourcePage()
            }
            .disabled(model.selectedRecordSourceURL == nil)
        }

        CommandGroup(replacing: .appTermination) {
            Button("Quit aaajiao Importer") {
                model.quitApplication()
            }
            .keyboardShortcut("q", modifiers: [.command])
        }
    }
}

private func recordStatusLabel(_ status: String) -> String {
    switch status {
    case "accepted":
        return "Accepted"
    case "needs_review":
        return "Needs review"
    case "ready_for_review":
        return "Ready for review"
    case "failed":
        return "Failed"
    default:
        return status.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

private func recordStatusTint(_ status: String) -> Color {
    switch status {
    case "accepted":
        return .green
    case "failed":
        return .orange
    default:
        return .secondary
    }
}

private func workspaceLabel(_ status: String?) -> String {
    switch status {
    case "ready":
        return "Ready"
    case "seed_version_mismatch":
        return "Snapshot changed"
    case "missing":
        return "Missing"
    default:
        return "Unknown"
    }
}

private func baselineLabel(_ status: String?) -> String {
    switch status {
    case "synced":
        return "GitHub Latest"
    case "seed_fallback":
        return "Seed Fallback"
    case "sync_skipped_pending_review":
        return "Refresh Skipped"
    case "missing":
        return "Missing"
    default:
        return "Unknown"
    }
}

private func baselineTint(_ settings: AppSettings) -> Color {
    switch settings.baseline_status {
    case "synced":
        return .green
    case "seed_fallback", "sync_skipped_pending_review":
        return .orange
    default:
        return .secondary
    }
}

private func baselineDetail(_ settings: AppSettings) -> String {
    if let error = settings.baseline_error, !error.isEmpty {
        if settings.baseline_status == "seed_fallback" {
            return "Using bundled seed after GitHub refresh failed."
        }
        return error
    }
    if settings.baseline_status == "sync_skipped_pending_review" {
        return "Pending review results are protected from overwrite."
    }
    if let commit = settings.baseline_commit, !commit.isEmpty {
        return "Commit \(String(commit.prefix(7)))."
    }
    if let branch = settings.baseline_branch, !branch.isEmpty {
        return "\(branch) baseline."
    }
    return "No baseline metadata."
}
