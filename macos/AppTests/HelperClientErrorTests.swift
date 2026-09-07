import Foundation

func helperClientErrorTests() -> [AppTest] {
    [
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
