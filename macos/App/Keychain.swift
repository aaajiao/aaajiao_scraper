import Foundation
import Security

enum KeychainStore {
    /// Result of a load attempt, distinguishing "never saved" from a genuine
    /// Keychain access failure (e.g. locked keychain, auth failure) so callers
    /// can surface the right message instead of treating both as "no key".
    enum LoadResult {
        case found(String)
        case notFound
        case failure(OSStatus)
    }

    private static let service = "com.aaajiao.importer"
    private static let account = "openai_api_key"
    private static var query: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }

    static func save(_ value: String) throws {
        let data = Data(value.utf8)
        SecItemDelete(query as CFDictionary)
        var attrs = query
        attrs[kSecValueData as String] = data
        let status = SecItemAdd(attrs as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }

    static func load() -> LoadResult {
        var query = query
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
                return .failure(status)
            }
            return .found(value)
        case errSecItemNotFound:
            return .notFound
        default:
            return .failure(status)
        }
    }

    static func delete() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }
}
