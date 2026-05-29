import Foundation

func openAIModelSettingsTests() -> [AppTest] {
    [
        ("model presets expose gpt-4.1, gpt-5.4-mini, and custom", {
            let rawValues = OpenAIModelPreset.allCases.map(\.rawValue)
            try expectEqual(rawValues, ["gpt-4.1", "gpt-5.4-mini", "custom"], "Unexpected preset order")
            try expect(!rawValues.contains("gpt-5.1"), "gpt-5.1 should not remain as a selectable preset")
        }),
        ("default preset remains gpt-4.1", {
            try expectEqual(OpenAIModelPreset.defaultPreset, .gpt41, "Default preset changed")
            try expectEqual(OpenAIModelSelection(preset: .gpt41, customModel: "").effectiveModel, "gpt-4.1", "gpt-4.1 effective model")
            try expectEqual(OpenAIModelSelection(preset: .gpt41, customModel: "").source, "preset", "gpt-4.1 source")
        }),
        ("gpt-5.4-mini preset resolves to preset source", {
            let selection = OpenAIModelSelection(preset: .gpt54Mini, customModel: "")
            try expectEqual(selection.effectiveModel, "gpt-5.4-mini", "gpt-5.4-mini effective model")
            try expectEqual(selection.source, "preset", "gpt-5.4-mini source")
            try expect(selection.isValid, "gpt-5.4-mini preset should be valid")
        }),
        ("custom model trims whitespace and marks source custom", {
            let selection = OpenAIModelSelection(preset: .custom, customModel: "  gpt-custom-model  ")
            try expectEqual(selection.effectiveModel, "gpt-custom-model", "Custom model should be trimmed")
            try expectEqual(selection.source, "custom", "Custom model source")
            try expect(selection.isValid, "Non-empty custom model should be valid")
        }),
        ("blank custom model is invalid", {
            let selection = OpenAIModelSelection(preset: .custom, customModel: "   ")
            try expectEqual(selection.effectiveModel, "", "Blank custom model should trim to empty")
            try expect(!selection.isValid, "Blank custom model should be invalid")
        }),
        ("store loads default selection from empty preferences", {
            let defaults = isolatedDefaults("empty")
            let selection = OpenAIModelSettingsStore.load(defaults: defaults)
            try expectEqual(selection.preset, .gpt41, "Empty store should load default preset")
            try expectEqual(selection.customModel, "", "Empty store should not invent custom model")
        }),
        ("store saves and loads gpt-5.4-mini", {
            let defaults = isolatedDefaults("mini")
            let expected = OpenAIModelSelection(preset: .gpt54Mini, customModel: "")
            OpenAIModelSettingsStore.save(expected, defaults: defaults)
            try expectEqual(OpenAIModelSettingsStore.load(defaults: defaults), expected, "Saved mini preset should round-trip")
        }),
        ("store saves and loads custom model", {
            let defaults = isolatedDefaults("custom")
            let expected = OpenAIModelSelection(preset: .custom, customModel: "gpt-custom")
            OpenAIModelSettingsStore.save(expected, defaults: defaults)
            try expectEqual(OpenAIModelSettingsStore.load(defaults: defaults), expected, "Saved custom model should round-trip")
        }),
        ("store falls back when saved custom model is blank", {
            let defaults = isolatedDefaults("blank-custom")
            OpenAIModelSettingsStore.save(OpenAIModelSelection(preset: .custom, customModel: "   "), defaults: defaults)
            let selection = OpenAIModelSettingsStore.load(defaults: defaults)
            try expectEqual(selection, OpenAIModelSelection(preset: .gpt41, customModel: ""), "Invalid saved custom model should fall back")
        }),
        ("store migrates legacy gpt-5.1 preset to gpt-5.4-mini", {
            let defaults = isolatedDefaults("legacy")
            defaults.set("gpt-5.1", forKey: "openai_model_preset")
            defaults.set("", forKey: "openai_model_custom")
            let selection = OpenAIModelSettingsStore.load(defaults: defaults)
            try expectEqual(selection, OpenAIModelSelection(preset: .gpt54Mini, customModel: ""), "Legacy gpt-5.1 should migrate to mini")
        }),
        ("store falls back for unknown raw preset", {
            let defaults = isolatedDefaults("unknown")
            defaults.set("gpt-unknown", forKey: "openai_model_preset")
            let selection = OpenAIModelSettingsStore.load(defaults: defaults)
            try expectEqual(selection, OpenAIModelSelection(preset: .gpt41, customModel: ""), "Unknown preset should fall back")
        }),
    ]
}
