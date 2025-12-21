"""
Tests for Firecrawl API integration.

Tests FirecrawlMixin methods with mocked API responses:
- extract_work_details with retry logic
- agent_search for batch extraction and agent mode
- discover_urls_with_scroll for infinite-scroll pages
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from scraper import AaajiaoScraper


class TestExtractWorkDetails:
    """Test suite for extract_work_details method."""

    def test_successful_extraction(self, scraper_with_mock_cache, mock_firecrawl_response):
        """Test successful artwork extraction."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_firecrawl_response
            mock_post.return_value = mock_response
            
            result = scraper_with_mock_cache.extract_work_details(
                "https://eventstructure.com/test"
            )
            
            assert result is not None
            assert result["title"] == "Test Artwork"
            assert result["title_cn"] == "测试作品"
            assert result["year"] == "2024"

    def test_extracts_splits_bilingual_title(self, scraper_with_mock_cache):
        """Test automatic splitting of bilingual titles."""
        response = {
            "success": True,
            "data": {
                "extract": {
                    "title": "English Title / 中文标题",
                    "title_cn": "",  # AI didn't split
                    "year": "2024",
                }
            },
        }
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response
            mock_post.return_value = mock_response
            
            result = scraper_with_mock_cache.extract_work_details(
                "https://eventstructure.com/test"
            )
            
            # Should auto-split the title
            assert result["title"] == "English Title"
            assert result["title_cn"] == "中文标题"

    def test_uses_cache_when_available(self, scraper_with_mock_cache, sample_artwork_data):
        """Test that cached data is returned without API call."""
        url = "https://eventstructure.com/test"
        
        # Pre-populate cache
        scraper_with_mock_cache._save_cache(url, sample_artwork_data)
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            result = scraper_with_mock_cache.extract_work_details(url)
            
            # Should not have called API
            mock_post.assert_not_called()
            assert result == sample_artwork_data

    def test_saves_to_cache_after_extraction(self, scraper_with_mock_cache, mock_firecrawl_response, temp_cache_dir):
        """Test that successful extraction is saved to cache."""
        url = "https://eventstructure.com/test"
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_firecrawl_response
            mock_post.return_value = mock_response
            
            result = scraper_with_mock_cache.extract_work_details(url)
            
            # Verify cache was saved
            loaded = scraper_with_mock_cache._load_cache(url)
            assert loaded is not None
            assert loaded["title"] == result["title"]

    def test_rate_limit_retry_with_backoff(self, scraper_with_mock_cache, mock_firecrawl_response):
        """Test exponential backoff on 429 rate limit."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            # First call: rate limited, second: success
            rate_limit_response = MagicMock()
            rate_limit_response.status_code = 429
            
            success_response = MagicMock()
            success_response.status_code = 200
            success_response.json.return_value = mock_firecrawl_response
            
            mock_post.side_effect = [rate_limit_response, success_response]
            
            start_time = time.time()
            result = scraper_with_mock_cache.extract_work_details(
                "https://eventstructure.com/test"
            )
            elapsed = time.time() - start_time
            
            # Should have succeeded after retry
            assert result is not None
            # Should have waited ~1 second for backoff
            assert elapsed >= 1.0
            assert mock_post.call_count == 2

    def test_max_retries_exceeded(self, scraper_with_mock_cache, caplog):
        """Test that max retries returns None."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            rate_limit_response = MagicMock()
            rate_limit_response.status_code = 429
            mock_post.return_value = rate_limit_response
            
            result = scraper_with_mock_cache.extract_work_details(
                "https://eventstructure.com/test"
            )
            
            assert result is None
            assert "Max retries exceeded" in caplog.text

    def test_api_error_returns_none(self, scraper_with_mock_cache, caplog):
        """Test that API errors return None."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response
            
            result = scraper_with_mock_cache.extract_work_details(
                "https://eventstructure.com/test"
            )
            
            assert result is None
            assert "Firecrawl Error 500" in caplog.text

    def test_network_exception_returns_none(self, scraper_with_mock_cache, caplog):
        """Test that network exceptions are handled."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_post.side_effect = Exception("Network timeout")
            
            result = scraper_with_mock_cache.extract_work_details(
                "https://eventstructure.com/test"
            )
            
            assert result is None
            assert "API request error" in caplog.text


