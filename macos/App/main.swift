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

@main
struct AaajiaoImporterApp: App {
    @NSApplicationDelegateAdaptor(ImporterAppDelegate.self) private var appDelegate

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

        MenuBarExtra("aaajiao Importer", systemImage: "tray.full") {
            MenuBarMenuView()
                .environmentObject(model)
        }

        Window("Settings", id: settingsWindowID) {
            SettingsView()
                .environmentObject(model)
        }
        .windowResizability(.contentSize)
    }
}
