
# 提取 Schema 定义
# ====================

# Quick 模式：仅提取核心字段，节省 credits
QUICK_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "English title of the artwork"},
        "title_cn": {"type": "string", "description": "Chinese title if available"},
        "year": {"type": "string", "description": "Creation year or year range"},
        "category": {"type": "string", "description": "Art category (e.g. Video, Installation)"},
        "has_images": {"type": "boolean", "description": "Whether the page contains images"}
    }
}

# Full 模式：完整字段提取
FULL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "English title"},
        "title_cn": {"type": "string", "description": "Chinese title"},
        "year": {"type": "string", "description": "Creation year"},
        "category": {"type": "string", "description": "Art category"},
        "description_en": {"type": "string", "description": "Full English description"},
        "description_cn": {"type": "string", "description": "Full Chinese description"},
        "high_res_images": {
            "type": "array",
            "items": {"type": "string"},
            "description": "High-res image URLs, prefer 'src_o' attribute"
        },
        "video_link": {"type": "string", "description": "Vimeo/YouTube URL if present"},
        "materials": {"type": "string", "description": "Materials used in the artwork"}
    }
}

# Prompt 模板库
# ====================
PROMPT_TEMPLATES = {
    "quick": "Extract basic artwork info: title (English and Chinese if available), year, and category. Return JSON only, no explanation.",
    "full": "Extract complete artwork details including title, year, category, full descriptions in English and Chinese, materials, and all high-resolution image URLs (use 'src_o' attribute when available). Return JSON only.",
    "images_only": "Extract all high-resolution image URLs from the page. Prioritize 'src_o' attributes for high-res versions. Exclude thumbnails and icons. Return as JSON array of URLs.",
    "default": "Extract all text content from the page (title, description, metadata, full text). Also extract the URL of the first visible image (or main artwork image) and map it to the field 'image'. IMPORTANT: If the image has a 'src_o' attribute, extract that URL for high resolution."
}

# 通用配置
# ====================
BASE_URL = "https://eventstructure.com"
SITEMAP_URL = "https://eventstructure.com/sitemap.xml"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
CACHE_DIR = ".cache"

# API 配置
MAX_WORKERS = 2
TIMEOUT = 15
FC_TIMEOUT = 30
