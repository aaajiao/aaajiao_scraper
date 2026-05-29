import Foundation

func helperClientErrorTests() -> [AppTest] {
    [
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
