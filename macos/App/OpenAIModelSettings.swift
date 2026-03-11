import Foundation

enum OpenAIModelPreset: String, CaseIterable, Identifiable {
    case gpt41 = "gpt-4.1"
    case gpt51 = "gpt-5.1"
    case custom = "custom"

    static let defaultPreset: Self = .gpt41

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .gpt41:
            return "gpt-4.1"
        case .gpt51:
            return "gpt-5.1"
        case .custom:
            return "Custom"
        }
    }

    var modelName: String {
        switch self {
        case .gpt41, .gpt51:
            return rawValue
        case .custom:
            return ""
        }
    }

    var source: String {
        switch self {
        case .custom:
            return "custom"
        case .gpt41, .gpt51:
            return "preset"
        }
    }
}

struct OpenAIModelSelection: Equatable {
    let preset: OpenAIModelPreset
    let customModel: String

    var effectiveModel: String {
        switch preset {
        case .custom:
            return customModel.trimmingCharacters(in: .whitespacesAndNewlines)
        case .gpt41, .gpt51:
            return preset.modelName
        }
    }

    var source: String {
        preset.source
    }

    var isValid: Bool {
        !effectiveModel.isEmpty
    }
}

enum OpenAIModelSettingsStore {
    private static let defaults = UserDefaults.standard
    private static let presetKey = "openai_model_preset"
    private static let customModelKey = "openai_model_custom"

    static func load() -> OpenAIModelSelection {
        let rawPreset = defaults.string(forKey: presetKey) ?? OpenAIModelPreset.defaultPreset.rawValue
        let preset = OpenAIModelPreset(rawValue: rawPreset) ?? .defaultPreset
        let customModel = defaults.string(forKey: customModelKey) ?? ""
        let selection = OpenAIModelSelection(preset: preset, customModel: customModel)
        if selection.isValid {
            return selection
        }
        return OpenAIModelSelection(preset: .defaultPreset, customModel: "")
    }

    static func save(_ selection: OpenAIModelSelection) {
        defaults.set(selection.preset.rawValue, forKey: presetKey)
        defaults.set(selection.customModel, forKey: customModelKey)
    }
}
