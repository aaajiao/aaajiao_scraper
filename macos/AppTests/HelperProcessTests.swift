import Foundation
import Darwin

private final class HelperProcessFixture {
    let directory: URL
    let executable: URL

    init(script: (URL) -> String) throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("aaajiao-process-tests-\(UUID().uuidString)", isDirectory: true)
        executable = directory.appendingPathComponent("helper.sh")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try ("#!/bin/sh\n" + script(directory)).write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
    }

    deinit { try? FileManager.default.removeItem(at: directory) }

    func client() -> HelperClient {
        HelperClient(executableURL: executable, terminationGracePeriod: 0.05)
    }

    func pid(_ name: String) throws -> pid_t {
        let value = try String(contentsOf: directory.appendingPathComponent(name), encoding: .utf8)
        guard let pid = Int32(value.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw AppTestFailure(message: "Invalid fixture PID: \(value)")
        }
        return pid
    }

    func waitForFile(_ name: String) throws {
        let path = directory.appendingPathComponent(name).path
        let deadline = Date(timeIntervalSinceNow: 3)
        while Date() < deadline {
            if let attributes = try? FileManager.default.attributesOfItem(atPath: path),
               (attributes[.size] as? NSNumber)?.intValue ?? 0 > 0 { return }
            Thread.sleep(forTimeInterval: 0.01)
        }
        throw AppTestFailure(message: "Helper did not create \(name)")
    }
}

private final class HelperProcessResult: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Result<Data, Error>?
    let finished = DispatchSemaphore(value: 0)

    func run(_ body: @escaping @Sendable () throws -> Data) {
        DispatchQueue.global().async {
            let result = Result { try body() }
            self.lock.lock()
            self.value = result
            self.lock.unlock()
            self.finished.signal()
        }
    }

    func result() throws -> Result<Data, Error> {
        guard finished.wait(timeout: .now() + 5) == .success else {
            throw AppTestFailure(message: "Helper did not finish and reap its process group")
        }
        lock.lock()
        defer { lock.unlock() }
        return value!
    }
}

private func expectProcessStopped(_ pid: pid_t) throws {
    let result = kill(pid, 0)
    try expect(result == -1 && errno == ESRCH, "Process \(pid) is still alive after the helper returned")
}

