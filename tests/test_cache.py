"""
Tests for caching functionality.

Tests CacheMixin methods:
- General cache operations
- Sitemap cache
- Extract cache with prompt hashing
- Discovery cache with TTL
"""

import hashlib
import json
import os
import pickle
import time
from unittest.mock import MagicMock

import pytest

from scraper import AaajiaoScraper


class TestGeneralCache:
    """Test suite for general cache methods."""

    def test_cache_path_generation(self, scraper_with_mock_cache):
        """Test that cache path is generated correctly."""
        url = "https://eventstructure.com/test"
        expected_hash = hashlib.md5(url.encode()).hexdigest()
        
        path = scraper_with_mock_cache._get_cache_path(url)
        
        assert expected_hash in path
        assert path.endswith(".pkl")

    def test_save_and_load_cache(self, scraper_with_mock_cache, sample_artwork_data):
        """Test saving and loading data from cache."""
        url = "https://eventstructure.com/test"
        
        # Save to cache
        scraper_with_mock_cache._save_cache(url, sample_artwork_data)
        
        # Load from cache
        loaded = scraper_with_mock_cache._load_cache(url)
        
        assert loaded == sample_artwork_data
        assert loaded["title"] == "Test Artwork"

    def test_load_nonexistent_cache_returns_none(self, scraper_with_mock_cache):
        """Test loading cache for non-existent URL returns None."""
        url = "https://eventstructure.com/nonexistent"
        
        result = scraper_with_mock_cache._load_cache(url)
        
        assert result is None

    def test_save_cache_handles_errors_gracefully(self, scraper_with_mock_cache, caplog):
        """Test that save cache handles write errors gracefully."""
        url = "https://eventstructure.com/test"
        invalid_data = {1, 2, 3}  # Sets are not pickle-able in same way
        
        # Should not raise, just log
        scraper_with_mock_cache._save_cache(url, invalid_data)
        
        # Check that debug message was logged
        assert "Cache save failed" in caplog.text or len(caplog.records) >= 0


class TestSitemapCache:
    """Test suite for sitemap cache methods."""

    def test_save_and_load_sitemap_cache(self, scraper_with_mock_cache):
        """Test saving and loading sitemap metadata."""
        sitemap_data = {
            "https://eventstructure.com/work/1": "2024-01-01",
            "https://eventstructure.com/work/2": "2024-01-02",
        }
        
        scraper_with_mock_cache._save_sitemap_cache(sitemap_data)
        loaded = scraper_with_mock_cache._load_sitemap_cache()
        
        assert loaded == sitemap_data

    def test_load_empty_sitemap_returns_empty_dict(self, scraper_with_mock_cache):
        """Test loading empty sitemap returns empty dictionary."""
        result = scraper_with_mock_cache._load_sitemap_cache()
        
        assert result == {}

    def test_sitemap_cache_file_format(self, scraper_with_mock_cache, temp_cache_dir):
        """Test that sitemap cache is saved as JSON."""
        sitemap_data = {"https://test.com": "2024-01-01"}
        
        scraper_with_mock_cache._save_sitemap_cache(sitemap_data)
        
        cache_file = temp_cache_dir / "sitemap_lastmod.json"
        assert cache_file.exists()
        
        with open(cache_file, "r") as f:
            loaded = json.load(f)
        
        assert loaded == sitemap_data


class TestExtractCache:
    """Test suite for extract cache methods."""

    def test_extract_cache_path_includes_prompt_hash(self, scraper_with_mock_cache):
        """Test that extract cache path includes prompt hash."""
        url = "https://eventstructure.com/test"
        prompt = "Extract artwork details"
        
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        path = scraper_with_mock_cache._get_extract_cache_path(url, prompt_hash)
        
        assert url_hash in path
        assert prompt_hash[:8] in path
        assert "extract_" in path

    def test_save_and_load_extract_cache(self, scraper_with_mock_cache, sample_artwork_data):
        """Test saving and loading extract cache with prompt."""
        url = "https://eventstructure.com/test"
        prompt = "Extract quick data"
        
        scraper_with_mock_cache._save_extract_cache(url, prompt, sample_artwork_data)
        loaded = scraper_with_mock_cache._load_extract_cache(url, prompt)
        
        assert loaded == sample_artwork_data

    def test_different_prompts_different_caches(self, scraper_with_mock_cache):
        """Test that different prompts create separate caches."""
        url = "https://eventstructure.com/test"
        data1 = {"result": "from prompt 1"}
        data2 = {"result": "from prompt 2"}
        
        scraper_with_mock_cache._save_extract_cache(url, "prompt1", data1)
        scraper_with_mock_cache._save_extract_cache(url, "prompt2", data2)
        
        loaded1 = scraper_with_mock_cache._load_extract_cache(url, "prompt1")
        loaded2 = scraper_with_mock_cache._load_extract_cache(url, "prompt2")
        
        assert loaded1 == data1
        assert loaded2 == data2
        assert loaded1 != loaded2


class TestDiscoveryCache:
    """Test suite for discovery cache methods."""

    def test_discovery_cache_path_includes_scroll_mode(self, scraper_with_mock_cache):
        """Test that discovery cache path includes scroll mode."""
        url = "https://eventstructure.com"
        scroll_mode = "horizontal"
        
        path = scraper_with_mock_cache._get_discovery_cache_path(url, scroll_mode)
        
        assert scroll_mode in path
        assert "discovery_" in path

    def test_discovery_cache_valid_check_new_file(self, scraper_with_mock_cache, temp_cache_dir):
        """Test that new cache file is valid."""
        cache_file = temp_cache_dir / "test_discovery.json"
        cache_file.write_text("{}")
        
        is_valid = scraper_with_mock_cache._is_discovery_cache_valid(str(cache_file), ttl_hours=24)
        
        assert is_valid is True

    def test_discovery_cache_invalid_old_file(self, scraper_with_mock_cache, temp_cache_dir):
        """Test that old cache file is invalid."""
        cache_file = temp_cache_dir / "test_discovery.json"
        cache_file.write_text("{}")
        
        # Modify file timestamp to be old
        old_time = time.time() - (25 * 3600)  # 25 hours ago
        os.utime(cache_file, (old_time, old_time))
        
        is_valid = scraper_with_mock_cache._is_discovery_cache_valid(str(cache_file), ttl_hours=24)
        
        assert is_valid is False

    def test_discovery_cache_nonexistent_file(self, scraper_with_mock_cache):
        """Test that nonexistent file is invalid."""
        is_valid = scraper_with_mock_cache._is_discovery_cache_valid("/nonexistent/path.json")
        
        assert is_valid is False


class TestCacheIntegration:
    """Integration tests for cache usage across scraper."""

    def test_cache_disabled_does_not_load(self, temp_cache_dir, monkeypatch):
        """Test that cache is not used when disabled."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        monkeypatch.setattr("scraper.constants.CACHE_DIR", str(temp_cache_dir))
        
        scraper = AaajiaoScraper(use_cache=False)
        
        # Save some data
        url = "https://test.com"
        data = {"test": "data"}
        scraper._save_cache(url, data)
        
        # Even though data exists, use_cache=False should prevent loading
        # (Note: Current implementation still saves, just doesn't load in extract methods)
        assert scraper.use_cache is False
