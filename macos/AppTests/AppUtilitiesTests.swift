import Foundation

func appUtilitiesTests() -> [AppTest] {
    [
        ("app version reads short version and build", {
            let version = AppVersionInfo.from(infoDictionary: [
                "CFBundleShortVersionString": "0.1.1",
                "CFBundleVersion": "2",
            ])
            try expectEqual(version.valueText, "0.1.1 (2)", "Version value")
            try expectEqual(version.menuText, "Version 0.1.1 (2)", "Version menu label")
        }),
        ("app version trims plist values", {
            let version = AppVersionInfo.from(infoDictionary: [
                "CFBundleShortVersionString": " 0.1.1 ",
                "CFBundleVersion": "\n2 ",
            ])
            try expectEqual(version.valueText, "0.1.1 (2)", "Trimmed version value")
        }),
        ("app version handles partial plist values", {
            try expectEqual(
                AppVersionInfo.from(infoDictionary: ["CFBundleShortVersionString": "0.1.1"]).valueText,
                "0.1.1",
                "Short-version-only value"
            )
            try expectEqual(
                AppVersionInfo.from(infoDictionary: ["CFBundleVersion": "2"]).valueText,
                "Build 2",
                "Build-only value"
            )
            try expectEqual(
                AppVersionInfo.from(infoDictionary: nil).valueText,
                "Unavailable",
                "Missing version value"
            )
        }),
        ("model source labels known values", {
            try expectEqual(openAIModelSourceLabel("custom"), "custom", "Custom source label")
            try expectEqual(openAIModelSourceLabel("preset"), "preset", "Preset source label")
            try expectEqual(openAIModelSourceLabel("default"), "default", "Default source label")
        }),
        ("model source labels unknown values as default", {
            try expectEqual(openAIModelSourceLabel(""), "default", "Empty source label")
            try expectEqual(openAIModelSourceLabel("invalid"), "default", "Invalid source label")
        }),
        ("github commit URL accepts https remotes", {
            let url = githubCommitURL(sourceURL: "https://github.com/aaajiao/aaajiao_scraper.git", commit: "abc123")
            try expectEqual(url?.absoluteString, "https://github.com/aaajiao/aaajiao_scraper/commit/abc123", "HTTPS remote URL")
        }),
        ("github commit URL accepts http remotes", {
            let url = githubCommitURL(sourceURL: "http://github.com/aaajiao/aaajiao_scraper", commit: "abc123")
            try expectEqual(url?.absoluteString, "https://github.com/aaajiao/aaajiao_scraper/commit/abc123", "HTTP remote URL")
        }),
        ("github commit URL accepts ssh remotes and trims commit", {
            let url = githubCommitURL(sourceURL: "git@github.com:aaajiao/aaajiao_scraper.git", commit: "  def456  ")
            try expectEqual(url?.absoluteString, "https://github.com/aaajiao/aaajiao_scraper/commit/def456", "SSH remote URL")
        }),
        ("github commit URL rejects missing data", {
            try expectNil(githubCommitURL(sourceURL: "", commit: "abc123"), "Empty source should be rejected")
            try expectNil(githubCommitURL(sourceURL: "https://github.com/aaajiao/aaajiao_scraper", commit: "   "), "Empty commit should be rejected")
            try expectNil(githubCommitURL(sourceURL: "https://example.com/aaajiao/aaajiao_scraper", commit: "abc123"), "Non-GitHub source should be rejected")
        }),
    ]
}
