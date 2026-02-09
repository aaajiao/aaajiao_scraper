"""
Core scraper components and utilities.

This module provides the foundational classes for the aaajiao scraper:
- RateLimiter: Thread-safe rate limiting for API calls
- CoreScraper: Base scraper with session management and configuration

All scraper mixins inherit from CoreScraper to share common functionality.
"""

import logging
import os
import time
from threading import Lock
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from .constants import CACHE_DIR, HEADERS, MAX_WORKERS, TIMEOUT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe rate limiter for API calls.
    
    Ensures that API calls respect rate limits by enforcing a minimum
    time interval between consecutive calls.
    
    Attributes:
        interval: Minimum time in seconds between calls.
        last_call: Timestamp of the last API call.
        lock: Thread lock for synchronization.
        
    Example:
        >>> limiter = RateLimiter(calls_per_minute=10)
        >>> limiter.wait()  # Blocks if called too soon
        >>> # Make API call here
    """

    def __init__(self, calls_per_minute: int = 5) -> None:
        """Initialize the rate limiter.
        
        Args:
            calls_per_minute: Maximum number of calls allowed per minute.
                Defaults to 5 calls/min (conservative).
        """
        self.interval: float = 60.0 / calls_per_minute
        self.last_call: float = 0
        self.lock: Lock = Lock()

    def wait(self) -> None:
        """Wait until the next call is allowed.
        
        This method blocks execution if insufficient time has passed
        since the last call. Thread-safe for concurrent usage.
        """
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
                logger.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self.last_call = time.time()


class CoreScraper:
    """Base scraper class with session management and configuration.
    
    Provides core functionality shared by all scraper mixins:
    - HTTP session with automatic retries
    - API key management from environment variables
    - Rate limiting for API calls
    - Cache directory initialization
    
    Attributes:
        session: Configured requests.Session with retry logic.
        works: List of scraped artwork data.
        use_cache: Whether to use cache for API responses.
        firecrawl_key: Firecrawl API key from environment.
        rate_limiter: RateLimiter instance for API calls.
        
    Example:
        >>> scraper = CoreScraper(use_cache=True)
        >>> scraper.session.get("https://example.com")
    """

    def __init__(self, use_cache: bool = True) -> None:
        """Initialize the core scraper.
        
        Args:
            use_cache: Enable caching of API responses. Defaults to True.
                Set to False for fresh data without cache lookup.
        """
        self.session: requests.Session = self._create_retry_session()
        self.works: list = []
        self.use_cache: bool = use_cache

        # Load API key from environment
        self.firecrawl_key: Optional[str] = self._load_api_key()

        # Initialize rate limiter (10 calls/min)
        self.rate_limiter: RateLimiter = RateLimiter(calls_per_minute=10)

        # Ensure cache directory exists
        os.makedirs(CACHE_DIR, exist_ok=True)

        logger.info(f"Scraper initialized (cache: {'enabled' if use_cache else 'disabled'})")

    def _load_api_key(self) -> Optional[str]:
        """Load Firecrawl API key from environment variables.
        
        Searches for FIRECRAWL_API_KEY in the following order:
        1. Current environment variables
        2. .env file in project root
        
        Returns:
            API key string if found, None otherwise.
            
        Note:
            Logs a warning if API key is not found. AI features
            will be unavailable without a valid key.
        """
        load_dotenv()
        key = os.getenv("FIRECRAWL_API_KEY")
        
        if not key:
            # Search for .env in parent directory (package compatibility)
            env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            if os.path.exists(env_file):
                load_dotenv(env_file)
                key = os.getenv("FIRECRAWL_API_KEY")

        if not key:
            logger.warning("FIRECRAWL_API_KEY not found, AI features will be unavailable")
        else:
            logger.info(f"API key loaded successfully (length: {len(key)})")
        
        return key

    def _create_retry_session(
        self, retries: int = 3, backoff_factor: float = 0.5
    ) -> requests.Session:
        """Create an HTTP session with automatic retry logic.
        
        Args:
            retries: Maximum number of retry attempts for failed requests.
                Defaults to 3.
            backoff_factor: Multiplier for exponential backoff between retries.
                Defaults to 0.5. Wait time is {backoff factor} * (2 ** retry_count).
        
        Returns:
            Configured requests.Session with retry adapter and default headers.
            
        Note:
            Retries are triggered for network errors and 5xx server errors.
            The session includes a User-Agent header to avoid bot detection.
        """
        session = requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(HEADERS)
        return session


    def get_credit_usage(self) -> Optional[Dict[str, Any]]:
        """Get current Firecrawl API credit usage and remaining balance.

        Calls the Firecrawl /v2/team/credit-usage endpoint to retrieve
        account billing information.

        Returns:
            Dictionary with credit information:
                - remaining_credits: Credits available
                - plan_credits: Total credits in plan
                - billing_period_start: Start of billing cycle (ISO date)
                - billing_period_end: End of billing cycle (ISO date)
            Returns None if API key is missing or request fails.

        Example:
            >>> scraper = AaajiaoScraper()
            >>> usage = scraper.get_credit_usage()
            >>> print(f"Remaining: {usage['remaining_credits']} credits")
        """
        if not self.firecrawl_key:
            logger.warning("No API key, cannot get credit usage")
            return None

        try:
            resp = requests.get(
                "https://api.firecrawl.dev/v1/team/credit-usage",
                headers={
                    "Authorization": f"Bearer {self.firecrawl_key}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    # API returns data in nested 'data' object
                    info = data.get("data", data)
                    result = {
                        "remaining_credits": info.get("remaining_credits", 0),
                        "plan_credits": info.get("plan_credits", 0),
                        "billing_period_start": info.get("billing_period_start", ""),
                        "billing_period_end": info.get("billing_period_end", ""),
                    }
                    logger.info(
                        f"💰 Credits: {result['remaining_credits']:,}/{result['plan_credits']:,} remaining"
                    )
                    return result
                else:
                    logger.warning(f"Credit usage API error: {data}")
            else:
                logger.warning(f"Credit usage request failed: {resp.status_code}")

            return None

        except Exception as e:
            logger.error(f"Failed to get credit usage: {e}")
            return None


def deduplicate_works(works: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate works based on URL.

    Keeps the first occurrence of each URL. This is useful after
    concurrent scraping where duplicates may occur.

    Args:
        works: List of work dictionaries, each containing at least a 'url' key.

    Returns:
        Deduplicated list of works, preserving original order.

    Example:
        >>> works = [{'url': 'a', 'title': '1'}, {'url': 'a', 'title': '2'}]
        >>> deduplicate_works(works)
        [{'url': 'a', 'title': '1'}]
    """
    seen_urls: set = set()
    unique_works: List[Dict[str, Any]] = []

    for work in works:
        url = work.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_works.append(work)

    if len(works) != len(unique_works):
        logger.info(f"Deduplicated: {len(works)} → {len(unique_works)} works")

    return unique_works