class TestAgentSearch:
    """Test suite for agent_search method."""

    def test_batch_extraction_all_from_cache(self, scraper_with_mock_cache, sample_artwork_data):
        """Test batch extraction when all URLs are cached."""
        urls = [
            "https://eventstructure.com/work/1",
            "https://eventstructure.com/work/2",
        ]
        prompt = "Extract artwork details"
        
        # Pre-populate cache for both URLs
        for url in urls:
            scraper_with_mock_cache._save_extract_cache(url, prompt, sample_artwork_data)
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            result = scraper_with_mock_cache.agent_search(
                prompt=prompt,
                urls=urls,
                extraction_level="quick"
            )
            
            # Should not call API
            mock_post.assert_not_called()
            assert result["from_cache"] is True
            assert result["cached_count"] == 2

    def test_batch_extraction_mixed_cache(self, scraper_with_mock_cache, sample_artwork_data, caplog):
        """Test batch extraction with some URLs cached."""
        urls = [
            "https://eventstructure.com/work/1",
            "https://eventstructure.com/work/2",
        ]
        prompt = "Extract details"
        
        # Cache only first URL
        scraper_with_mock_cache._save_extract_cache(urls[0], prompt, sample_artwork_data)
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post, \
             patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            
            # Mock job submission
            submit_response = MagicMock()
            submit_response.status_code = 200
            submit_response.json.return_value = {"success": True, "id": "job123"}
            
            # Mock job completion
            complete_response = MagicMock()
            complete_response.status_code = 200
            complete_response.json.return_value = {
                "status": "completed",
                "creditsUsed": 20,
                "data": [{"url": urls[1], **sample_artwork_data}]
            }
            
            mock_post.return_value = submit_response
            mock_get.return_value = complete_response
            
            result = scraper_with_mock_cache.agent_search(
                prompt=prompt,
                urls=urls,
                extraction_level="quick"
            )
            
            # Should extract only uncached URL
            assert "1 hits, 1 to extract" in caplog.text
            assert result["cached_count"] == 1
            assert result["new_count"] == 1
            assert len(result["data"]) == 2

    def test_batch_extraction_job_polling(self, scraper_with_mock_cache):
        """Test that batch extraction polls job status."""
        urls = ["https://eventstructure.com/work/1"]
        prompt = "Extract"
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post, \
             patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            
            # Job submission
            submit_response = MagicMock()
            submit_response.status_code = 200
            submit_response.json.return_value = {"success": True, "id": "job123"}
            mock_post.return_value = submit_response
            
            # Job status: processing -> completed
            processing_response = MagicMock()
            processing_response.status_code = 200
            processing_response.json.return_value = {"status": "processing"}
            
            complete_response = MagicMock()
            complete_response.status_code = 200
            complete_response.json.return_value = {
                "status": "completed",
                "creditsUsed": 20,
                "data": [{"url": urls[0], "title": "Test"}]
            }
            
            mock_get.side_effect = [processing_response, complete_response]
            
            result = scraper_with_mock_cache.agent_search(prompt=prompt, urls=urls)
            
            assert result is not None
            assert len(result["data"]) == 1

    def test_agent_mode_open_search(self, scraper_with_mock_cache, caplog):
        """Test agent mode for open-ended search."""
        prompt = "Find all video installations"
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post, \
             patch.object(scraper_with_mock_cache.session, "get") as mock_get:
            
            # Agent job submission
            submit_response = MagicMock()
            submit_response.status_code = 200
            submit_response.json.return_value = {"success": True, "id": "agent123"}
            mock_post.return_value = submit_response
            
            # Agent completion
            complete_response = MagicMock()
            complete_response.status_code = 200
            complete_response.json.return_value = {
                "status": "completed",
                "creditsUsed": 15,
                "data": [{"title": "Video Work 1"}, {"title": "Video Work 2"}]
            }
            mock_get.return_value = complete_response
            
            result = scraper_with_mock_cache.agent_search(prompt=prompt, urls=None)
            
            assert "Starting Smart Agent task" in caplog.text
            assert result is not None
            assert len(result["data"]) == 2

    def test_extraction_level_selects_schema(self, scraper_with_mock_cache, caplog):
        """Test that extraction_level selects correct schema."""
        levels = ["quick", "full", "images_only"]
        expected_logs = ["Quick mode", "Full mode", "Images Only mode"]
        
        for level, expected_log in zip(levels, expected_logs):
            caplog.clear()
            
            with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
                # Mock failure to avoid actual execution
                mock_post.return_value = MagicMock(status_code=400)
                
                scraper_with_mock_cache.agent_search(
                    prompt="test",
                    urls=["https://test.com"],
                    extraction_level=level
                )
                
                assert expected_log in caplog.text


