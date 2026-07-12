import Foundation

enum HelperClientError: LocalizedError {
    case missingResources
    case nonZeroExit(String)
    case decodeFailure(String)
    case timeout(command: String, seconds: TimeInterval)

    var errorDescription: String? {
        switch self {
        case .missingResources:
            return "Bundled helper resources are missing."
        case .nonZeroExit(let message):
            return message.trimmingCharacters(in: .whitespacesAndNewlines)
        case .decodeFailure(let message):
            return "Failed to decode helper output: \(message)"
        case .timeout(let command, let seconds):
            return "Helper command '\(command)' timed out after \(Int(seconds))s."
        }
    }
}

/// A machine-readable progress update the helper may emit on stderr during
/// long-running batch operations (currently only `startIncrementalSync`),
/// one line per completed URL: `PROGRESS <completed>/<total> <url>`.
struct HelperProgress: Sendable {
    let completed: Int
    let total: Int
    let url: String

    private static let prefix = "PROGRESS "

    /// Parses a single stderr line. Returns nil for anything that isn't a
    /// well-formed progress line, which callers then treat as ordinary
    /// stderr output — this is what keeps the format backward compatible
    /// with helper builds that never emit progress lines at all.
    init?(stderrLine data: Data) {
        guard let line = String(data: data, encoding: .utf8),
              line.hasPrefix(HelperProgress.prefix) else { return nil }
        let rest = line.dropFirst(HelperProgress.prefix.count)
        let parts = rest.split(separator: " ", maxSplits: 1)
        guard parts.count == 2 else { return nil }
        let counts = parts[0].split(separator: "/", maxSplits: 1)
        guard counts.count == 2,
              let completed = Int(counts[0]),
              let total = Int(counts[1]) else { return nil }
        self.completed = completed
        self.total = total
        self.url = String(parts[1])
    }
}

/// Splits an incrementally-arriving stderr stream into progress lines (see
/// `HelperProgress`) and everything else. Progress lines are reported via
/// `onProgress` as soon as a complete line is available and are excluded
/// from the accumulated text so they never pollute an eventual error
/// message; every other line is preserved byte-for-byte, so stderr behaves
/// exactly as before whenever the helper doesn't emit any progress lines.
private final class StderrProgressFilter {
    private let onProgress: (HelperProgress) -> Void
    private let lock = NSLock()
    private var pending = Data()
    private var filtered = Data()

    init(onProgress: @escaping (HelperProgress) -> Void) {
        self.onProgress = onProgress
    }

    /// Feed a raw chunk as it arrives on the reading queue.
    func consume(_ chunk: Data) {
        lock.lock()
        pending.append(chunk)
        var lines: [Data] = []
        while let newlineIndex = pending.firstIndex(of: 0x0A) {
            lines.append(pending.subdata(in: pending.startIndex..<newlineIndex))
            pending.removeSubrange(pending.startIndex...newlineIndex)
        }
        lock.unlock()
        classify(lines)
    }

    /// Flushes a final unterminated line (if any) and returns everything
    /// that wasn't a progress line, in original order. Call once no more
    /// `consume` calls will happen (i.e. after the pipe reader has drained).
    func finish() -> Data {
        lock.lock()
        let remainder = pending
        pending.removeAll()
        lock.unlock()
        if !remainder.isEmpty {
            classify([remainder])
        }
        lock.lock()
        defer { lock.unlock() }
        return filtered
    }

    private func classify(_ lines: [Data]) {
        guard !lines.isEmpty else { return }
        var keep = Data()
        for line in lines {
            if let progress = HelperProgress(stderrLine: line) {
                onProgress(progress)
            } else {
                keep.append(line)
                keep.append(0x0A)
            }
        }
        guard !keep.isEmpty else { return }
        lock.lock()
        filtered.append(keep)
        lock.unlock()
    }
}

/// Streams a pipe's output as it arrives instead of buffering it after the
/// fact. Reading must start before (or concurrently with) waiting for the
/// producing process to exit: `Process.waitUntilExit()` followed by
/// `readDataToEndOfFile()` deadlocks as soon as the child writes more than
/// the OS pipe buffer (64KB on macOS), because the child blocks on `write()`
/// waiting for a reader that never comes until after it exits.
///
/// Chunks are also handed to `onChunk` as they arrive so callers can layer
/// incremental parsing on top (e.g. splitting stderr into progress lines)
/// without waiting for the whole stream to finish.
private final class PipeStreamReader {
    private let pipe: Pipe
    private let onChunk: ((Data) -> Void)?
    private let lock = NSLock()
    private var buffer = Data()
    private let drainedGroup = DispatchGroup()