func helperProcessTests() -> [AppTest] {
    [
        ("helper timeout kills and reaps an uncooperative process group", {
            let fixture = try HelperProcessFixture { directory in
                """
                trap '' TERM
                echo $$ > '\(directory.path)/parent.pid'
                /bin/sh -c 'trap "" TERM; echo $$ > "$1"; while :; do /bin/sleep 5; done' child '\(directory.path)/child.pid' &
                wait
                """
            }
            // A child outside the helper group must remain untouched.
            let unrelated = Process()
            unrelated.executableURL = URL(fileURLWithPath: "/bin/sleep")
            unrelated.arguments = ["60"]
            try unrelated.run()
            defer {
                if unrelated.isRunning { unrelated.terminate() }
                unrelated.waitUntilExit()
            }
            let started = Date()
            do {
                _ = try fixture.client().runRawCommand(arguments: ["startIncrementalSync"], timeout: 2)
                throw AppTestFailure(message: "Expected helper timeout")
            } catch HelperClientError.timeout(let command, _) {
                try expectEqual(command, "startIncrementalSync", "Timed-out command")
            }
            try expect(Date().timeIntervalSince(started) < 5, "SIGKILL escalation should bound termination time")
            try expectProcessStopped(fixture.pid("parent.pid"))
            try expectProcessStopped(fixture.pid("child.pid"))
            try expect(unrelated.isRunning, "Timeout cleanup must not signal unrelated processes")
        }),
        ("helper cancellation waits for parent and child termination", {
            let fixture = try HelperProcessFixture { directory in
                """
                trap '' TERM
                echo $$ > '\(directory.path)/parent.pid'
                /bin/sh -c 'trap "" TERM; echo $$ > "$1"; while :; do /bin/sleep 5; done' child '\(directory.path)/child.pid' &
                wait
                """
            }
            let client = fixture.client()
            let run = HelperProcessResult()
            run.run { try client.runRawCommand(arguments: ["submitManualURL"], timeout: 4) }
            try fixture.waitForFile("child.pid")
            try expect(client.cancelCurrentCommand(), "An active import must accept cancellation")
            switch try run.result() {
            case .failure(HelperClientError.cancelled): break
            case .failure(let error): throw AppTestFailure(message: "Expected cancellation, got \(error)")
            case .success: throw AppTestFailure(message: "Cancelled helper unexpectedly succeeded")
            }
            try expectProcessStopped(fixture.pid("parent.pid"))
            try expectProcessStopped(fixture.pid("child.pid"))
            try expect(!client.cancelCurrentCommand(), "An idle helper has nothing to cancel")
        }),
        ("helper never accepts user cancellation during publishing", {
            let fixture = try HelperProcessFixture { directory in
                """
                echo $$ > '\(directory.path)/parent.pid'
                /bin/sleep 0.2
                printf 'published'
                """
            }
            let client = fixture.client()
            let run = HelperProcessResult()
            run.run { try client.runRawCommand(arguments: ["applyAcceptedRecords"], timeout: 3) }
            try fixture.waitForFile("parent.pid")
            try expect(!client.cancelCurrentCommand(), "Publishing cannot be interrupted by an import cancel action")
            let output = try run.result().get()
            try expectEqual(String(decoding: output, as: UTF8.self), "published", "Protected command completes")
        }),
        ("helper cancellation is limited to the explicit import allowlist", {
            for (command, expected) in [
                ("startIncrementalSync", true),
                ("submitManualURL", true),
                ("retryRecord", true),
                ("refreshWorkspaceBaseline", false),
                ("resetWorkspace", false),
                ("deleteBatch", false),
                ("applyAcceptedRecords", false),
            ] {
                let fixture = try HelperProcessFixture { directory in
                    """
                    echo $$ > '\(directory.path)/parent.pid'
                    /bin/sleep 0.15
                    printf 'done'
                    """
                }
                let client = fixture.client()
                let run = HelperProcessResult()
                run.run { try client.runRawCommand(arguments: [command], timeout: 2) }
                try fixture.waitForFile("parent.pid")
                try expectEqual(client.cancelCurrentCommand(), expected, "Cancellation policy for \(command)")
                let result = try run.result()
                if expected {
                    guard case .failure(HelperClientError.cancelled) = result else {
                        throw AppTestFailure(message: "\(command) did not report cancellation")
                    }
                } else {
                    _ = try result.get()
                }
                try expectProcessStopped(fixture.pid("parent.pid"))
            }
        }),
        ("helper drains large stdout and stderr without deadlock or truncation", {
            let fixture = try HelperProcessFixture { _ in
                """
                /usr/bin/awk 'BEGIN { for (i=0; i<32768; i++) printf "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" }'
                /usr/bin/awk 'BEGIN { for (i=0; i<32768; i++) print "stderr output must be drained while the process is running" }' >&2
                """
            }
            let data = try fixture.client().runRawCommand(arguments: ["listPendingRecords"], timeout: 5)
            let expected = String(repeating: "0123456789abcdef", count: 131072)
            try expectEqual(data, Data(expected.utf8), "All stdout bytes should be retained")
        }),
        ("helper cleans surviving descendants after a successful parent exit", {
            let fixture = try HelperProcessFixture { directory in
                """
                /bin/sleep 60 &
                echo $! > '\(directory.path)/child.pid'
                printf 'complete'
                """
            }
            let data = try fixture.client().runRawCommand(arguments: ["listPendingRecords"], timeout: 2)
            try expectEqual(String(decoding: data, as: UTF8.self), "complete", "Successful parent output")
            try expectProcessStopped(fixture.pid("child.pid"))
        }),
        ("helper remains reusable after a timeout", {
            let fixture = try HelperProcessFixture { _ in
                """
                if [ "$1" = 'submitManualURL' ]; then
                    /bin/sleep 60
                else
                    printf 'ready'
                fi
                """
            }
            let client = fixture.client()
            do {
                _ = try client.runRawCommand(arguments: ["submitManualURL"], timeout: 0.1)
                throw AppTestFailure(message: "Expected timeout")
            } catch HelperClientError.timeout { }
            let data = try client.runRawCommand(arguments: ["listPendingRecords"], timeout: 1)
            try expectEqual(String(decoding: data, as: UTF8.self), "ready", "A timed-out command must fully release the client")
        }),
    ]
}
