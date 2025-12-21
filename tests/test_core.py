"""
Tests for core scraper functionality.

Tests CoreScraper and RateLimiter classes:
- API key loading
- Rate limiting behavior
- Session creation with retries
- Basic initialization
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper.core import CoreScraper, RateLimiter


class TestRateLimiter:
    """Test suite for RateLimiter class."""

    def test_initialization(self):
        """Test RateLimiter initializes with correct interval."""
        limiter = RateLimiter(calls_per_minute=10)
        assert limiter.interval == 6.0  # 60/10 = 6 seconds
        assert limiter.last_call == 0

    def test_custom_rate(self):
        """Test RateLimiter with custom rate."""
        limiter = RateLimiter(calls_per_minute=5)
        assert limiter.interval == 12.0  # 60/5 = 12 seconds

    def test_wait_does_not_block_first_call(self):
        """Test that first call doesn't block."""
        limiter = RateLimiter(calls_per_minute=60)
        start = time.time()
        limiter.wait()
        elapsed = time.time() - start
        # First call should be instant (< 0.1s)
        assert elapsed < 0.1

    def test_wait_blocks_rapid_calls(self):
        """Test that rapid calls are rate limited."""
        limiter = RateLimiter(calls_per_minute=60)  # 1 second interval
        
        # First call
        limiter.wait()
        
        # Second call should block
        start = time.time()
        limiter.wait()
        elapsed = time.time() - start
        
        # Should wait approximately 1 second
        assert 0.9 < elapsed < 1.2

    def test_thread_safety(self):
        """Test that RateLimiter uses locks (basic check)."""
        limiter = RateLimiter()
        assert hasattr(limiter, "lock")
        assert limiter.lock is not None


class TestCoreScraper:
    """Test suite for CoreScraper class."""

    def test_initialization_with_cache(self, temp_cache_dir, monkeypatch):
        """Test CoreScraper initializes with cache enabled."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        monkeypatch.setattr("scraper.constants.CACHE_DIR", str(temp_cache_dir))
        
        scraper = CoreScraper(use_cache=True)
        
        assert scraper.use_cache is True
        assert scraper.works == []
        assert scraper.session is not None
        assert scraper.rate_limiter is not None

    def test_initialization_without_cache(self, monkeypatch):
        """Test CoreScraper initializes with cache disabled."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        
        scraper = CoreScraper(use_cache=False)
        
        assert scraper.use_cache is False

    def test_api_key_loading_from_env(self, monkeypatch):
        """Test API key is loaded from environment variable."""
        test_key = "fc-test-key-12345"
        monkeypatch.setenv("FIRECRAWL_API_KEY", test_key)
        
        scraper = CoreScraper()
        
        assert scraper.firecrawl_key == test_key

    def test_api_key_missing_warning(self, monkeypatch, caplog):
        """Test warning is logged when API key is missing."""
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        
        scraper = CoreScraper()
        
        assert scraper.firecrawl_key is None
        assert "FIRECRAWL_API_KEY not found" in caplog.text

    def test_session_has_retry_logic(self, monkeypatch):
        """Test that session is configured with retry adapter."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        
        scraper = CoreScraper()
        
        assert isinstance(scraper.session, requests.Session)
        # Check that adapter is mounted
        assert "http://" in scraper.session.adapters
        assert "https://" in scraper.session.adapters

    def test_session_has_custom_headers(self, monkeypatch):
        """Test that session includes User-Agent header."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        
        scraper = CoreScraper()
        
        assert "User-Agent" in scraper.session.headers
        assert "Mozilla" in scraper.session.headers["User-Agent"]

    def test_cache_directory_created(self, temp_cache_dir, monkeypatch):
        """Test that cache directory is created on initialization."""
        test_cache = temp_cache_dir / "new_cache"
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        monkeypatch.setattr("scraper.constants.CACHE_DIR", str(test_cache))
        
        assert not test_cache.exists()
        
        scraper = CoreScraper()
        
        assert test_cache.exists()

    def test_rate_limiter_configuration(self, monkeypatch):
        """Test that rate limiter is configured correctly."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        
        scraper = CoreScraper()
        
        assert isinstance(scraper.rate_limiter, RateLimiter)
        # Should be 10 calls per minute (6 second interval)
        assert scraper.rate_limiter.interval == 6.0

    def test_create_retry_session_custom_params(self, monkeypatch):
        """Test session creation with custom retry parameters."""
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
        
        scraper = CoreScraper()
        session = scraper._create_retry_session(retries=5, backoff_factor=1.0)
        
        assert isinstance(session, requests.Session)
        # Verify adapters are configured
        for adapter in session.adapters.values():
            if hasattr(adapter, "max_retries"):
                assert adapter.max_retries.total == 5
                assert adapter.max_retries.backoff_factor == 1.0
