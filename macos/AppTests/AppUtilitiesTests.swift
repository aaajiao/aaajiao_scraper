import Foundation

func appUtilitiesTests() -> [AppTest] {
    [
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
