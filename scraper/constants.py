"""
Configuration constants for the aaajiao portfolio scraper.

This module contains all configuration constants including:
- JSON schemas for LLM extraction
- Prompt templates for different extraction modes
- URL and network configuration
- Cache and API settings

All constants are immutable and should not be modified at runtime.
"""

from typing import Any, Dict, Final, List, Optional

from pydantic import BaseModel, Field

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
        "type": {"type": "string", "description": "Art type/category (e.g. Video, Installation)"},
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
        "type": {"type": "string", "description": "Art type/category"},
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
        "credits": {
            "type": "string",
            "description": "Credits and collaborators (e.g., 'Photo: John', 'concept: aaajiao; sound: yang2')"
        },
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
        "full descriptions, materials, size, duration, credits, and high-res images (src_o). "
        "IMPORTANT: Separate fields correctly - "
        "'materials' = physical materials (LED, acrylic, wood, silicone, screen printing); "
        "'size' = physical dimensions (180x180cm, variable); "
        "'duration' = video length for video works (4'30'', 10:25); "
        "'credits' = collaborators and credits (Photo: xxx, concept: aaajiao; sound: yang2). "
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

# API Cost Estimates (for documentation and planning)
SCRAPE_CREDITS_PER_PAGE: Final[int] = 1
"""Firecrawl Scrape API cost: 1 credit per page (markdown only)."""

EXTRACT_CREDITS_PER_PAGE: Final[int] = 30
"""Firecrawl Extract API average cost: ~30 credits per page (token-based, actual 20-50)."""

# ====================
# Extraction Pattern Constants
# ====================

MATERIAL_KEYWORDS: Final[List[str]] = [
    # Physical materials (English)
    "LED", "acrylic", "wood", "bamboo", "cotton", "foam", "PVC",
    "silicone", "fabric", "metal", "glass", "plastic", "paper",
    "screen printing", "silk", "polyurethane", "TPU", "ink",
    "fiberglass", "resin", "steel", "aluminum", "ceramic",
    "neon", "rubber", "vinyl", "linen", "canvas", "concrete",
    "sponge", "roller", "hair", "clothing", "seat", "monitor",
    "computer", "projector", "speaker", "cable", "wire", "light",
    "mirror", "stone", "marble", "granite", "copper", "bronze",
    "iron", "chrome", "titanium", "carbon", "fiber",
    "epoxy", "lacquer", "paint", "pigment", "dye", "thread",
    "rope", "string", "chain", "mesh", "net", "film", "tape",
    "printing", "print", "spray", "laser", "CNC", "3D",
    # Chinese materials
    "丝网印刷", "亚克力", "硅胶", "竹", "棉", "泡沫", "金属",
    "玻璃", "塑料", "纸", "油墨", "树脂", "钢", "铝", "陶瓷",
    "霓虹", "橡胶", "帆布", "混凝土", "聚氨酯", "海绵", "滚轮",
    "显示器", "投影", "音箱", "电缆", "线", "灯", "镜", "石",
    "大理石", "花岗岩", "铜", "青铜", "铁", "铬", "钛", "碳纤维",
    "环氧", "漆", "颜料", "染料", "绳", "链", "网", "膜",
]
"""Material keywords for identifying physical materials in artwork descriptions.

Used by both BasicScraperMixin (Layer 1) and FirecrawlMixin (Layer 2).
Comprehensive list including English and Chinese terms.
"""

CREDITS_PATTERNS: Final[List[str]] = [
    r'^Photo(?:\s+by)?\s*:\s*.+',
    r'^concept\s*:\s*.+',
    r'^sound\s*:\s*.+',
    r'^software\s*:\s*.+',
    r'^hardware\s*:\s*.+',
    r'^computer graphics\s*:\s*.+',
    r'^video editing\s*:\s*.+',
    r'^technical support\s*:\s*.+',
    r'^architecture\s*:\s*.+',
    r'^interactive\s*:\s*.+',
    r'^dancer\s*:\s*.+',
    r'^actress\s*:\s*.+',
    r'^curated by\s+.+',
    r'^team\s*:\s*.+',
    r'^director\s*:\s*.+',
    r'^producer\s*:\s*.+',
    r'^editor\s*:\s*.+',
    r'^music\s*:\s*.+',
    r'^animation\s*:\s*.+',
    r'^design\s*:\s*.+',
    r'^programming\s*:\s*.+',
    r'^code\s*:\s*.+',
    r'^venue\s*:\s*.+',
    r'^location\s*:\s*.+',
    r'.+:\s*[a-zA-Z]+(?:,\s*[a-zA-Z]+)*(?:;\s*[a-zA-Z\s]+:\s*[a-zA-Z]+(?:,\s*[a-zA-Z]+)*)+',
    r'made possible (?:with|by)\s+.+',
    r'collaboration (?:of|with)\s+.+',
    r'Copyright\s+(?:of|by)\s+.+',
]
"""Credits patterns for identifying collaborator/credit lines.

Patterns use \\s* after role names to handle variable spacing (e.g., "sound : name").
Used for both extraction and validation in Layer 1 and Layer 2.
"""

