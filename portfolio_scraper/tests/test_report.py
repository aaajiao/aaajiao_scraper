"""
Tests for report generation functionality.

Tests ReportMixin methods:
- JSON export
- Markdown generation
- Agent report with image downloads
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scraper import AaajiaoScraper


class TestSaveToJson:
    """Test suite for save_to_json method."""

    def test_saves_works_to_json(self, scraper_with_mock_cache, sample_artwork_data, tmp_path):
        """Test saving works to JSON file."""
        scraper_with_mock_cache.works = [sample_artwork_data]
        output_file = tmp_path / "test_works.json"
        
        scraper_with_mock_cache.save_to_json(str(output_file))
        
        assert output_file.exists()
        
        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert len(data) == 1
        assert data[0]["title"] == "Test Artwork"

    def test_json_encoding_preserves_chinese(self, scraper_with_mock_cache, tmp_path):
        """Test that Chinese characters are preserved in JSON."""
        scraper_with_mock_cache.works = [
            {"title_cn": "测试作品", "description_cn": "这是一个测试"}
        ]
        output_file = tmp_path / "test.json"
        
        scraper_with_mock_cache.save_to_json(str(output_file))
        
        with open(output_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Chinese characters should not be escaped
        assert "测试作品" in content
        assert "\\u" not in content  # No unicode escapes


class TestGenerateMarkdown:
    """Test suite for generate_markdown method."""

    def test_generates_markdown_file(self, scraper_with_mock_cache, sample_artwork_data, tmp_path):
        """Test markdown generation."""
        scraper_with_mock_cache.works = [sample_artwork_data]
        output_file = tmp_path / "test.md"
        
        scraper_with_mock_cache.generate_markdown(str(output_file))
        
        assert output_file.exists()
        
        content = output_file.read_text(encoding="utf-8")
        assert "# aaajiao 作品集" in content
        assert "Test Artwork" in content
        assert "2024" in content

    def test_sorts_by_year_descending(self, scraper_with_mock_cache, tmp_path):
        """Test that works are sorted by year in descending order."""
        scraper_with_mock_cache.works = [
            {"title": "Work 2020", "year": "2020", "url": "http://test.com/1"},
            {"title": "Work 2023", "year": "2023", "url": "http://test.com/2"},
            {"title": "Work 2021", "year": "2021", "url": "http://test.com/3"},
        ]
        output_file = tmp_path / "test.md"
        
        scraper_with_mock_cache.generate_markdown(str(output_file))
        
        content = output_file.read_text()
        # Should appear in order: 2023, 2021, 2020
        pos_2023 = content.find("Work 2023")
        pos_2021 = content.find("Work 2021")
        pos_2020 = content.find("Work 2020")
        
        assert pos_2023 < pos_2021 < pos_2020

    def test_includes_bilingual_titles(self, scraper_with_mock_cache, tmp_path):
        """Test bilingual title formatting."""
        scraper_with_mock_cache.works = [
            {
                "title": "English Title",
                "title_cn": "中文标题",
                "year": "2024",
                "url": "http://test.com"
            }
        ]
        output_file = tmp_path / "test.md"
        
        scraper_with_mock_cache.generate_markdown(str(output_file))
        
        content = output_file.read_text()
        # Title is formatted as a link: [English Title](url) / 中文标题
        assert "English Title" in content
        assert "中文标题" in content


class TestGenerateAgentReport:
    """Test suite for generate_agent_report method."""

    def test_creates_report_directory(self, scraper_with_mock_cache, tmp_path):
        """Test that report directory is created."""
        data = {"data": [{"title": "Test", "url": "http://test.com"}]}
        output_dir = tmp_path / "report_output"
        
        with patch("requests.get"):  # Mock image download
            scraper_with_mock_cache.generate_agent_report(
                data, str(output_dir), prompt="test"
            )
        
        assert output_dir.exists()

    def test_downloads_images(self, scraper_with_mock_cache, tmp_path):
        """Test that images are downloaded."""
        data = {
            "data": [{
                "title": "Test",
                "url": "http://test.com",
                "high_res_images": [
                    "https://example.com/img1.jpg",
                    "https://example.com/img2.jpg"
                ]
            }]
        }
        output_dir = tmp_path / "report"
        
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"fake image data"
            mock_get.return_value = mock_response
            
            report_path = scraper_with_mock_cache.generate_agent_report(
                data, str(output_dir), prompt="test"
            )
            
            # Check images directory exists
            images_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("images_")]
            assert len(images_dirs) == 1
            
            # Check image files
            image_files = list(images_dirs[0].iterdir())
            assert len(image_files) == 2

    def test_generates_markdown_report(self, scraper_with_mock_cache, tmp_path):
        """Test markdown report generation."""
        data = {
            "data": [{
                "title": "Test Artwork",
                "title_cn": "测试作品",
                "year": "2024",
                "description_en": "Test description",
            }]
        }
        output_dir = tmp_path / "report"
        
        with patch("requests.get"):
            report_path = scraper_with_mock_cache.generate_agent_report(
                data, str(output_dir), prompt="test", extraction_level="full"
            )
        
        assert os.path.exists(report_path)
        
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        assert "作品提取报告" in content
        assert "Test Artwork" in content
        assert "FULL" in content

    def test_saves_json_data(self, scraper_with_mock_cache, tmp_path):
        """Test that JSON data is saved alongside report."""
        data = {"data": [{"title": "Test"}]}
        output_dir = tmp_path / "report"
        
        with patch("requests.get"):
            scraper_with_mock_cache.generate_agent_report(
                data, str(output_dir), prompt="test prompt"
            )
        
        # Find JSON file
        json_files = [f for f in output_dir.iterdir() if f.suffix == ".json"]
        assert len(json_files) == 1
        
        with open(json_files[0], "r") as f:
            saved_data = json.load(f)
        
        assert saved_data["_meta"]["prompt"] == "test prompt"
        assert saved_data["data"] == data["data"]

    def test_handles_image_download_errors(self, scraper_with_mock_cache, tmp_path, caplog):
        """Test that image download errors are logged."""
        data = {
            "data": [{
                "title": "Test",
                "high_res_images": ["https://fail.com/img.jpg"]
            }]
        }
        output_dir = tmp_path / "report"
        
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            
            scraper_with_mock_cache.generate_agent_report(data, str(output_dir))
        
        assert "Image download failed" in caplog.text
