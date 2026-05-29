import Foundation

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
