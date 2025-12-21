
import unittest
from unittest.mock import MagicMock, patch
from scraper.firecrawl import FirecrawlMixin
import requests

class TestFirecrawlErrorHandling(unittest.TestCase):
    def setUp(self):
        self.scraper = FirecrawlMixin()
        self.scraper.firecrawl_key = "test_key"
        self.scraper.rate_limiter = MagicMock()
        self.scraper.use_cache = False
        # Mocking methods that might be called
        self.scraper._load_extract_cache = MagicMock(return_value=None)
        self.scraper._save_extract_cache = MagicMock()

    @patch('requests.post')
    def test_agent_search_api_error(self, mock_post):
        # Simulate 401 Unauthorized
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError) as cm:
            self.scraper.agent_search("test prompt", urls=["http://example.com"], extraction_level="quick")
        
        self.assertIn("Extract start failed: 401", str(cm.exception))
        print("✅ Correctly raised RuntimeError on 401")

    @patch('requests.post')
    def test_agent_search_success_false(self, mock_post):
        # Simulate 200 OK but success=False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": False, "error": "Some error"}
        mock_post.return_value = mock_response

        with self.assertRaises(RuntimeError) as cm:
            self.scraper.agent_search("test prompt", urls=["http://example.com"], extraction_level="quick")
        
        self.assertIn("Extract start failed: {'success': False", str(cm.exception))
        print("✅ Correctly raised RuntimeError on success=False")

if __name__ == '__main__':
    unittest.main()
