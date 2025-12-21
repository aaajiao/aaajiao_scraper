
from .core import CoreScraper, RateLimiter
from .basic import BasicScraperMixin
from .firecrawl import FirecrawlMixin
from .cache import CacheMixin
from .report import ReportMixin
from .constants import CACHE_DIR, PROMPT_TEMPLATES, QUICK_SCHEMA, FULL_SCHEMA

class AaajiaoScraper(CoreScraper, BasicScraperMixin, FirecrawlMixin, CacheMixin, ReportMixin):
    """
    Facade class combining all scraper functionalities.
    Inherits from:
    - CoreScraper: Session, Config
    - BasicScraperMixin: Sitemap, HTML parsing
    - FirecrawlMixin: extract_work_details, agent_search, discovery
    - CacheMixin: Caching utilities
    - ReportMixin: Markdown/JSON generation
    """
    
    # Re-expose constants for external access if needed (e.g. app.py access to PROMPT_TEMPLATES)
    PROMPT_TEMPLATES = PROMPT_TEMPLATES
    QUICK_SCHEMA = QUICK_SCHEMA
    FULL_SCHEMA = FULL_SCHEMA
    
    def __init__(self, use_cache: bool = True):
        super().__init__(use_cache=use_cache)
