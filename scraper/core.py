
import os
import time
import logging
from threading import Lock
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import requests
from dotenv import load_dotenv

from .constants import CACHE_DIR, HEADERS, MAX_WORKERS, TIMEOUT

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class RateLimiter:
    """线程安全的速率限制器"""
    def __init__(self, calls_per_minute: int = 5):
        self.interval = 60.0 / calls_per_minute
        self.last_call = 0
        self.lock = Lock()
    
    def wait(self):
        """等待直到允许下一次调用"""
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
                logger.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self.last_call = time.time()

class CoreScraper:
    def __init__(self, use_cache: bool = True):
        self.session = self._create_retry_session()
        self.works = []
        self.use_cache = use_cache
        
        # 加载 API Key
        self.firecrawl_key = self._load_api_key()
        
        # 初始化速率限制器 (10 calls/min) - increased a bit
        self.rate_limiter = RateLimiter(calls_per_minute=10)
        
        # 确保缓存目录存在
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        logger.info(f"Scraper 初始化完成 (缓存: {'开启' if use_cache else '关闭'})")

    def _load_api_key(self) -> str:
        """从环境变量或 .env 文件加载 API Key"""
        load_dotenv()
        key = os.getenv("FIRECRAWL_API_KEY")
        if not key:
            # 向上级目录查找 .env (兼容包结构)
            env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
            if os.path.exists(env_file):
                load_dotenv(env_file)
                key = os.getenv("FIRECRAWL_API_KEY")
        
        if not key:
            logger.warning("未找到 FIRECRAWL_API_KEY，AI 功能将不可用")
        else:
            logger.info(f"API Key 加载成功 (长度: {len(key)})")
        return key

    def _create_retry_session(self, retries: int = 3, backoff_factor: float = 0.5):
        """创建带重试机制的 Session"""
        session = requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update(HEADERS)
        return session