TYPE_KEYWORDS: Final[List[str]] = [
    "Video", "Installation", "Website", "Software", "Print",
    "Data", "Performance", "Sculpture", "Media", "Photography",
    "Painting", "Drawing", "Animation", "Game", "Application",
    "Sound", "Interactive", "Single channel", "Multi-channel",
    "装置", "录像", "雕塑", "摄影", "绘画", "动画", "游戏",
    "声音", "互动", "单频", "多频",
]
"""Type keywords for identifying artwork categories.

Used to detect type lines in content parsing. Includes both English and Chinese terms.
"""

# ====================
# Canonical Art Types (for normalization)
# ====================

CANONICAL_TYPES: Final[Dict[str, str]] = {
    # Installation variants -> Installation
    "installation": "Installation",
    "装置": "Installation",
    "video installation": "Video Installation",
    "视频装置": "Video Installation",
    "media installation": "Media Installation",
    "sound installation": "Sound Installation",
    "mixed media installation": "Mixed Media Installation",

    # Video variants -> Video
    "video": "Video",
    "录像": "Video",
    "single channel video": "Single Channel Video",
    "单频录像": "Single Channel Video",
    "单频彩色录像": "Single Channel Video",
    "multi-channel video": "Multi-Channel Video",
    "多频录像": "Multi-Channel Video",
    "film": "Film",
    "document video": "Documentary Video",

    # Digital/Web variants
    "website": "Website",
    "网站": "Website",
    "software": "Software",
    "application": "Application",
    "app": "Application",
    "game": "Game",
    "游戏": "Game",
    "nft": "NFT",
    "crypto": "Crypto Art",

    # Print/2D variants
    "print": "Print",
    "版画": "Print",
    "digital printing": "Digital Print",
    "数码打印": "Digital Print",
    "screen printing": "Screen Print",
    "丝网印刷": "Screen Print",
    "photography": "Photography",
    "摄影": "Photography",
    "painting": "Painting",
    "绘画": "Painting",
    "drawing": "Drawing",

    # Sculpture variants
    "sculpture": "Sculpture",
    "雕塑": "Sculpture",
    "media sculpture": "Media Sculpture",

    # Performance variants
    "performance": "Performance",
    "live performance": "Live Performance",
    "video or live performance": "Video/Performance",

    # Other
    "data": "Data Art",
    "sound": "Sound Art",
    "声音": "Sound Art",
    "interactive": "Interactive",
    "互动": "Interactive",
    "animation": "Animation",
    "动画": "Animation",
    "projection mapping": "Projection Mapping",
    "projection-mapping": "Projection Mapping",
    "投影映射": "Projection Mapping",
    "media art": "Media Art",
    "new media": "New Media Art",
    "新媒体": "New Media Art",
    "object": "Object",
    "物件": "Object",
}
"""Canonical art type mappings for normalization.

Maps various type strings (including Chinese) to standardized English type names.
Used to clean and normalize the 'type' field.
"""

# ====================
# Excluded Tags (for filtering non-artwork pages)
# ====================

EXCLUDED_TAGS: Final[List[str]] = [
    # Exhibition types
    "exhibition", "solo exhibition", "group exhibition",
    "展览", "个展", "群展",
    # Publications
    "catalog", "catalogue", "book", "publication",
    "图录", "书籍", "出版物",
    # Other non-artwork
    "event", "talk", "lecture", "workshop",
    "活动", "讲座", "工作坊",
]
"""Tags that indicate non-artwork pages (exhibitions, publications, events).

Used in extract_metadata_bs4() to early-detect and mark pages for filtering.
These pages will be skipped by is_artwork() check.
"""

