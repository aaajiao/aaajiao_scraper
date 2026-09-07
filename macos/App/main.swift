import AppKit
import Foundation
import SwiftUI

let settingsWindowID = "settings"
let importerWindowID = "importer"

func presentSettingsWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.async {
        openWindow(id: settingsWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

func presentImporterWindow(_ openWindow: OpenWindowAction) {
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.async {
        openWindow(id: importerWindowID)
        NSApp.activate(ignoringOtherApps: true)
    }
}

func closeSettingsWindow() {
    if let settingsWindow = NSApp.windows.first(where: { $0.title == "Settings" }) {
        settingsWindow.performClose(nil)
        return
    }
    NSApp.keyWindow?.performClose(nil)
}

private struct ImporterMenuBarLabel: View {
    @Environment(\.openWindow) private var openWindow
    @Binding var hasPresentedInitialWindow: Bool

    var body: some View {
        Image(systemName: "tray.full")
            .accessibilityLabel("aaajiao Importer")
            .onAppear {
                guard !hasPresentedInitialWindow else { return }
                hasPresentedInitialWindow = true
                presentImporterWindow(openWindow)
            }
    }
}

@main
struct AaajiaoImporterApp: App {
    @NSApplicationDelegateAdaptor(ImporterAppDelegate.self) private var appDelegate
    @State private var hasPresentedInitialWindow = false

    private var model: AppModel { appDelegate.model }

    var body: some Scene {
        Window("Importer", id: importerWindowID) {
            ContentView()
                .environmentObject(model)
        }
        .defaultSize(width: 1180, height: 780)
        .windowResizability(.contentMinSize)
        .commands {
            AppCommands(model: model)
        }

        MenuBarExtra {
            MenuBarMenuView()
                .environmentObject(model)
        } label: {
            ImporterMenuBarLabel(hasPresentedInitialWindow: $hasPresentedInitialWindow)
        }

        Window("Settings", id: settingsWindowID) {
            SettingsView()
                .environmentObject(model)
        }
        .windowResizability(.contentSize)
    }
}
