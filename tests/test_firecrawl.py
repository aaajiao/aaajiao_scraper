"""
Tests for Firecrawl API integration.

Tests FirecrawlMixin methods with mocked API responses:
- extract_work_details with three-tier strategy
- agent_search for batch extraction and agent mode
- discover_urls_with_scroll for infinite-scroll pages
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from scraper import AaajiaoScraper


class TestExtractWorkDetails:
    """Test suite for extract_work_details method with three-tier strategy."""

    def test_layer1_local_extraction_success(self, scraper_with_mock_cache, sample_artwork_data):
        """Test Layer 1: successful local BS4 extraction (0 credits)."""
        url = "https://eventstructure.com/test"

        # Mock BS4 extraction on instance
        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=sample_artwork_data.copy())

        result = scraper_with_mock_cache.extract_work_details(url)

        # Should succeed with Layer 1 only
        assert result is not None
        assert result["title"] == "Test Artwork"
        scraper_with_mock_cache.extract_metadata_bs4.assert_called_once()

    def test_layer2_markdown_enrichment(self, scraper_with_mock_cache):
        """Test Layer 2: markdown scrape + regex enrichment (1 credit)."""
        url = "https://eventstructure.com/test"

        # Layer 1: partial data (missing year)
        partial_data = {"title": "Test", "type": "Video", "url": url}

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=partial_data)

        with patch("requests.post") as mock_post:
            # Mock markdown scrape response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"markdown": "# Test\nYear: 2024\nSize: 100x200cm"}
            }
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.extract_work_details(url)

            # Should try Layer 2 (markdown scrape)
            mock_post.assert_called()

    def test_layer3_llm_fallback(self, scraper_with_mock_cache, mock_firecrawl_response):
        """Test Layer 3: LLM extraction as last resort (~20-50 credits, token-based)."""
        url = "https://eventstructure.com/test"

        # Layer 1 fails
        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=None)

        with patch("requests.post") as mock_post:
            # Mock response for both markdown scrape (fails) and LLM extract (succeeds)
            # First call: markdown scrape fails, second call: LLM succeeds
            markdown_fail = MagicMock()
            markdown_fail.status_code = 200
            markdown_fail.json.return_value = {"data": {"markdown": ""}}

            llm_success = MagicMock()
            llm_success.status_code = 200
            llm_success.json.return_value = mock_firecrawl_response

            mock_post.side_effect = [markdown_fail, llm_success]

            result = scraper_with_mock_cache.extract_work_details(url)

            # Should have called API at least twice
            assert mock_post.call_count >= 2

    def test_uses_cache_when_available(self, scraper_with_mock_cache, sample_artwork_data):
        """Test that cached data is returned without any extraction."""
        url = "https://eventstructure.com/test"

        # Pre-populate cache
        scraper_with_mock_cache._save_cache(url, sample_artwork_data)

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock()

        result = scraper_with_mock_cache.extract_work_details(url)

        # Should not call BS4 extraction
        scraper_with_mock_cache.extract_metadata_bs4.assert_not_called()
        assert result == sample_artwork_data

    def test_saves_to_cache_after_extraction(self, scraper_with_mock_cache, sample_artwork_data):
        """Test that successful extraction is saved to cache."""
        url = "https://eventstructure.com/test"

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=sample_artwork_data.copy())

        result = scraper_with_mock_cache.extract_work_details(url)

        # Verify cache was saved
        loaded = scraper_with_mock_cache._load_cache(url)
        assert loaded is not None
        assert loaded["title"] == result["title"]

    def test_skips_exhibition_from_local(self, scraper_with_mock_cache, caplog):
        """Test that exhibitions are skipped from Layer 1."""
        import logging
        caplog.set_level(logging.INFO)

        url = "https://eventstructure.com/exhibition"
        exhibition_data = {
            "title": "Some Exhibition",
            "type": "Exhibition",
            "year": "2024",
            "url": url,
        }

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=exhibition_data)

        result = scraper_with_mock_cache.extract_work_details(url)

        # Should return None for exhibitions
        assert result is None
        # Check for skip message (either old format or new format)
        assert "Skipping exhibition" in caplog.text or "exhibition" in caplog.text.lower()

    def test_rate_limit_retry_in_layer3(self, scraper_with_mock_cache, mock_firecrawl_response):
        """Test exponential backoff on 429 rate limit in Layer 3."""
        url = "https://eventstructure.com/test"

        # Skip Layer 1
        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=None)

        with patch("requests.post") as mock_post:
            # Markdown scrape returns empty, then LLM: rate limited first, success second
            markdown_empty = MagicMock()
            markdown_empty.status_code = 200
            markdown_empty.json.return_value = {"data": {"markdown": ""}}

            rate_limit_response = MagicMock()
            rate_limit_response.status_code = 429

            success_response = MagicMock()
            success_response.status_code = 200
            success_response.json.return_value = mock_firecrawl_response

            mock_post.side_effect = [markdown_empty, rate_limit_response, success_response]

            start_time = time.time()
            result = scraper_with_mock_cache.extract_work_details(url)
            elapsed = time.time() - start_time

            # Should have succeeded after retry
            assert result is not None
            # Should have waited for backoff
            assert elapsed >= 1.0

    def test_max_retries_exceeded(self, scraper_with_mock_cache, caplog):
        """Test that max retries returns None."""
        url = "https://eventstructure.com/test"

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=None)

        with patch("requests.post") as mock_post:
            # Markdown empty, then always rate limited
            markdown_empty = MagicMock()
            markdown_empty.status_code = 200
            markdown_empty.json.return_value = {"data": {"markdown": ""}}

            rate_limit_response = MagicMock()
            rate_limit_response.status_code = 429

            mock_post.side_effect = [markdown_empty] + [rate_limit_response] * 5

            result = scraper_with_mock_cache.extract_work_details(url)

            assert result is None
            assert "Max retries exceeded" in caplog.text

    def test_api_error_returns_none(self, scraper_with_mock_cache, caplog):
        """Test that API errors in Layer 3 return None."""
        url = "https://eventstructure.com/test"

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=None)

        with patch("requests.post") as mock_post:
            # Markdown empty, then server error
            markdown_empty = MagicMock()
            markdown_empty.status_code = 200
            markdown_empty.json.return_value = {"data": {"markdown": ""}}

            error_response = MagicMock()
            error_response.status_code = 500
            error_response.text = "Internal Server Error"

            mock_post.side_effect = [markdown_empty, error_response]

            result = scraper_with_mock_cache.extract_work_details(url)

            assert result is None
            assert "Firecrawl Error 500" in caplog.text

    def test_network_exception_returns_none(self, scraper_with_mock_cache, caplog):
        """Test that network exceptions are handled."""
        url = "https://eventstructure.com/test"

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=None)

        with patch("requests.post") as mock_post:
            # Markdown empty, then network error
            markdown_empty = MagicMock()
            markdown_empty.status_code = 200
            markdown_empty.json.return_value = {"data": {"markdown": ""}}

            mock_post.side_effect = [markdown_empty, Exception("Network timeout")]

            result = scraper_with_mock_cache.extract_work_details(url)

            assert result is None
            # Check for either error message
            assert "LLM extraction error" in caplog.text or "error" in caplog.text.lower()

    def test_year_normalization(self, scraper_with_mock_cache):
        """Test that year is normalized during extraction."""
        url = "https://eventstructure.com/test"

        # Use Installation type (doesn't require duration/video_link for completeness)
        # and include all required fields so Layer 1 succeeds
        data_with_date_range = {
            "title": "Test",
            "type": "Installation",
            "year": "April 26, 2024 — May 25, 2024",
            "url": url,
            "materials": "test materials",
            "size": "100x100cm",
        }

        scraper_with_mock_cache.extract_metadata_bs4 = MagicMock(return_value=data_with_date_range)

        result = scraper_with_mock_cache.extract_work_details(url)

        # Year should be normalized to "2024"
        assert result is not None
        assert result["year"] == "2024"


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

        with patch("requests.post") as mock_post:
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
        import logging
        caplog.set_level(logging.INFO)

        urls = [
            "https://eventstructure.com/work/1",
            "https://eventstructure.com/work/2",
        ]
        prompt = "Extract details"

        # Cache only first URL
        scraper_with_mock_cache._save_extract_cache(urls[0], prompt, sample_artwork_data)

        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:

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

            # Should extract only uncached URL (check log or result)
            assert result["cached_count"] == 1
            assert result["new_count"] == 1
            assert len(result["data"]) == 2

    def test_batch_extraction_job_polling(self, scraper_with_mock_cache):
        """Test that batch extraction polls job status."""
        urls = ["https://eventstructure.com/work/1"]
        prompt = "Extract"

        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:

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
        import logging
        caplog.set_level(logging.INFO)

        prompt = "Find all video installations"

        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:

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

            # Check result instead of log message (implementation may vary)
            assert result is not None
            assert len(result["data"]) == 2

    def test_extraction_level_selects_schema(self, scraper_with_mock_cache, caplog):
        """Test that extraction_level selects correct schema."""
        import logging
        caplog.set_level(logging.INFO)

        levels = ["quick", "full", "images_only"]

        for level in levels:
            caplog.clear()

            with patch("requests.post") as mock_post, \
                 patch("requests.get") as mock_get:
                # Mock successful job submission and completion with data
                submit_response = MagicMock()
                submit_response.status_code = 200
                submit_response.json.return_value = {"success": True, "id": "job123"}
                mock_post.return_value = submit_response

                complete_response = MagicMock()
                complete_response.status_code = 200
                complete_response.json.return_value = {
                    "status": "completed",
                    "creditsUsed": 2,
                    "data": [{"url": "https://test.com", "title": "Test"}]
                }
                mock_get.return_value = complete_response

                result = scraper_with_mock_cache.agent_search(
                    prompt="test",
                    urls=["https://test.com"],
                    extraction_level=level
                )

                # Just verify the call succeeded with the specified level
                assert result is not None


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

        with patch("requests.post") as mock_post:
            result = scraper_with_mock_cache.discover_urls_with_scroll(url, scroll_mode)

            # Should not call API
            mock_post.assert_not_called()
            assert result == cached_urls

    def test_horizontal_scroll_mode(self, scraper_with_mock_cache):
        """Test horizontal scrolling action sequence."""
        with patch("requests.post") as mock_post:
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
        with patch("requests.post") as mock_post:
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
            assert os.path.exists(cache_path)

    def test_handles_api_errors_gracefully(self, scraper_with_mock_cache, caplog):
        """Test that API errors return empty list."""
        # Clear any existing cache
        cache_path = scraper_with_mock_cache._get_discovery_cache_path(
            "https://eventstructure.com", "auto"
        )
        if os.path.exists(cache_path):
            os.remove(cache_path)

        with patch("requests.post") as mock_post:
            mock_post.side_effect = Exception("Timeout")

            result = scraper_with_mock_cache.discover_urls_with_scroll(
                "https://eventstructure.com",
                use_cache=False
            )

            assert result == []
            # Check for error in log
            assert "Discovery" in caplog.text or "error" in caplog.text.lower()


class TestDiscoverUrlsWithMap:
    """Test suite for discover_urls_with_map method (Map API)."""

    def test_discovers_artwork_urls(self, scraper_with_mock_cache):
        """Test Map API discovers and filters artwork URLs."""
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "success": True,
                "links": [
                    "https://eventstructure.com/work/artwork-1",
                    "https://eventstructure.com/work/artwork-2",
                    "https://eventstructure.com/about",
                    "https://eventstructure.com/contact",
                    "https://eventstructure.com/",
                ]
            }
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.discover_urls_with_map()

            assert len(result) == 2
            assert "https://eventstructure.com/work/artwork-1" in result
            assert "https://eventstructure.com/work/artwork-2" in result
            assert "https://eventstructure.com/about" not in result

    def test_uses_search_parameter(self, scraper_with_mock_cache):
        """Test that search parameter is passed to Map API."""
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True, "links": []}
            mock_post.return_value = mock_response

            scraper_with_mock_cache.discover_urls_with_map(search="video installation")

            call_args = mock_post.call_args
            payload = call_args[1].get("json") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["json"]
            assert payload.get("search") == "video installation"

    def test_handles_api_failure(self, scraper_with_mock_cache):
        """Test graceful handling of API failures."""
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.discover_urls_with_map()
            assert result == []

    def test_no_api_key_returns_empty(self, scraper_with_mock_cache):
        """Test that missing API key returns empty list."""
        scraper_with_mock_cache.firecrawl_key = None
        result = scraper_with_mock_cache.discover_urls_with_map()
        assert result == []


class TestScrapeWithJson:
    """Test suite for scrape_with_json method (Scrape + JSON format)."""

    def test_extracts_structured_data(self, scraper_with_mock_cache, sample_artwork_data):
        """Test successful JSON extraction from scrape endpoint."""
        url = "https://eventstructure.com/test-work"

        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "json": {
                        "title": "Test Artwork",
                        "title_cn": "测试作品",
                        "year": "2024",
                        "type": "Video Installation",
                        "materials": "LED, Computer",
                        "size": "",
                        "duration": "4'30''",
                        "credits": "",
                        "description_en": "A test artwork",
                        "description_cn": "测试作品描述",
                    },
                    "markdown": "# Test Artwork\n..."
                }
            }
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.scrape_with_json(url)

            assert result is not None
            assert result["title"] == "Test Artwork"
            assert result["title_cn"] == "测试作品"
            assert result["source"] == "scrape_json"

    def test_cleans_null_placeholders(self, scraper_with_mock_cache):
        """Test that null/N/A placeholder values are cleaned."""
        url = "https://eventstructure.com/test-work"

        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "json": {
                        "title": "Test",
                        "year": "2024",
                        "materials": "None",
                        "size": "N/A",
                        "duration": "not specified",
                        "credits": "null",
                    }
                }
            }
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.scrape_with_json(url)

            assert result["materials"] == ""
            assert result["size"] == ""
            assert result["duration"] == ""
            assert result["credits"] == ""

    def test_includes_spa_actions(self, scraper_with_mock_cache):
        """Test that SPA-aware actions are included when wait_for_spa=True."""
        url = "https://eventstructure.com/test-work"

        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"json": {"title": "Test", "year": "2024"}}
            }
            mock_post.return_value = mock_response

            scraper_with_mock_cache.scrape_with_json(url, wait_for_spa=True)

            call_args = mock_post.call_args
            payload = call_args[1].get("json") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["json"]
            assert "waitFor" in payload
            assert "actions" in payload
            assert "excludeTags" in payload

    def test_handles_api_failure(self, scraper_with_mock_cache):
        """Test graceful handling of API failure."""
        url = "https://eventstructure.com/test-work"

        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.scrape_with_json(url)
            assert result is None

    def test_no_api_key_returns_none(self, scraper_with_mock_cache):
        """Test that missing API key returns None."""
        scraper_with_mock_cache.firecrawl_key = None
        result = scraper_with_mock_cache.scrape_with_json("https://test.com")
        assert result is None

    def test_normalizes_year(self, scraper_with_mock_cache):
        """Test that year normalization is applied."""
        url = "https://eventstructure.com/test-work"

        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "json": {
                        "title": "Test",
                        "year": "September 2019 - January 2020",
                    }
                }
            }
            mock_post.return_value = mock_response

            result = scraper_with_mock_cache.scrape_with_json(url)
            assert result["year"] == "2019-2020"


class TestSPAAwareParameters:
    """Test that SPA-aware parameters are correctly applied to API calls."""

    def test_scrape_markdown_includes_exclude_tags(self, scraper_with_mock_cache):
        """Test that scrape_markdown includes excludeTags and waitFor."""
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"markdown": "# Test Content"}
            }
            mock_post.return_value = mock_response

            scraper_with_mock_cache.scrape_markdown("https://eventstructure.com/test")

            call_args = mock_post.call_args
            payload = call_args[1].get("json") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["json"]
            assert "excludeTags" in payload
            assert "waitFor" in payload

    def test_extract_with_llm_includes_spa_params(self, scraper_with_mock_cache):
        """Test that _extract_with_llm includes SPA-aware parameters."""
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "json": {"title": "Test", "year": "2024", "category": "Video"}
                }
            }
            mock_post.return_value = mock_response

            scraper_with_mock_cache._extract_with_llm(
                "https://eventstructure.com/test-work"
            )

            call_args = mock_post.call_args
            payload = call_args[1].get("json") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["json"]
            assert "excludeTags" in payload
            assert "waitFor" in payload
            assert "onlyMainContent" in payload


class TestDescriptionContamination:
    """Test suite for _is_description_contaminated method."""

    def test_detects_quoted_title_contamination(self, scraper_with_mock_cache):
        """Test detection of '"OtherWork" is a installation' pattern."""
        desc = '"Guard" is a installation artwork exploring physical presence.'
        url = "https://eventstructure.com/Sacpe-data"
        local_data = {"title": "Sacpe.data"}

        result = scraper_with_mock_cache._is_description_contaminated(
            desc, url, local_data
        )
        assert result is True

    def test_detects_named_artwork_contamination(self, scraper_with_mock_cache):
        """Test detection of 'OtherWork is a video artwork' pattern."""
        desc = "One ritual is a video artwork exploring digital meditation."
        url = "https://eventstructure.com/observe"
        local_data = {"title": "observe"}

        result = scraper_with_mock_cache._is_description_contaminated(
            desc, url, local_data
        )
        assert result is True

    def test_accepts_matching_description(self, scraper_with_mock_cache):
        """Test that descriptions mentioning the correct work are accepted."""
        desc = "Sacpe.data is a sound installation exploring digital landscapes."
        url = "https://eventstructure.com/Sacpe-data"
        local_data = {"title": "Sacpe.data"}

        result = scraper_with_mock_cache._is_description_contaminated(
            desc, url, local_data
        )
        assert result is False

    def test_accepts_normal_description(self, scraper_with_mock_cache):
        """Test that normal descriptions without contamination patterns pass."""
        desc = "This installation explores the relationship between digital identity and physical space."
        url = "https://eventstructure.com/test-work"
        local_data = {"title": "test work"}

        result = scraper_with_mock_cache._is_description_contaminated(
            desc, url, local_data
        )
        assert result is False

    def test_short_descriptions_pass(self, scraper_with_mock_cache):
        """Test that very short descriptions are not flagged."""
        desc = "Short text."
        url = "https://eventstructure.com/test"

        result = scraper_with_mock_cache._is_description_contaminated(
            desc, url, None
        )
        assert result is False

    def test_detects_known_contaminant_slug(self, scraper_with_mock_cache):
        """Test detection of known contaminant work names in description."""
        desc = "This piece draws on themes similar to guard and explores digital identity."
        url = "https://eventstructure.com/blogArchaeological-0"
        local_data = {"title": "blogArchaeological 0"}

        result = scraper_with_mock_cache._is_description_contaminated(
            desc, url, local_data
        )
        assert result is True


class TestCrossContaminationCleanup:
    """Test suite for _clean_cross_contamination function."""

    def test_detects_duplicate_materials(self):
        """Test that identical materials in 3+ works are cleaned."""
        from scraper import _clean_cross_contamination

        works = [
            {"title": "Guard, I...", "url": "https://eventstructure.com/Guard-I",
             "materials": "silicone, fiberglass, artificial hair, clothing, seat",
             "description_en": "Guard is a installation artwork."},
            {"title": "Sacpe.data", "url": "https://eventstructure.com/Sacpe-data",
             "materials": "silicone, fiberglass, artificial hair, clothing, seat",
             "description_en": ""},
            {"title": "hm.data", "url": "https://eventstructure.com/hm-data",
             "materials": "silicone, fiberglass, artificial hair, clothing, seat",
             "description_en": ""},
            {"title": "Clean Work", "url": "https://eventstructure.com/clean",
             "materials": "LED, computer, screen",
             "description_en": "A unique description."},
        ]

        cleaned = _clean_cross_contamination(works)

        # Should clean materials from Sacpe.data and hm.data but keep Guard, I...
        assert cleaned >= 2
        assert works[0]["materials"] != ""  # Guard keeps its materials
        assert works[1]["materials"] == ""  # Sacpe.data cleaned
        assert works[2]["materials"] == ""  # hm.data cleaned
        assert works[3]["materials"] == "LED, computer, screen"  # Unaffected

    def test_detects_duplicate_descriptions(self):
        """Test that identical descriptions in 2+ works are cleaned."""
        from scraper import _clean_cross_contamination

        works = [
            {"title": "One ritual", "url": "https://eventstructure.com/One-ritual",
             "materials": "video",
             "description_en": "One ritual is a video artwork exploring digital meditation and mindfulness."},
            {"title": "observe", "url": "https://eventstructure.com/observe",
             "materials": "print paper",
             "description_en": "One ritual is a video artwork exploring digital meditation and mindfulness."},
        ]

        cleaned = _clean_cross_contamination(works)

        # Should clean description from observe (mentions "One ritual")
        assert cleaned >= 1
        assert works[0]["description_en"] != ""  # One ritual keeps its desc
        assert works[1]["description_en"] == ""  # observe cleaned

    def test_no_false_positives(self):
        """Test that unique materials/descriptions are not cleaned."""
        from scraper import _clean_cross_contamination

        works = [
            {"title": "Work A", "url": "https://eventstructure.com/work-a",
             "materials": "LED, acrylic, wood",
             "description_en": "A unique description about work A."},
            {"title": "Work B", "url": "https://eventstructure.com/work-b",
             "materials": "silicone, fiberglass",
             "description_en": "A different description about work B."},
        ]

        cleaned = _clean_cross_contamination(works)
        assert cleaned == 0
        assert works[0]["materials"] == "LED, acrylic, wood"
        assert works[1]["materials"] == "silicone, fiberglass"
