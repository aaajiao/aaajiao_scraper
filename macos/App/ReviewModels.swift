import Foundation

enum ReviewFilter: String, CaseIterable, Identifiable {
    case all, pending, accepted, failed

    var id: String { rawValue }
    var title: String {
        switch self {
        case .all: return "All"
        case .pending: return "Pending"
        case .accepted: return "Accepted"
        case .failed: return "Failed"
        }
    }

    func matches(_ record: ProposedRecord) -> Bool {
        switch self {
        case .all: return record.status != "rejected"
        case .pending: return ["ready_for_review", "needs_review"].contains(record.status)
        case .accepted: return record.status == "accepted"
        case .failed: return record.status == "failed"
        }
    }
}

enum RecordField: String, CaseIterable, Identifiable {
    case title
    case titleCN = "title_cn"
    case year, type, materials, size, duration, credits
    case descriptionEN = "description_en"
    case descriptionCN = "description_cn"
    case videoLink = "video_link"
    case images
    case highResImages = "high_res_images"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .title: return "Title (English)"
        case .titleCN: return "Title (Chinese)"
        case .year: return "Year"
        case .type: return "Type"
        case .materials: return "Materials"
        case .size: return "Dimensions"
        case .duration: return "Duration"
        case .credits: return "Credits"
        case .descriptionEN: return "Description (English)"
        case .descriptionCN: return "Description (Chinese)"
        case .videoLink: return "Video URL"
        case .images: return "Images"
        case .highResImages: return "High-resolution images"
        }
    }

    var isMultiline: Bool {
        [.credits, .descriptionEN, .descriptionCN, .images, .highResImages].contains(self)
    }
}

extension ProposedRecord {
    func value(for field: RecordField) -> String {
        if let effective = effective_fields?[field.rawValue] { return effective }
        switch field {
        case .title: return title
        case .titleCN: return title_cn
        case .year: return year
        case .type: return type
        case .materials: return materials
        case .size: return size
        case .duration: return duration
        case .credits: return credits
        case .descriptionEN: return description_en
        case .descriptionCN: return description_cn
        case .videoLink: return video_link
        case .images: return images.joined(separator: "\n")
        case .highResImages: return high_res_images.joined(separator: "\n")
        }
    }

    func baselineValue(for field: RecordField) -> String? {
        baseline_fields?[field.rawValue]
    }
}

func isAbsoluteWebURL(_ value: String) -> Bool {
    guard let parts = URLComponents(string: value),
          ["http", "https"].contains(parts.scheme?.lowercased() ?? ""),
          let host = parts.host, !host.isEmpty else { return false }
    return parts.user == nil && parts.password == nil && !value.contains(where: { $0.isWhitespace })
}

func artworkURLValidationMessage(_ value: String) -> String? {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }
    guard isAbsoluteWebURL(trimmed), let parts = URLComponents(string: trimmed),
          ["eventstructure.com", "www.eventstructure.com"].contains(parts.host?.lowercased() ?? "") else {
        return "Enter a full http(s) artwork URL from eventstructure.com."
    }
    guard !parts.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")).isEmpty else {
        return "Enter an artwork page URL, including its path."
    }
    return nil
}