# Equipment/material keywords that should NOT be in type field
TYPE_POLLUTANTS: Final[List[str]] = [
    # Equipment (should be in materials)
    "projector", "player", "screen", "monitor", "computer", "cable",
    "speaker", "microphone", "sensor", "raspberry", "arduino",
    "投影", "播放器", "显示器", "电脑", "音箱", "麦克风",
    # Materials (should be in materials)
    "acrylic", "wood", "metal", "glass", "led", "pvc", "silicone",
    "亚克力", "金属", "玻璃",
    # Techniques (should be separate or in materials)
    "chevron board", "metal frame", "linen", "canvas",
    # Format descriptors (can be part of type but not standalone)
    "color", "彩色", "sound", "有声",
]
"""Keywords that indicate pollution in type field.

If type field contains these AND is longer than expected,
the extra content should be moved to materials.
"""

# ====================
# Pydantic Schema for Firecrawl Extract
# ====================


class ArtworkSchema(BaseModel):
    """Pydantic schema for structured artwork metadata extraction.

    Used with Firecrawl Extract API to ensure consistent, typed output.
    Field descriptions guide the LLM on what to extract and expected formats.
    """

    title: str = Field(description="Artwork title in English")
    title_cn: Optional[str] = Field(
        default=None,
        description="Chinese title, usually after '/' in bilingual format like 'Title / 标题'",
    )
    year: str = Field(
        description="Creation year, format: YYYY or YYYY-YYYY for ranges"
    )
    type: Optional[str] = Field(
        default=None,
        description="Artwork type: Installation, Video, Performance, Sculpture, etc.",
    )

    # Physical properties
    size: Optional[str] = Field(
        default=None,
        description=(
            "Physical dimensions. Accept formats: 180 x 180 cm, 180×180×50cm, "
            "180*180, Dimension variable, 尺寸可变"
        ),
    )
    duration: Optional[str] = Field(
        default=None,
        description=(
            "Video/sound duration. Accept formats: 6'30\", 4 minutes, 10 min, "
            "4分30秒, 00:04:30"
        ),
    )
    materials: Optional[str] = Field(
        default=None,
        description=(
            "Materials and medium used, comma-separated. "
            "Example: 'LED screen, acrylic, wood / LED屏幕, 亚克力, 木'"
        ),
    )

    # Descriptions
    description_en: Optional[str] = Field(
        default=None, description="English description paragraph(s)"
    )
    description_cn: Optional[str] = Field(
        default=None, description="Chinese description paragraph(s) (中文描述)"
    )

    # Credits
    credits: Optional[str] = Field(
        default=None,
        description=(
            "Credits and acknowledgments: photo by, technical support, "
            "collaboration, made possible with, etc."
        ),
    )


ARTWORK_EXTRACT_PROMPT: Final[str] = """
Extract artwork metadata from this artist portfolio page.

⚠️ CRITICAL - THIS IS A SINGLE PAGE APPLICATION (SPA):
- The page contains a SIDEBAR with links to OTHER artworks - IGNORE THESE!
- Only extract from the MAIN CONTENT AREA (center/right of page)
- The sidebar may list: "One ritual", "Two rituals", "Guard, I...", etc. - DO NOT extract these!
- If you see multiple titles, the MAIN artwork title is the one with full description below it

HOW TO IDENTIFY THE CORRECT ARTWORK:
1. Look for the largest/most prominent title in the main content area
2. The correct title has detailed information below it (year, type, materials, description)
3. Sidebar items only have title + small thumbnail - skip these

EXTRACTION RULES:
1. Title format: Usually "English Title / 中文标题" - split into title and title_cn
2. Size: 180 x 180 cm, 180×180×50cm, Dimension variable, 尺寸可变
3. Duration: 6'30", 4 minutes, 4分30秒, 00:04:30 (for video/sound works)
4. Materials: Physical materials only (LED, acrylic, wood, silicone, etc.)
5. Credits: Photo credits, collaborators, technical support
6. Descriptions: Separate English and Chinese paragraphs

VERIFICATION: Your extracted title should relate to the URL slug of the page.
"""
"""Optimized prompt for Firecrawl Extract API.

Emphasizes ignoring sidebar content and handling various data formats.
"""
