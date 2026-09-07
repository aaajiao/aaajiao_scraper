import AppKit
import Foundation
import SwiftUI

// The production entrypoint is excluded from this target. These identifiers
// preserve its window actions while keeping the preview lifecycle independent.
let settingsWindowID = "settings"
let importerWindowID = "importer"

func presentSettingsWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    openWindow(id: settingsWindowID)
}

func presentImporterWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    openWindow(id: importerWindowID)
}

func closeSettingsWindow() {
    NSApp.windows.first(where: { $0.title == "Importer Preview Settings" })?.performClose(nil)
}

@MainActor
private final class PreviewPreferences {
    var key = "preview-placeholder-no-api-access"
    var modelSelection = OpenAIModelSelection(preset: .defaultPreset, customModel: "")

    var value: AppModelPreferences {
        AppModelPreferences(
            loadKey: { self.key.isEmpty ? .notFound : .found(self.key) },
            saveKey: { self.key = $0 },
            deleteKey: { self.key = "" },
            loadModel: { self.modelSelection },
            saveModel: { self.modelSelection = $0 }
        )
    }
}

@MainActor
private final class PreviewAppDelegate: NSObject, NSApplicationDelegate {
    let model: AppModel
    let helper: PreviewHelper

    override init() {
        guard let fixtureURL = Bundle.main.url(forResource: "fixtures", withExtension: "json") else {
            fatalError("The preview bundle is missing fixtures.json")
        }
        do {
            let helper = try PreviewHelper(fixtureURL: fixtureURL)
            self.helper = helper
            model = AppModel(helper: helper, preferences: PreviewPreferences().value)
        } catch {
            fatalError("The preview fixture could not be loaded: \(error.localizedDescription)")
        }
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        model.shouldTerminateApplication() ? .terminateNow : .terminateCancel
    }

    var canChangeQueueScenario: Bool {
        !model.isReviewInteractionLocked && !model.isShowingImportSheet && !model.isShowingApplyConfirmation
            && !model.isShowingResetConfirmation && !model.isShowingDeleteConfirmation && !model.isShowingDiscardConfirmation
    }

    func selectQueueScenario(_ scenario: PreviewQueueScenario) {
        guard canChangeQueueScenario else { return }
        helper.selectQueueScenario(scenario)
        // Drop only this preview model's selection before reloading the new
        // in-memory queue through the same helper/model path as the real app.
        model.currentBatchID = nil
        model.currentBatchDetail = nil
        model.selectedRecordID = nil
        model.currentApplyPreview = nil
        model.availableBatches = []
        model.searchText = ""
        model.reviewFilter = .all
        model.refreshFromUI()
    }

    func resizePreviewWindow(width: CGFloat, height: CGFloat) {
        guard let window = NSApp.windows.first(where: {
            $0.identifier?.rawValue == importerWindowID || ["Importer", "Importer Preview"].contains($0.title)
        }) else { return }
        window.contentView?.layoutSubtreeIfNeeded()
        // A unified titlebar/toolbar occupies part of the content view. Size the
        // outer frame from the usable layout rect instead of shrinking that area.
        let layoutSize = window.contentLayoutRect.size
        let chromeWidth = max(0, window.frame.width - layoutSize.width)
        let chromeHeight = max(0, window.frame.height - layoutSize.height)
        var frame = window.frame
        frame.size = NSSize(
            width: max(window.minSize.width, width + chromeWidth),
            height: max(window.minSize.height, height + chromeHeight)
        )
        window.setFrame(frame, display: true, animate: false)
        window.contentView?.layoutSubtreeIfNeeded()

        // SwiftUI can revise its minimum or toolbar layout after the first resize.
        // One bounded correction keeps the requested usable area available.
        var adjustedFrame = window.frame
        adjustedFrame.size = NSSize(
            width: max(window.minSize.width, adjustedFrame.width + max(0, width - window.contentLayoutRect.width)),
            height: max(window.minSize.height, adjustedFrame.height + max(0, height - window.contentLayoutRect.height))
        )
        if adjustedFrame.size != window.frame.size {
            window.setFrame(adjustedFrame, display: true, animate: false)
            window.contentView?.layoutSubtreeIfNeeded()
        }
        window.center()
        window.makeKeyAndOrderFront(nil)
    }
}

@main
struct ImporterPreviewApp: App {
    @NSApplicationDelegateAdaptor(PreviewAppDelegate.self) private var appDelegate
    @State private var authenticationMode = PreviewAuthenticationMode.valid

    var body: some Scene {
        Window("Importer Preview", id: importerWindowID) {
            ContentView()
                .environmentObject(appDelegate.model)
                .navigationTitle("Importer Preview")
        }
        .defaultSize(width: 1180, height: 780)
        .windowResizability(.contentMinSize)
        .commands {
            AppCommands(model: appDelegate.model)
            CommandMenu("Preview") {
                Text("Preview · Changes stay in memory; nothing is uploaded.")
                Menu("Appearance") {
                    Button("System") { NSApp.appearance = nil }
                    Button("Light") { NSApp.appearance = NSAppearance(named: .aqua) }
                    Button("Dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
                }
                Menu("Window Size") {
                    Button("Compact (900×620)") { appDelegate.resizePreviewWindow(width: 900, height: 620) }
                    Button("Standard (1180×780)") { appDelegate.resizePreviewWindow(width: 1180, height: 780) }
                }
                Menu("API Authentication") {
                    Picker("Scenario", selection: Binding(
                        get: { authenticationMode },
                        set: { mode in
                            authenticationMode = mode
                            appDelegate.helper.authenticationMode = mode
                        }
                    )) {
                        ForEach(PreviewAuthenticationMode.allCases) { mode in
                            Text(mode.title).tag(mode)
                        }
                    }
                    .pickerStyle(.inline)
                }
                .disabled(appDelegate.model.isBusy)
                Divider()
                Menu("Queue Scenarios") {
                    Button("Empty Queue") { appDelegate.selectQueueScenario(.emptyQueue) }
                    Button("No Site Updates") { appDelegate.selectQueueScenario(.noSiteUpdates) }
                    Button("All Accepted") { appDelegate.selectQueueScenario(.allAccepted) }
                    Divider()
                    Button("Restore Sample Data") { appDelegate.selectQueueScenario(.sampleData) }
                        .keyboardShortcut("0", modifiers: [.command, .option])
                }
                .disabled(!appDelegate.canChangeQueueScenario)
            }
        }

        Window("Importer Preview Settings", id: settingsWindowID) {
            SettingsView()
                .environmentObject(appDelegate.model)
        }
        .windowResizability(.contentSize)
    }
}
