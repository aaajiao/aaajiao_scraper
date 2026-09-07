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

    override init() {
        guard let fixtureURL = Bundle.main.url(forResource: "fixtures", withExtension: "json") else {
            fatalError("The preview bundle is missing fixtures.json")
        }
        do {
            model = AppModel(helper: try PreviewHelper(fixtureURL: fixtureURL), preferences: PreviewPreferences().value)
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
}

@main
struct ImporterPreviewApp: App {
    @NSApplicationDelegateAdaptor(PreviewAppDelegate.self) private var appDelegate

    var body: some Scene {
        Window("Importer Preview", id: importerWindowID) {
            ContentView()
                .environmentObject(appDelegate.model)
                .navigationTitle("Importer Preview")
        }
        .defaultSize(width: 1200, height: 820)
        .windowResizability(.contentMinSize)
        .commands {
            AppCommands(model: appDelegate.model)
            CommandMenu("Preview") {
                Text("Sample data • changes stay in memory")
                Menu("Appearance") {
                    Button("System") { NSApp.appearance = nil }
                    Button("Light") { NSApp.appearance = NSAppearance(named: .aqua) }
                    Button("Dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
                }
                Divider()
                Button("Restore Sample Data") {
                    appDelegate.model.confirmWorkspaceReset()
                }
                .keyboardShortcut("0", modifiers: [.command, .option])
                .disabled(appDelegate.model.isBusy)
            }
        }

        Window("Importer Preview Settings", id: settingsWindowID) {
            SettingsView()
                .environmentObject(appDelegate.model)
        }
        .windowResizability(.contentSize)
    }
}