    init(pipe: Pipe, onChunk: ((Data) -> Void)? = nil) {
        self.pipe = pipe
        self.onChunk = onChunk
    }

    /// Begins accumulating data. Must be called before the producing
    /// process is started so no early output is missed.
    func start() {
        drainedGroup.enter()
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            guard let self else { return }
            let chunk = handle.availableData
            if chunk.isEmpty {
                // EOF: the write end of the pipe closed.
                handle.readabilityHandler = nil
                self.drainedGroup.leave()
                return
            }
            self.lock.lock()
            self.buffer.append(chunk)
            self.lock.unlock()
            self.onChunk?(chunk)
        }
    }

    /// Waits (up to `deadline`) for the pipe to reach EOF, then returns
    /// everything read so far. Safe to call even if EOF never arrives
    /// (e.g. the process was force-terminated): whatever was captured up to
    /// that point is returned once the deadline passes.
    @discardableResult
    func finish(deadline: DispatchTime) -> Data {
        _ = drainedGroup.wait(timeout: deadline)
        pipe.fileHandleForReading.readabilityHandler = nil
        lock.lock()
        defer { lock.unlock() }
        return buffer
    }
}

final class HelperClient: @unchecked Sendable {
    /// Default wall-clock budgets per command shape. Individual calls may
    /// override via the `timeout` parameter where a command's normal
    /// duration doesn't fit these buckets.
    private enum Timeout {
        /// Local SQLite reads/writes with no network or subprocess fan-out.
        static let quick: TimeInterval = 60
        /// A single network round trip (git baseline sync, one AI validation call, git push).
        static let standard: TimeInterval = 180
        /// Batch operations that loop over many URLs, each with its own AI validation call.
        static let extended: TimeInterval = 900
    }

    /// Grace period given to a timed-out process to exit after `terminate()`
    /// before we give up waiting on it and return control to the caller.
    private static let terminationGracePeriod: TimeInterval = 5

    func bootstrapWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        try await runCommandAsync(
            arguments: ["bootstrapWorkspace"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.standard,
            as: BootstrapResponse.self
        )
    }

