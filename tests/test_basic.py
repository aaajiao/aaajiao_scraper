"""
Tests for basic scraper functionality.

Tests BasicScraperMixin methods:
- Sitemap parsing
- Incremental mode with lastmod comparison
- URL validation rules
- Fallback main page scanning
"""

from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from scraper import AaajiaoScraper


class TestGetAllWorkLinks:
    """Test suite for get_all_work_links method."""

    def test_full_mode_parses_sitemap(self, scraper_with_mock_cache, mock_sitemap_xml):
        """Test full mode returns all valid work links."""
        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = mock_sitemap_xml.encode()
            mock_get.return_value = mock_response
            
            links = scraper_with_mock_cache.get_all_work_links(incremental=False)
            
            # Should return 2 work links (excluding /about)
            assert len(links) == 2
            assert "https://eventstructure.com/work/test-1" in links
            assert "https://eventstructure.com/work/test-2" in links
            assert "https://eventstructure.com/about" not in links

    def test_full_mode_saves_to_cache(self, scraper_with_mock_cache, mock_sitemap_xml, temp_cache_dir):
        """Test that full mode saves sitemap to cache."""
        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = mock_sitemap_xml.encode()
            mock_get.return_value = mock_response
            
            scraper_with_mock_cache.get_all_work_links(incremental=False)
            
            # Check cache file exists
            cache_file = temp_cache_dir / "sitemap_lastmod.json"
            assert cache_file.exists()

    def test_incremental_mode_detects_new_urls(self, scraper_with_mock_cache, temp_cache_dir):
        """Test incremental mode detects new URLs."""
        # Save old sitemap
        old_sitemap = {
            "https://eventstructure.com/work/test-1": "2024-01-01"
        }
        scraper_with_mock_cache._save_sitemap_cache(old_sitemap)
        
        # New sitemap with additional URL
        new_sitemap_xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://eventstructure.com/work/test-1</loc>
        <lastmod>2024-01-01</lastmod>
    </url>
    <url>
        <loc>https://eventstructure.com/work/test-2</loc>
        <lastmod>2024-01-02</lastmod>
    </url>
</urlset>"""
        
        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = new_sitemap_xml.encode()
            mock_get.return_value = mock_response
            
            links = scraper_with_mock_cache.get_all_work_links(incremental=True)
            
            # Should only return new URL
            assert len(links) == 1
            assert "https://eventstructure.com/work/test-2" in links

    def test_incremental_mode_detects_modified_urls(self, scraper_with_mock_cache):
        """Test incremental mode detects modified URLs by lastmod."""
        # Old sitemap
        old_sitemap = {
            "https://eventstructure.com/work/test-1": "2024-01-01"
        }
        scraper_with_mock_cache._save_sitemap_cache(old_sitemap)
        
        # Same URL but newer lastmod
        new_sitemap_xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://eventstructure.com/work/test-1</loc>
        <lastmod>2024-01-15</lastmod>
    </url>
</urlset>"""
        
        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = new_sitemap_xml.encode()
            mock_get.return_value = mock_response
            
            links = scraper_with_mock_cache.get_all_work_links(incremental=True)
            
            # Should return modified URL
            assert len(links) == 1
            assert "https://eventstructure.com/work/test-1" in links

    def test_incremental_mode_no_changes(self, scraper_with_mock_cache, caplog):
        """Test incremental mode with no changes."""
        import logging
        caplog.set_level(logging.INFO)

        # Identical sitemap
        sitemap_data = {
            "https://eventstructure.com/work/test-1": "2024-01-01"
        }
        scraper_with_mock_cache._save_sitemap_cache(sitemap_data)

        sitemap_xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://eventstructure.com/work/test-1</loc>
        <lastmod>2024-01-01</lastmod>
    </url>
