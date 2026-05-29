import Foundation

struct AppTestFailure: Error, CustomStringConvertible {
    let message: String

    var description: String {
        message
    }
}

typealias AppTest = (name: String, body: () throws -> Void)

func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() {
        throw AppTestFailure(message: message)
    }
}

func expectEqual<T: Equatable>(_ actual: T, _ expected: T, _ message: String) throws {
    if actual != expected {
        throw AppTestFailure(message: "\(message). Expected \(expected), got \(actual)")
    }
}

func expectNil<T>(_ value: T?, _ message: String) throws {
    if value != nil {
        throw AppTestFailure(message: "\(message). Expected nil, got \(String(describing: value))")
    }
}

func expectNotNil<T>(_ value: T?, _ message: String) throws {
    if value == nil {
        throw AppTestFailure(message: "\(message). Expected non-nil value")
    }
}

func isolatedDefaults(_ testName: String) -> UserDefaults {
    let suiteName = "com.aaajiao.importer.tests.\(testName).\(UUID().uuidString)"
    guard let defaults = UserDefaults(suiteName: suiteName) else {
        fatalError("Could not create isolated UserDefaults suite")
    }
    defaults.removePersistentDomain(forName: suiteName)
    return defaults
}

func runAppTests(_ tests: [AppTest]) {
    var failures: [String] = []
    for test in tests {
        do {
            try test.body()
            print("PASS \(test.name)")
        } catch {
            failures.append("\(test.name): \(error)")
            print("FAIL \(test.name): \(error)")
        }
    }

    if failures.isEmpty {
        print("App tests passed: \(tests.count)")
    } else {
        fputs("App tests failed: \(failures.count) of \(tests.count)\n", stderr)
        for failure in failures {
            fputs("- \(failure)\n", stderr)
        }
        exit(1)
    }
}
