import AppKit

@MainActor
final class ImporterAppDelegate: NSObject, NSApplicationDelegate {
    // The delegate owns the same model observed by every window and menu.
    // It is available even if no importer window has appeared yet.
    let model = AppModel()

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        model.shouldTerminateApplication() ? .terminateNow : .terminateCancel
    }
}