</urlset>"""

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = sitemap_xml.encode()
            mock_get.return_value = mock_response

            links = scraper_with_mock_cache.get_all_work_links(incremental=True)

            # Should return empty list
            assert len(links) == 0
            assert "No updates detected" in caplog.text

    def test_sitemap_failure_triggers_fallback(self, scraper_with_mock_cache, caplog):
        """Test that sitemap failure triggers fallback scanning."""
        import logging
        caplog.set_level(logging.INFO)

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            # First call (sitemap) fails
            mock_get.side_effect = [
                Exception("Sitemap timeout"),
                MagicMock(status_code=200, content=b"<html></html>")
            ]

            links = scraper_with_mock_cache.get_all_work_links(incremental=False)

            # Should have attempted fallback
            assert "Sitemap parsing failed" in caplog.text
            assert "Attempting to scan main page" in caplog.text


class TestFallbackScanMainPage:
    """Test suite for _fallback_scan_main_page method."""

    def test_extracts_links_from_main_page(self, scraper_with_mock_cache):
        """Test extraction of links from main page HTML."""
        html = """
        <html>
            <body>
                <a href="https://eventstructure.com/work/art1">Art 1</a>
                <a href="/work/art2">Art 2</a>
                <a href="https://eventstructure.com/about">About</a>
            </body>
        </html>
        """
        
        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = html.encode()
            mock_get.return_value = mock_response
            
            links = scraper_with_mock_cache._fallback_scan_main_page()
            
            # Should extract work links and convert relative URLs
            assert len(links) == 2
            assert "https://eventstructure.com/work/art1" in links
            assert "https://eventstructure.com/work/art2" in links

    def test_fallback_handles_errors_gracefully(self, scraper_with_mock_cache, caplog):
        """Test that fallback handles errors and returns empty list."""
        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            
            links = scraper_with_mock_cache._fallback_scan_main_page()
            
            assert links == []
            assert "Main page scanning failed" in caplog.text


class TestIsValidWorkLink:
    """Test suite for _is_valid_work_link method."""

    def test_valid_work_link(self, scraper_with_mock_cache):
        """Test that valid work links are accepted."""
        valid_urls = [
            "https://eventstructure.com/work/my-artwork",
            "https://eventstructure.com/project/2024",
            "https://eventstructure.com/installation-name",
        ]
        
        for url in valid_urls:
            assert scraper_with_mock_cache._is_valid_work_link(url) is True

    def test_invalid_navigation_links(self, scraper_with_mock_cache):
        """Test that navigation links are rejected."""
        invalid_urls = [
            "https://eventstructure.com/",
            "https://eventstructure.com/about",
            "https://eventstructure.com/contact",
            "https://eventstructure.com/cv",
            "https://eventstructure.com/aaajiao",
        ]
        
        for url in invalid_urls:
            assert scraper_with_mock_cache._is_valid_work_link(url) is False

    def test_tag_pages_rejected(self, scraper_with_mock_cache):
        """Test that tag archive pages are rejected."""
        tag_urls = [
            "https://eventstructure.com/tag/video",
            "https://eventstructure.com/tag/installation",
        ]
        
        for url in tag_urls:
            assert scraper_with_mock_cache._is_valid_work_link(url) is False

    def test_external_domain_rejected(self, scraper_with_mock_cache):
        """Test that URLs from other domains are rejected."""
        external_urls = [
            "https://google.com/work/test",
            "https://example.com/art",
        ]
        
        for url in external_urls:
            assert scraper_with_mock_cache._is_valid_work_link(url) is False

    def test_rss_feed_rejected(self, scraper_with_mock_cache):
        """Test that RSS/feed URLs are rejected."""
        feed_urls = [
            "https://eventstructure.com/rss",
            "https://eventstructure.com/feed",
        ]
        
        for url in feed_urls:
            assert scraper_with_mock_cache._is_valid_work_link(url) is False

    def test_sitemap_url_rejected(self, scraper_with_mock_cache):
        """Test that sitemap URL is rejected."""
        assert scraper_with_mock_cache._is_valid_work_link("https://eventstructure.com/sitemap") is False


class TestExtractMetadataBS4:
    """Test suite for extract_metadata_bs4 method - materials and credits extraction."""

    def test_extracts_physical_materials(self, scraper_with_mock_cache):
        """Test extraction of physical materials from HTML."""
        html = """
        <html>
            <div class="project_title">Test Work / 测试作品</div>
            <div class="project_content">
                2024
                Video Installation / 视频装置
                LED, acrylic, wood
                Dimension variable / 尺寸可变
                Some long description that goes on and on to explain the artwork
                in detail and provide context about the artistic vision behind it.
            </div>
        </html>
        """

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = html.encode()
            mock_get.return_value = mock_response

            result = scraper_with_mock_cache.extract_metadata_bs4(
                "https://eventstructure.com/test-work"
            )

            assert result is not None
            assert result["title"] == "Test Work"
            assert result["title_cn"] == "测试作品"
            assert result["year"] == "2024"
            assert "LED" in result["materials"] or "acrylic" in result["materials"]
            assert result["credits"] == ""

    def test_separates_credits_from_materials(self, scraper_with_mock_cache):
        """Test that credits are extracted separately from materials."""
        html = """
        <html>
            <div class="project_title">Test Work</div>
            <div class="project_content">
                2024
                Installation
                concept: aaajiao; sound: yang2; software: aaajiao
                Some description about the work.
            </div>
        </html>
        """

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = html.encode()
            mock_get.return_value = mock_response

            result = scraper_with_mock_cache.extract_metadata_bs4(
                "https://eventstructure.com/test-work"
            )

            assert result is not None
            # Credits should be extracted, materials should be empty
            assert "concept:" in result["credits"] or "aaajiao" in result["credits"]
            assert result["materials"] == ""

    def test_extracts_photo_credits(self, scraper_with_mock_cache):
        """Test extraction of photo credits."""
        html = """
        <html>
            <div class="project_title">Test Work</div>
            <div class="project_content">
                2024
                Sculpture
                Photo: Trevor Good
                Silicone, fiberglass
            </div>
        </html>
        """

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = html.encode()
            mock_get.return_value = mock_response

            result = scraper_with_mock_cache.extract_metadata_bs4(
                "https://eventstructure.com/test-work"
            )

            assert result is not None
            assert "Photo" in result["credits"] or "Trevor" in result["credits"]
            # Materials should contain silicone/fiberglass, not photo credit
            if result["materials"]:
                assert "Photo" not in result["materials"]

    def test_handles_bilingual_materials(self, scraper_with_mock_cache):
        """Test extraction of bilingual materials format."""
        html = """
        <html>
            <div class="project_title">Test Work</div>
            <div class="project_content">
                2024
                Print
                Screen printing, silicone skin / 丝网印刷、硅胶皮
                180 x 180 cm
            </div>
        </html>
        """

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = html.encode()
            mock_get.return_value = mock_response

            result = scraper_with_mock_cache.extract_metadata_bs4(
                "https://eventstructure.com/test-work"
            )

            assert result is not None
            # Should extract bilingual materials line
            assert "screen printing" in result["materials"].lower() or "丝网印刷" in result["materials"]

    def test_type_not_polluted_by_credits(self, scraper_with_mock_cache):
        """Test that type field is not polluted by credits info."""
        html = """
        <html>
            <div class="project_title">Test Work</div>
            <div class="project_content">
                2024
                Photo: John Smith
                Video Installation
                LED screens
            </div>
        </html>
        """

        with patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = html.encode()
            mock_get.return_value = mock_response

            result = scraper_with_mock_cache.extract_metadata_bs4(
                "https://eventstructure.com/test-work"
            )

            assert result is not None
            # Type should be Video Installation, not Photo credit
            if result["type"]:
                assert "Video" in result["type"] or "Installation" in result["type"]
                assert "Photo:" not in result["type"]
