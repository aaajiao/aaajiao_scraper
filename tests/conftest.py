"""
Pytest configuration and shared fixtures.

This module provides common fixtures and configuration for all tests:
- Mock Firecrawl API responses
- Temporary directories for cache testing
- Sample data for testing scrapers
"""

import json
import os
import tempfile
from typing import Dict, Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory for testing.
    
    Args:
        tmp_path: pytest built-in fixture for temporary directory
        
    Returns:
        Path to temporary cache directory
        
    Example:
        >>> def test_cache(temp_cache_dir):
        ...     cache_file = temp_cache_dir / "test.pkl"
        ...     cache_file.write_text("test")
    """
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def mock_firecrawl_key():
    """Provide a mock Firecrawl API key.
    
    Returns:
        Mock API key string for testing
    """
    return "fc-test-key-12345"


@pytest.fixture
def sample_artwork_data() -> Dict[str, Any]:
    """Provide sample artwork data for testing.
    
    Returns:
        Dictionary with sample artwork fields
    """
    return {
        "url": "https://eventstructure.com/test-work",
        "title": "Test Artwork",
        "title_cn": "测试作品",
        "year": "2024",
        "type": "Video Installation",
        "category": "Video Installation",
        "materials": "LED, Computer",
        "description_en": "A test artwork for unit testing",
        "description_cn": "用于单元测试的测试作品",
        "video_link": "https://vimeo.com/123456",
        "size": "",
        "duration": "",
        "tags": [],
    }


@pytest.fixture
def mock_firecrawl_response(sample_artwork_data):
    """Provide a mock successful Firecrawl API response.
    
    Args:
        sample_artwork_data: Sample artwork fixture
        
    Returns:
        Dictionary mimicking Firecrawl V2 API response
    """
    return {
        "success": True,
        "data": {
            "extract": {
                "title": sample_artwork_data["title"],
                "title_cn": sample_artwork_data["title_cn"],
                "year": sample_artwork_data["year"],
                "category": sample_artwork_data["category"],
                "materials": sample_artwork_data["materials"],
                "description_en": sample_artwork_data["description_en"],
                "description_cn": sample_artwork_data["description_cn"],
                "video_link": sample_artwork_data["video_link"],
            }
        },
    }


@pytest.fixture
def mock_sitemap_xml():
    """Provide a mock sitemap XML response.
    
    Returns:
        XML string mimicking a sitemap
    """
    return """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://eventstructure.com/work/test-1</loc>
        <lastmod>2024-01-01</lastmod>
    </url>
    <url>
        <loc>https://eventstructure.com/work/test-2</loc>
        <lastmod>2024-01-02</lastmod>
    </url>
    <url>
        <loc>https://eventstructure.com/about</loc>
        <lastmod>2024-01-01</lastmod>
    </url>
</urlset>"""


@pytest.fixture
def mock_requests():
    """Provide a mock requests module for API testing.
    
    Returns:
        Mock requests module with patched get/post
        
    Example:
        >>> def test_api(mock_requests):
        ...     mock_requests.get.return_value.status_code = 200
    """
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        mock_get.return_value = MagicMock()
        mock_post.return_value = MagicMock()
        yield {"get": mock_get, "post": mock_post}


@pytest.fixture
def scraper_with_mock_cache(temp_cache_dir, mock_firecrawl_key, monkeypatch):
    """Create a scraper instance with mocked cache directory.
    
    Args:
        temp_cache_dir: Temporary cache directory fixture
        mock_firecrawl_key: Mock API key fixture
        monkeypatch: pytest monkeypatch fixture
        
    Returns:
        AaajiaoScraper instance configured for testing
    """
    from scraper import AaajiaoScraper
    
    # Mock environment and cache directory
    monkeypatch.setenv("FIRECRAWL_API_KEY", mock_firecrawl_key)
    monkeypatch.setattr("scraper.constants.CACHE_DIR", str(temp_cache_dir))
    
    return AaajiaoScraper(use_cache=True)

