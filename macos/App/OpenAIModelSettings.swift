import Foundation

enum OpenAIModelPreset: String, CaseIterable, Identifiable {
    case gpt41 = "gpt-4.1"
    case gpt54Mini = "gpt-5.4-mini"
    case custom = "custom"

    static let defaultPreset: Self = .gpt41

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .gpt41:
            return "gpt-4.1"
        case .gpt54Mini:
            return "gpt-5.4-mini"
        case .custom:
            return "Custom"
        }
    }

    var modelName: String {
        switch self {
        case .gpt41, .gpt54Mini:
            return rawValue
        case .custom:
            return ""
        }
    }

    var source: String {
        switch self {
        case .custom:
            return "custom"
        case .gpt41, .gpt54Mini:
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
        case .gpt41, .gpt54Mini:
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
    private static let presetKey = "openai_model_preset"
    private static let customModelKey = "openai_model_custom"

    static func load(defaults: UserDefaults = .standard) -> OpenAIModelSelection {
        let rawPreset = defaults.string(forKey: presetKey) ?? OpenAIModelPreset.defaultPreset.rawValue
        let preset: OpenAIModelPreset
        if rawPreset == "gpt-5.1" {
            preset = .gpt54Mini
        } else {
            preset = OpenAIModelPreset(rawValue: rawPreset) ?? .defaultPreset
        }
        let customModel = defaults.string(forKey: customModelKey) ?? ""
        let selection = OpenAIModelSelection(preset: preset, customModel: customModel)
        if selection.isValid {
            return selection
        }
        return OpenAIModelSelection(preset: .defaultPreset, customModel: "")
    }

    static func save(_ selection: OpenAIModelSelection, defaults: UserDefaults = .standard) {
        defaults.set(selection.preset.rawValue, forKey: presetKey)
        defaults.set(selection.customModel, forKey: customModelKey)
    }
}
