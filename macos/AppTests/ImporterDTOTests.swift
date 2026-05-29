import Foundation

func importerDTOTests() -> [AppTest] {
    [
        ("proposed record display title prefers title", {
            let record = fixtureRecord(title: "A Work", slug: "a-work")
            try expectEqual(record.displayTitle, "A Work", "Display title should use title")
        }),
        ("proposed record display title falls back to slug", {
            let record = fixtureRecord(title: "", slug: "fallback-slug")
            try expectEqual(record.displayTitle, "fallback-slug", "Display title should fall back to slug")
        }),
        ("app settings empty has neutral values", {
            let settings = AppSettings.empty
            try expectEqual(settings.workspace_path, "", "Empty workspace path")
            try expectEqual(settings.has_openai_key, false, "Empty OpenAI key state")
            try expectEqual(settings.openai_model, "", "Empty OpenAI model")
            try expectNil(settings.baseline_status, "Empty baseline status")
        }),
        ("pending records response decodes helper JSON", {
            let json = """
            {
              "settings": {
                "workspace_path": "/tmp/workspace",
                "repo_path": "/repo",
                "has_openai_key": true,
                "openai_model": "gpt-5.4-mini",
                "openai_model_source": "preset",
                "workspace_status": "ready",
                "workspace_seed_version": "seed-a",
                "bundle_seed_version": "seed-b",
                "baseline_status": "synced",
                "baseline_source_url": "https://github.com/aaajiao/aaajiao_scraper.git",
                "baseline_branch": "main",
                "baseline_commit": "abc123",
                "baseline_updated_at": "2026-05-29T00:00:00Z",
                "baseline_error": ""
              },
              "batches": [
                {
                  "id": 7,
                  "mode": "manual",
                  "status": "reviewing",
                  "total_records": 1,
                  "accepted_records": 0,
                  "ready_records": 1,
                  "last_error": ""
                }
              ],
              "pending_records": [
                {
                  "id": 11,
                  "batch_id": 7,
                  "url": "https://eventstructure.com/work",
                  "slug": "work",
                  "status": "ready_for_review",
                  "page_type": "artwork",
                  "confidence": 0.91,
                  "is_update": false,
                  "title": "Work",
                  "title_cn": "",
                  "year": "2024",
                  "type": "installation",
                  "materials": "",
                  "size": "",
                  "duration": "",
                  "credits": "",
                  "description_en": "",
                  "description_cn": "",
                  "video_link": "",
                  "images": ["image-a.jpg"],
                  "high_res_images": ["image-a-large.jpg"],
                  "error_message": null
                }
              ]
            }
            """.data(using: .utf8)!
            let response = try JSONDecoder().decode(PendingRecordsResponse.self, from: json)
            try expectEqual(response.settings.openai_model, "gpt-5.4-mini", "Decoded OpenAI model")
            try expectEqual(response.batches.first?.id, 7, "Decoded batch id")
            try expectEqual(response.pending_records.first?.displayTitle, "Work", "Decoded record display title")
            try expectEqual(response.pending_records.first?.images, ["image-a.jpg"], "Decoded images")
        }),
        ("apply response decodes nested preview", {
            let json = """
            {
              "batch_id": 5,
              "applied_commit_sha": "abc123",
              "preview": {
                "batch_id": 5,
                "accepted_count": 2,
                "new_count": 1,
                "updated_count": 1,
                "target_files": ["aaajiao_works.json", "aaajiao_portfolio.md"],
                "will_push": true,
                "error_message": ""
              }
            }
            """.data(using: .utf8)!
            let response = try JSONDecoder().decode(ApplyResponse.self, from: json)
            try expectEqual(response.applied_commit_sha, "abc123", "Decoded applied commit")
            try expectEqual(response.preview.accepted_count, 2, "Decoded accepted count")
            try expectEqual(response.preview.target_files, ["aaajiao_works.json", "aaajiao_portfolio.md"], "Decoded target files")
            try expect(response.preview.will_push, "Decoded preview should allow push")
        }),
    ]
}

private func fixtureRecord(title: String, slug: String) -> ProposedRecord {
    ProposedRecord(
        id: 1,
        batch_id: 1,
        url: "https://eventstructure.com/\(slug)",
        slug: slug,
        status: "ready_for_review",
        page_type: "artwork",
        confidence: 0.9,
        is_update: false,
        title: title,
        title_cn: "",
        year: "",
        type: "",
        materials: "",
        size: "",
        duration: "",
        credits: "",
        description_en: "",
        description_cn: "",
        video_link: "",
        images: [],
        high_res_images: [],
        error_message: nil
    )
}
