import Foundation

func helperClientErrorTests() -> [AppTest] {
    [
        ("helper progress distinguishes known stages from numeric updates", {
            for stage in ["checking_access", "discovering_urls", "reading_page", "validating_record"] {
                for url in ["", "https://eventstructure.com/artwork"] {
                    let line = "STAGE \(stage)" + (url.isEmpty ? "" : " \(url)")
                    guard let progress = HelperProgress(stderrLine: Data(line.utf8)) else {
                        throw AppTestFailure(message: "Expected known stage \(line)")
                    }
                    try expectEqual(progress.stage, stage, "Stage name")
                    try expectEqual(progress.url, url, "Optional stage URL")
                    try expectEqual(progress.completed, 0, "Stage events do not report completed counts")
                    try expectEqual(progress.total, 0, "Stage events do not report totals")
                }
            }
            guard let progress = HelperProgress(stderrLine: Data("PROGRESS 2/7 https://eventstructure.com/artwork".utf8)) else {
                throw AppTestFailure(message: "Numeric progress must remain supported")
            }
            try expectEqual(progress.stage, nil, "Numeric events have no stage")
            try expectEqual(progress.completed, 2, "Numeric completed count")
            try expectEqual(progress.total, 7, "Numeric total count")
            try expectEqual(progress.url, "https://eventstructure.com/artwork", "Numeric URL")
        }),
        ("helper progress preserves unknown stages and malformed protocol as stderr", {
            for line in [
                "STAGE future_stage https://eventstructure.com/artwork",
                "STAGE checking_access_extra",
                "STAGE reading_page unexpected failure details",
                "STAGE validating_record file:///tmp/page",
                "STAGE ",
                "STAGE",
                "ordinary STAGE checking_access",
                "PROGRESS invalid/7 https://eventstructure.com/artwork",
                "PROGRESS 2/7"
            ] {
                try expect(HelperProgress(stderrLine: Data(line.utf8)) == nil, "Unrecognized line must remain stderr: \(line)")
            }
        }),
        ("helper authentication marker survives the actual CLI Error prefix", {
            let error = HelperClientError.fromHelperStderr("STAGE checking_access\nError: [OPENAI_AUTHENTICATION_FAILED] OpenAI authentication failed. Check Settings.\n")
            guard case .authenticationFailed(let message) = error else { throw AppTestFailure(message: "Expected a typed authentication failure") }
            try expectEqual(message, "OpenAI authentication failed. Check Settings.", "Strip only the known transport wrapper and code")
        }),
        ("helper permission and preflight markers remain distinct", {
            guard case .permissionDenied = HelperClientError.fromHelperStderr("Error: [OPENAI_PERMISSION_DENIED] Model permission denied") else {
                throw AppTestFailure(message: "A model permission error must not be classified as an invalid key")
            }
            guard case .preflightFailed = HelperClientError.fromHelperStderr("Error: [OPENAI_PREFLIGHT_FAILED] Connection unavailable") else {
                throw AppTestFailure(message: "A connection failure needs its own classification")
            }
        }),
        ("ordinary network and 403 errors do not imply authentication failure", {
            for stderr in ["HTTP 403 Forbidden", "Connection timed out", "Page text includes [OPENAI_AUTHENTICATION_FAILED]"] {
                guard case .nonZeroExit = HelperClientError.fromHelperStderr(stderr) else {
                    throw AppTestFailure(message: "Only explicit helper codes may establish an authentication error")
                }
            }
        }),
        ("helper client missing resources message", {
            try expectEqual(
                HelperClientError.missingResources.errorDescription,
                "Bundled helper resources are missing.",
                "Missing resources message"
            )
        }),
        ("helper client non-zero exit trims stderr", {
            try expectEqual(
                HelperClientError.nonZeroExit("  helper failed\n").errorDescription,
                "helper failed",
                "Non-zero exit message should be trimmed"
            )
        }),
        ("helper client decode failure includes helper output", {
            try expectEqual(
                HelperClientError.decodeFailure("not json").errorDescription,
                "Failed to decode helper output: not json",
                "Decode failure message"
            )
        }),
    ]
}