class TestDiscoverUrlsWithScroll:
    """Test suite for discover_urls_with_scroll method."""

    def test_uses_cache_when_valid(self, scraper_with_mock_cache, temp_cache_dir):
        """Test that valid cache is used."""
        url = "https://eventstructure.com"
        scroll_mode = "auto"
        
        # Create valid cache
        cache_path = scraper_with_mock_cache._get_discovery_cache_path(url, scroll_mode)
        cached_urls = ["https://eventstructure.com/work/1", "https://eventstructure.com/work/2"]
        with open(cache_path, "w") as f:
            json.dump(cached_urls, f)
        
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            result = scraper_with_mock_cache.discover_urls_with_scroll(url, scroll_mode)
            
            # Should not call API
            mock_post.assert_not_called()
            assert result == cached_urls

    def test_horizontal_scroll_mode(self, scraper_with_mock_cache):
        """Test horizontal scrolling action sequence."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"extract": {"urls": []}}
            }
            mock_post.return_value = mock_response
            
            scraper_with_mock_cache.discover_urls_with_scroll(
                "https://eventstructure.com",
                scroll_mode="horizontal",
                use_cache=False
            )
            
            # Check that payload includes horizontal scroll actions
            call_args = mock_post.call_args
            payload = call_args[1]["json"]
            assert "actions" in payload
            # Should have 20 horizontal scrolls
            js_actions = [a for a in payload["actions"] if a.get("type") == "executeJavascript"]
            assert len(js_actions) == 20

    def test_saves_discovered_urls_to_cache(self, scraper_with_mock_cache, temp_cache_dir):
        """Test that discovered URLs are saved to cache."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "extract": {
                        "urls": [
                            {"url": "https://eventstructure.com/work/1"},
                            {"url": "https://eventstructure.com/work/2"}
                        ]
                    }
                }
            }
            mock_post.return_value = mock_response
            
            result = scraper_with_mock_cache.discover_urls_with_scroll(
                "https://eventstructure.com"
            )
            
            assert len(result) == 2
            
            # Check cache was created
            cache_path = scraper_with_mock_cache._get_discovery_cache_path(
                "https://eventstructure.com", "auto"
            )
            assert cache_path.exists()

    def test_handles_api_errors_gracefully(self, scraper_with_mock_cache, caplog):
        """Test that API errors return empty list."""
        with patch.object(scraper_with_mock_cache.session, "post") as mock_post:
            mock_post.side_effect = Exception("Timeout")
            
            result = scraper_with_mock_cache.discover_urls_with_scroll(
                "https://eventstructure.com"
            )
            
            assert result == []
            assert "Discovery error" in caplog.text
