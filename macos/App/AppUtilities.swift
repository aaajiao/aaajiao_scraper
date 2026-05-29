import Foundation

struct AppVersionInfo: Equatable {
    let shortVersion: String
    let build: String

    var valueText: String {
        switch (shortVersion.isEmpty, build.isEmpty) {
        case (false, false):
            return "\(shortVersion) (\(build))"
        case (false, true):
            return shortVersion
        case (true, false):
            return "Build \(build)"
        case (true, true):
            return "Unavailable"
        }
    }

    var menuText: String {
        "Version \(valueText)"
    }

    static var current: AppVersionInfo {
        from(infoDictionary: Bundle.main.infoDictionary)
    }

    static func from(infoDictionary: [String: Any]?) -> AppVersionInfo {
        AppVersionInfo(
            shortVersion: normalizedVersionValue(infoDictionary?["CFBundleShortVersionString"]),
            build: normalizedVersionValue(infoDictionary?["CFBundleVersion"])
        )
    }

    private static func normalizedVersionValue(_ value: Any?) -> String {
        guard let value = value as? String else { return "" }
        return value.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

func openAIModelSourceLabel(_ source: String) -> String {
    switch source {
    case "custom":
        return "custom"
    case "preset":
        return "preset"
    default:
        return "default"
    }
}

func githubCommitURL(sourceURL: String?, commit: String?) -> URL? {
    let trimmedCommit = commit?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard !trimmedCommit.isEmpty else { return nil }
    let trimmedSource = sourceURL?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard !trimmedSource.isEmpty else { return nil }

    let repoPath: String
    if trimmedSource.hasPrefix("https://github.com/") || trimmedSource.hasPrefix("http://github.com/") {
        repoPath = trimmedSource
            .replacingOccurrences(of: "https://github.com/", with: "")
            .replacingOccurrences(of: "http://github.com/", with: "")
    } else if trimmedSource.hasPrefix("git@github.com:") {
        repoPath = trimmedSource.replacingOccurrences(of: "git@github.com:", with: "")
    } else {
        return nil
    }

    let normalizedRepoPath = repoPath.hasSuffix(".git")
        ? String(repoPath.dropLast(4))
        : repoPath
    return URL(string: "https://github.com/\(normalizedRepoPath)/commit/\(trimmedCommit)")
}
