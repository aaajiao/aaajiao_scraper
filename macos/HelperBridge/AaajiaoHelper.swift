import Foundation

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
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [enginePath] + Array(CommandLine.arguments.dropFirst())
        process.environment = [
            "AAAJIAO_IMPORTER_BUNDLE_ROOT": resourcesURL.path,
            "AAAJIAO_REPO_ROOT": "/Users/aaajiao/Documents/aaajiao_scraper",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": sitePackages
        ].merging(ProcessInfo.processInfo.environment) { new, old in
            new.isEmpty ? old : new
        }
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError

        try process.run()
        process.waitUntilExit()
        Foundation.exit(process.terminationStatus)
    }
}
