"""
Configuration constants for the aaajiao portfolio scraper.

This module contains all configuration constants including:
- JSON schemas for LLM extraction
- Prompt templates for different extraction modes
- URL and network configuration
- Cache and API settings

All constants are immutable and should not be modified at runtime.
"""

from typing import Any, Dict, Final

# ====================
# Extraction Schema Definitions
# ====================

"""JSON schema for quick extraction mode.

Extracts only core fields to minimize API credits consumption (~20 credits per page).
Suitable for batch processing or initial discovery.
"""
QUICK_SCHEMA: Final[Dict[str, Any]] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "The URL of the page being scraped"},
        "title": {"type": "string", "description": "English title of the artwork"},
        "title_cn": {"type": "string", "description": "Chinese title if available"},
        "year": {"type": "string", "description": "Creation year or year range"},
        "category": {"type": "string", "description": "Art category (e.g. Video, Installation)"},
        "has_images": {"type": "boolean", "description": "Whether the page contains images"},
    },
    "required": ["url", "title"],
}

"""JSON schema for full extraction mode.

Extracts complete artwork details including descriptions, images, and metadata.
Higher API cost (~50 credits per page) but provides comprehensive data.
"""
FULL_SCHEMA: Final[Dict[str, Any]] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "The URL of the page being scraped"},
        "title": {"type": "string", "description": "English title"},
        "title_cn": {"type": "string", "description": "Chinese title"},
        "year": {"type": "string", "description": "Creation year"},
        "category": {"type": "string", "description": "Art category"},
        "description_en": {"type": "string", "description": "Full English description"},
        "description_cn": {"type": "string", "description": "Full Chinese description"},
        "high_res_images": {
            "type": "array",
            "items": {"type": "string"},
            "description": "High-res image URLs, prefer 'src_o' attribute",
        },
        "video_link": {"type": "string", "description": "Vimeo/YouTube URL if present"},
        "materials": {"type": "string", "description": "Materials used in the artwork (NOT dimensions or duration)"},
        "size": {"type": "string", "description": "Physical dimensions (e.g. '180 x 180 cm', 'Dimension variable')"},
        "duration": {"type": "string", "description": "Video duration for video works (e.g. '4:30', '2′47′')"},
    },
    "required": ["url", "title"],
}

# ====================
# Prompt Templates
# ====================

"""Pre-configured prompts for different extraction modes.

Keys:
    quick: Basic info extraction (title, year, category)
    full: Complete details with descriptions and images
    images_only: High-resolution image URLs only
    default: General text content extraction
"""
PROMPT_TEMPLATES: Final[Dict[str, str]] = {
    "quick": (
        "Extract basic artwork info including THE URL OF THE PAGE, title (English/Chinese), "
        "year, and category. Return JSON."
    ),
    "full": (
        "Extract complete artwork details including THE URL, title, year, category, "
        "full descriptions, materials, size, duration, and high-res images (src_o). "
        "IMPORTANT: Separate fields correctly - "
        "'materials' = what it's made of (LED, acrylic, wood); "
        "'size' = physical dimensions (180x180cm, variable); "
        "'duration' = video length for video works (4'30'', 10:25). "
        "Return JSON."
    ),
    "images_only": (
        "Extract all high-resolution image URLs from the page. "
        "Prioritize 'src_o' attributes for high-res versions. "
        "Exclude thumbnails and icons. Return as JSON array of URLs."
    ),
    "default": (
        "Extract all text content from the page (title, description, metadata, full text). "
        "Also extract the URL of the first visible image (or main artwork image) "
        "and map it to the field 'image'. IMPORTANT: If the image has a 'src_o' attribute, "
        "extract that URL for high resolution."
    ),
}

# ====================
# General Configuration
# ====================

BASE_URL: Final[str] = "https://eventstructure.com"
"""Base URL for the aaajiao portfolio website."""

SITEMAP_URL: Final[str] = "https://eventstructure.com/sitemap.xml"
"""URL of the XML sitemap for discovering all artwork pages."""

HEADERS: Final[Dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
"""HTTP headers for web requests to avoid bot detection."""

CACHE_DIR: Final[str] = ".cache"
"""Directory path for storing cached extraction results."""

# ====================
# API Configuration
# ====================

MAX_WORKERS: Final[int] = 2
"""Maximum number of concurrent workers for parallel processing."""

TIMEOUT: Final[int] = 15
"""Default HTTP request timeout in seconds."""

FC_TIMEOUT: Final[int] = 30
"""Firecrawl API request timeout in seconds (longer due to LLM processing)."""
