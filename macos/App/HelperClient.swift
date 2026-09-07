import Foundation
import Darwin

enum HelperClientError: LocalizedError {
    case missingResources
    case cancelled
    case nonZeroExit(String)
    case authenticationFailed(String)
    case permissionDenied(String)
    case preflightFailed(String)
    case decodeFailure(String)
    case timeout(command: String, seconds: TimeInterval)

    var errorDescription: String? {
        switch self {
        case .cancelled:
            return "Import cancelled."
        case .missingResources:
            return "Bundled helper resources are missing."
        case .nonZeroExit(let message), .authenticationFailed(let message), .permissionDenied(let message), .preflightFailed(let message):
            return message.trimmingCharacters(in: .whitespacesAndNewlines)
        case .decodeFailure(let message):
            return "Failed to decode helper output: \(message)"
        case .timeout(let command, let seconds):
            return "Helper command '\(command)' timed out after \(Int(seconds))s."
        }
    }

    static func fromHelperStderr(_ stderr: String) -> Self {
        // Codes come from the helper's deliberate failure classification. Do
        // not infer an invalid key from arbitrary network errors or HTTP 403.
        for line in stderr.components(separatedBy: .newlines).reversed() {
            let lineText = line.trimmingCharacters(in: .whitespacesAndNewlines)
            let trimmed = lineText.hasPrefix("Error: ") ? String(lineText.dropFirst("Error: ".count)) : lineText
            for (prefix, kind) in [
                ("[OPENAI_AUTHENTICATION_FAILED]", 0),
                ("[OPENAI_PERMISSION_DENIED]", 1),
                ("[OPENAI_PREFLIGHT_FAILED]", 2)
            ] where trimmed.hasPrefix(prefix) {
                let message = String(trimmed.dropFirst(prefix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
                switch kind {
                case 0: return .authenticationFailed(message)
                case 1: return .permissionDenied(message)
                default: return .preflightFailed(message)
                }
            }
        }
        return .nonZeroExit(stderr.isEmpty ? "Helper failed." : stderr)
    }
}

/// A machine-readable progress update the helper may emit on stderr during
/// long-running batch operations. Numeric updates use
/// `PROGRESS <completed>/<total> <url>`; stage updates use `STAGE <stage> [url]`.
struct HelperProgress: Sendable {
    let completed: Int
    let total: Int
    let url: String
    /// Stage events carry zero counts. Consumers should preserve their latest
    /// numeric progress when this is non-nil.
    let stage: String?

    private static let prefix = "PROGRESS "
    private static let stagePrefix = "STAGE "
    private static let knownStages: Set<String> = [
        "checking_access", "discovering_urls", "reading_page", "validating_record"
    ]

    /// Parses a single stderr line. Returns nil for anything that isn't a
    /// well-formed progress line, which callers then treat as ordinary
    /// stderr output — this is what keeps the format backward compatible
    /// with helper builds that never emit progress lines at all.
    init?(stderrLine data: Data) {
        guard let line = String(data: data, encoding: .utf8) else { return nil }
        if line.hasPrefix(Self.stagePrefix) {
            let parts = line.dropFirst(Self.stagePrefix.count).split(separator: " ", maxSplits: 1)
            guard let stage = parts.first.map(String.init), Self.knownStages.contains(stage) else { return nil }
            let url = parts.count == 2 ? String(parts[1]) : ""
            // Only consume the known protocol. A log sentence beginning with a
            // stage name must remain visible if its suffix isn't a page URL.
            if !url.isEmpty {
                guard url.rangeOfCharacter(from: .whitespacesAndNewlines) == nil,
                      let parsedURL = URL(string: url),
                      let scheme = parsedURL.scheme?.lowercased(),
                      ["http", "https"].contains(scheme),
                      parsedURL.host != nil else { return nil }
            }
            self.completed = 0
            self.total = 0
            self.url = url
            self.stage = stage
            return
        }
        guard line.hasPrefix(Self.prefix) else { return nil }
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
        self.stage = nil
    }
}

/// Splits an incrementally-arriving stderr stream into progress lines (see
/// `HelperProgress`) and everything else. Progress lines are reported via
/// `onProgress` as soon as a complete line is available and are excluded
/// from the accumulated text so they never pollute an eventual error
/// message; every other line is preserved byte-for-byte, so stderr behaves
/// exactly as before whenever the helper doesn't emit any progress lines.
final class StderrProgressFilter {
    private let onProgress: ((HelperProgress) -> Void)?
    private let lock = NSLock()
    private var pending = Data()
    private var filtered = Data()

    init(onProgress: ((HelperProgress) -> Void)? = nil) {
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
            classify([remainder], terminated: false)
        }
        lock.lock()
        defer { lock.unlock() }
        return filtered
    }

    private func classify(_ lines: [Data], terminated: Bool = true) {
        guard !lines.isEmpty else { return }
        var keep = Data()
        for line in lines {
            if let progress = HelperProgress(stderrLine: line) {
                onProgress?(progress)
            } else {
                keep.append(line)
                if terminated { keep.append(0x0A) }
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

    private let executableURL: URL?
    private let timeoutOverride: TimeInterval?
    private let terminationGracePeriod: TimeInterval
    private let commandLock = NSLock()
    private let stateLock = NSLock()
    private var activeCommand: HelperRunningCommand?

    /// Overrides are used by isolated process tests; normal app calls use
    /// the bundled helper and the per-command budgets above.
    init(
        executableURL: URL? = nil,
        timeoutOverride: TimeInterval? = nil,
        terminationGracePeriod: TimeInterval = 5
    ) {
        self.executableURL = executableURL
        self.timeoutOverride = timeoutOverride
        self.terminationGracePeriod = terminationGracePeriod
    }

    /// Only import operations are cancellable. In particular, publishing
    /// must finish reconciling the remote and local transaction state.
    /// Returning true acknowledges the request; the async command does not
    /// finish until the process group has stopped and its output is drained.
    @discardableResult
    func cancelCurrentCommand() -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return activeCommand?.requestCancellation() ?? false
    }

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

    func validateOpenAIKey(openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> OpenAIKeyValidationResponse {
        try await runCommandAsync(
            arguments: ["validateOpenAIKey"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.quick,
            as: OpenAIKeyValidationResponse.self
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

    func retryRecord(id: Int, openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        try await runCommandAsync(
            arguments: ["retryRecord", "--id", "\(id)"],
            openAIKey: openAIKey,
            openAIModel: openAIModel,
            openAIModelSource: openAIModelSource,
            timeout: Timeout.standard,
            as: RecordStatusResponse.self
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

    func updateRecord(id: Int, fields: [String: String], openAIKey: String, openAIModel: String, openAIModelSource: String) async throws -> RecordStatusResponse {
        let editsURL = FileManager.default.temporaryDirectory.appendingPathComponent("aaajiao-record-edits-\(UUID().uuidString).json")
        let data = try JSONEncoder().encode(fields)
        try data.write(to: editsURL, options: .atomic)
        defer { try? FileManager.default.removeItem(at: editsURL) }
        return try await runCommandAsync(
            arguments: ["updateRecord", "--id", "\(id)", "--edits-file", editsURL.path],
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

    /// Internal so process lifecycle tests can exercise real, isolated
    /// executables without requiring a bundle or an external service.
    func runRawCommand(
        arguments: [String],
        openAIKey: String = "",
        openAIModel: String = "",
        openAIModelSource: String = "",
        timeout: TimeInterval,
        onProgress: (@Sendable (HelperProgress) -> Void)? = nil
    ) throws -> Data {
        // Commands from one client never overlap, even if a caller starts a
        // second operation before awaiting cancellation of the first one.
        commandLock.lock()
        defer { commandLock.unlock() }
        let helperURL = executableURL ?? Bundle.main.bundleURL
            .appendingPathComponent("Contents/MacOS/AaajiaoHelper", isDirectory: false)
        guard FileManager.default.isExecutableFile(atPath: helperURL.path) else {
            throw HelperClientError.missingResources
        }
        let commandName = arguments.first ?? "helper"
        let command = HelperRunningCommand(name: commandName)
        stateLock.lock()
        activeCommand = command
        stateLock.unlock()
        defer {
            stateLock.lock()
            activeCommand = nil
            stateLock.unlock()
        }

        let environment = [
            "OPENAI_API_KEY": openAIKey,
            "OPENAI_MODEL": openAIModel,
            "OPENAI_MODEL_SOURCE": openAIModelSource
        ].merging(ProcessInfo.processInfo.environment) { new, _ in new }
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        let progressFilter = StderrProgressFilter(onProgress: onProgress)
        let stdoutReader = PipeStreamReader(pipe: stdoutPipe)
        let stderrReader = PipeStreamReader(pipe: stderrPipe, onChunk: { chunk in progressFilter.consume(chunk) })
        stdoutReader.start()
        stderrReader.start()

        let pid: pid_t
        do {
            // SETPGROUP creates the group atomically at spawn, before any
            // helper code runs or can create Python/git descendants.
            pid = try spawnHelper(
                executableURL: helperURL,
                arguments: arguments,
                environment: environment,
                stdoutPipe: stdoutPipe,
                stderrPipe: stderrPipe
            )
        } catch {
            stdoutPipe.fileHandleForWriting.closeFile()
            stderrPipe.fileHandleForWriting.closeFile()
            stdoutReader.finish(deadline: .distantFuture)
            stderrReader.finish(deadline: .distantFuture)
            throw error
        }
        stdoutPipe.fileHandleForWriting.closeFile()
        stderrPipe.fileHandleForWriting.closeFile()

        let budget = timeoutOverride ?? timeout
        let deadline = ProcessInfo.processInfo.systemUptime + max(0, budget)
        var status: Int32 = 0
        var reaped = false
        var stoppedError: Error?
        while !reaped {
            do {
                reaped = try reapHelper(pid, status: &status, blocking: false)
            } catch {
                stoppedError = error
                break
            }
            if reaped { break }
            if command.isCancellationRequested {
                stoppedError = HelperClientError.cancelled
                break
            }
            if ProcessInfo.processInfo.systemUptime >= deadline {
                stoppedError = HelperClientError.timeout(command: commandName, seconds: budget)
                break
            }
            command.waitForCancellation(until: Date(timeIntervalSinceNow: min(0.025, max(0, deadline - ProcessInfo.processInfo.systemUptime))))
        }

        // A timed-out parent or a successful helper with stray descendants
        // both require group cleanup. Never unlock the app while Python,
        // git or another inherited child can still write to the workspace.
        if !reaped || helperGroupExists(pid) {
            stopHelperGroup(pid, reaped: &reaped, status: &status, gracePeriod: terminationGracePeriod)
        }
        let output = stdoutReader.finish(deadline: .distantFuture)
        _ = stderrReader.finish(deadline: .distantFuture)
        let errorOutput = progressFilter.finish()
        if let stoppedError { throw stoppedError }
        // waitpid's status is zero only for a clean exit(0); signals and
        // non-zero exit codes retain their failure status.
        guard status == 0 else {
            let message = String(decoding: errorOutput, as: UTF8.self)
            throw HelperClientError.fromHelperStderr(message)
        }
        return output
    }
}

/// Cancellation wakes the runner; all signalling and reaping stays on the
/// runner queue so a late UI click can never target a reused process id.
private final class HelperRunningCommand {
    private let cancellable: Bool
    private let condition = NSCondition()
    private var cancellationRequested = false

    init(name: String) {
        cancellable = ["startIncrementalSync", "submitManualURL", "retryRecord"].contains(name)
    }

    var isCancellationRequested: Bool {
        condition.lock()
        defer { condition.unlock() }
        return cancellationRequested
    }

    func requestCancellation() -> Bool {
        guard cancellable else { return false }
        condition.lock()
        cancellationRequested = true
        condition.broadcast()
        condition.unlock()
        return true
    }

    func waitForCancellation(until deadline: Date) {
        condition.lock()
        if !cancellationRequested { _ = condition.wait(until: deadline) }
        condition.unlock()
    }
}

private func spawnHelper(
    executableURL: URL,
    arguments: [String],
    environment: [String: String],
    stdoutPipe: Pipe,
    stderrPipe: Pipe
) throws -> pid_t {
    var attributes: posix_spawnattr_t?
    var actions: posix_spawn_file_actions_t?
    try checkSpawnResult(posix_spawnattr_init(&attributes))
    defer { posix_spawnattr_destroy(&attributes) }
    try checkSpawnResult(posix_spawn_file_actions_init(&actions))
    defer { posix_spawn_file_actions_destroy(&actions) }
    try checkSpawnResult(posix_spawnattr_setpgroup(&attributes, 0))
    var signalMask = sigset_t()
    sigemptyset(&signalMask)
    try checkSpawnResult(posix_spawnattr_setsigmask(&attributes, &signalMask))
    var defaultSignals = sigset_t()
    sigemptyset(&defaultSignals)
    for signal in [SIGTERM, SIGINT, SIGHUP, SIGPIPE, SIGQUIT] { sigaddset(&defaultSignals, signal) }
    try checkSpawnResult(posix_spawnattr_setsigdefault(&attributes, &defaultSignals))
    try checkSpawnResult(posix_spawnattr_setflags(
        &attributes,
        Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT | POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF)
    ))
    try checkSpawnResult(posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0))
    try checkSpawnResult(posix_spawn_file_actions_adddup2(&actions, stdoutPipe.fileHandleForWriting.fileDescriptor, STDOUT_FILENO))
    try checkSpawnResult(posix_spawn_file_actions_adddup2(&actions, stderrPipe.fileHandleForWriting.fileDescriptor, STDERR_FILENO))

    var argv = ([executableURL.path] + arguments).map { strdup($0) } + [nil]
    var envp = environment.sorted { $0.key < $1.key }.map { strdup("\($0.key)=\($0.value)") } + [nil]
    defer {
        for pointer in argv { free(pointer) }
        for pointer in envp { free(pointer) }
    }
    var pid: pid_t = 0
    let result = posix_spawn(&pid, executableURL.path, &actions, &attributes, &argv, &envp)
    try checkSpawnResult(result)
    return pid
}

private func checkSpawnResult(_ result: Int32) throws {
    guard result == 0 else { throw POSIXError(POSIXErrorCode(rawValue: result) ?? .EIO) }
}

private func reapHelper(_ pid: pid_t, status: inout Int32, blocking: Bool) throws -> Bool {
    while true {
        let result = waitpid(pid, &status, blocking ? 0 : WNOHANG)
        if result == pid { return true }
        if result == 0 { return false }
        if errno == EINTR { continue }
        throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .ECHILD)
    }
}

private func helperGroupExists(_ pid: pid_t) -> Bool {
    kill(-pid, 0) == 0 || errno == EPERM
}

private func stopHelperGroup(_ pid: pid_t, reaped: inout Bool, status: inout Int32, gracePeriod: TimeInterval) {
    _ = kill(-pid, SIGTERM)
    let graceDeadline = ProcessInfo.processInfo.systemUptime + max(0, gracePeriod)
    while ProcessInfo.processInfo.systemUptime < graceDeadline {
        if !reaped { reaped = (try? reapHelper(pid, status: &status, blocking: false)) ?? true }
        if reaped && !helperGroupExists(pid) { return }
        Thread.sleep(forTimeInterval: 0.01)
    }
    _ = kill(-pid, SIGKILL)
    if !reaped { reaped = (try? reapHelper(pid, status: &status, blocking: true)) ?? true }
    // Acknowledging timeout/cancellation requires actual termination, not
    // merely delivery of a signal. Orphan descendants are reaped by launchd.
    while helperGroupExists(pid) {
        _ = kill(-pid, SIGKILL)
        Thread.sleep(forTimeInterval: 0.01)
    }
}