    func listPendingRecords(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> PendingRecordsResponse {
        try await runCommandAsync(
            arguments: ["listPendingRecords"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: PendingRecordsResponse.self
        )
    }

    func resetWorkspace(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        try await runCommandAsync(
            arguments: ["resetWorkspace"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.standard,
            as: BootstrapResponse.self
        )
    }

    func refreshWorkspaceBaseline(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BootstrapResponse {
        try await runCommandAsync(
            arguments: ["refreshWorkspaceBaseline"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.standard,
            as: BootstrapResponse.self
        )
    }

    /// `onProgress` (if provided) is invoked once per `PROGRESS <completed>/<total> <url>`
    /// line the helper emits on stderr while it works through the batch. It fires on a
    /// background queue, same as any other stderr activity — callers updating UI state
    /// must hop back to the main actor themselves. Helper builds that don't emit progress
    /// lines behave exactly as before (onProgress is simply never called).
    func startIncrementalSync(
        openAIKey: String,
        openAIModel: String,
        openAIModelSource: String,
        onProgress: (@Sendable (HelperProgress) -> Void)? = nil
    ) async throws -> StartSyncResponse {
        try await runCommandAsync(
            arguments: ["startIncrementalSync"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.extended,
            as: StartSyncResponse.self,
            onProgress: onProgress
        )
    }

    func submitManualURL(_ url: String, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> SubmitURLResponse {
        try await runCommandAsync(
            arguments: ["submitManualURL", "--url", url],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.standard,
            as: SubmitURLResponse.self
        )
    }

    func acceptRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try await runCommandAsync(
            arguments: ["acceptRecord", "--id", "\(id)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: RecordStatusResponse.self
        )
    }

    func rejectRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try await runCommandAsync(
            arguments: ["rejectRecord", "--id", "\(id)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: RecordStatusResponse.self
        )
    }

    func getBatchDetail(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> BatchDetailResponse {
        try await runCommandAsync(
            arguments: ["getBatchDetail", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: BatchDetailResponse.self
        )
    }

    func getApplyPreview(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyPreview {
        try await runCommandAsync(
            arguments: ["getApplyPreview", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: ApplyPreview.self
        )
    }

    func applyAcceptedRecords(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> ApplyResponse {
        try await runCommandAsync(
            arguments: ["applyAcceptedRecords", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.standard,
            as: ApplyResponse.self
        )
    }

    func deleteBatch(batchID: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> DeleteBatchResponse {
        try await runCommandAsync(
            arguments: ["deleteBatch", "--batch-id", "\(batchID)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: DeleteBatchResponse.self
        )
    }

    private func runCommandAsync<T: Decodable & Sendable>(
        arguments: [String],
        openAIKey: String,
        openAIModel: String,
        openAIModelSource: String,
        timeout: TimeInterval,
        as type: T.Type,
        onProgress: (@Sendable (HelperProgress) -> Void)? = nil
    ) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let result = try self.runCommand(
                        arguments: arguments,
                        openAIKey: openAIKey,
                        openAIModel: openAIModel,
                        openAIModelSource: openAIModelSource,
                        timeout: timeout,
                        as: type,
                        onProgress: onProgress
                    )
                    continuation.resume(returning: result)
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private func runCommand<T: Decodable & Sendable>(
        arguments: [String],
        openAIKey: String,
        openAIModel: String,
        openAIModelSource: String,
        timeout: TimeInterval,
        as type: T.Type,
        onProgress: (@Sendable (HelperProgress) -> Void)? = nil
    ) throws -> T {
        let data = try runRawCommand(
            arguments: arguments,
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: timeout,
            onProgress: onProgress
        )
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            let raw = String(decoding: data, as: UTF8.self)
            throw HelperClientError.decodeFailure(raw.isEmpty ? error.localizedDescription : raw)
        }
    }

    private func runRawCommand(
        arguments: [String],
        openAIKey: String,
        openAIModel: String,
        openAIModelSource: String,
        timeout: TimeInterval,
        onProgress: (@Sendable (HelperProgress) -> Void)? = nil
    ) throws -> Data {
        let helperURL = Bundle.main.bundleURL
            .appendingPathComponent("Contents/MacOS/AaajiaoHelper", isDirectory: false)
        guard FileManager.default.isExecutableFile(atPath: helperURL.path) else {
            throw HelperClientError.missingResources
        }
        let process = Process()
        process.executableURL = helperURL
        process.arguments = arguments
        process.environment = [
            "OPENAI_API_KEY": openAIKey,
            "OPENAI_MODEL": openAIModel,
            "OPENAI_MODEL_SOURCE": openAIModelSource
        ].merging(ProcessInfo.processInfo.environment) { new, _ in new }

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        // Stream both pipes concurrently with the process running so their
        // OS buffers never fill up and block the child's write() calls.
        // When a progress handler is supplied, stderr chunks are also fed
        // to a StderrProgressFilter (each chunk arrives as soon as the
        // helper flushes it) so progress lines can be reported incrementally
        // and kept out of the text that becomes an eventual error message.
        let progressFilter = onProgress.map { StderrProgressFilter(onProgress: $0) }
        let stdoutReader = PipeStreamReader(pipe: stdoutPipe)
        let stderrReader = PipeStreamReader(pipe: stderrPipe, onChunk: progressFilter.map { filter in
            { chunk in filter.consume(chunk) }
        })
        stdoutReader.start()
        stderrReader.start()

        let exitGroup = DispatchGroup()
        exitGroup.enter()
        process.terminationHandler = { _ in exitGroup.leave() }

        try process.run()

        let commandName = arguments.first ?? "helper"
        let exited = exitGroup.wait(timeout: .now() + timeout) == .success
        guard exited else {
            process.terminate()
            // Give the process a short grace period to actually exit so the
            // pipes get closed and the readers can drain cleanly, then stop
            // waiting regardless so this call never hangs the caller again.
            _ = exitGroup.wait(timeout: .now() + Self.terminationGracePeriod)
            stdoutReader.finish(deadline: .now())
            stderrReader.finish(deadline: .now())
            throw HelperClientError.timeout(command: commandName, seconds: timeout)
        }

        let output = stdoutReader.finish(deadline: .now() + Self.terminationGracePeriod)
        let rawStderr = stderrReader.finish(deadline: .now() + Self.terminationGracePeriod)
        // With no progress filter this is identical to the raw stderr bytes
        // (unchanged behavior); with one, progress lines have been stripped
        // out so they never show up in a user-facing error message.
        let errorOutput = progressFilter?.finish() ?? rawStderr
        guard process.terminationStatus == 0 else {
            let message = String(decoding: errorOutput, as: UTF8.self)
            throw HelperClientError.nonZeroExit(message.isEmpty ? "Helper failed." : message)
        }
        return output
    }
}
