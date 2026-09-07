import Foundation
import Darwin

enum HelperBridgeError: LocalizedError {
    case missingExecutable
    case missingResources

    var errorDescription: String? {
        switch self {
        case .missingExecutable:
            return "Unable to determine helper executable path."
        case .missingResources:
            return "Bundled helper resources are missing."
        }
    }
}

@main
struct AaajiaoHelper {
    static func main() throws {
        let executableURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        let macOSURL = executableURL.deletingLastPathComponent()
        let contentsURL = macOSURL.deletingLastPathComponent()
        let resourcesURL = contentsURL.appendingPathComponent("Resources", isDirectory: true)

        let pythonCandidates = [
            resourcesURL.appendingPathComponent("python_runtime/bin/python3").path,
            resourcesURL.appendingPathComponent("python_runtime/bin/python3.9").path,
            resourcesURL.appendingPathComponent("python_runtime/bin/python").path
        ]
        guard let pythonPath = pythonCandidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            throw HelperBridgeError.missingResources
        }

        let enginePath = resourcesURL.appendingPathComponent("engine/aaajiao_importer.py").path
        guard FileManager.default.fileExists(atPath: enginePath) else {
            throw HelperBridgeError.missingResources
        }

        let sitePackages = resourcesURL.appendingPathComponent("python_runtime/lib/python3.9/site-packages").path
        var environment = ProcessInfo.processInfo.environment
        environment["AAAJIAO_IMPORTER_BUNDLE_ROOT"] = resourcesURL.path
        if environment["AAAJIAO_REPO_ROOT"]?.isEmpty ?? true {
            environment["AAAJIAO_REPO_ROOT"] = "/Users/aaajiao/Documents/aaajiao_scraper"
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONPATH"] = sitePackages
        environment.removeValue(forKey: "PYTHONHOME")
        environment.removeValue(forKey: "PYTHONEXECUTABLE")
        // Replace this launcher in-place. The app owns this PID and its
        // process group, so timeout/cancellation reaches Python and every
        // inherited git or network subprocess without a surviving wrapper.
        for key in ["PYTHONHOME", "PYTHONEXECUTABLE"] { unsetenv(key) }
        for (key, value) in environment { setenv(key, value, 1) }
        var arguments = ([pythonPath, enginePath] + Array(CommandLine.arguments.dropFirst())).map { strdup($0) } + [nil]
        defer { for pointer in arguments { free(pointer) } }
        execv(pythonPath, &arguments)
        throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
    }
}
