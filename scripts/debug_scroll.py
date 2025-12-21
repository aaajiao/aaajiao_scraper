import requests
import os
import json
import logging

# Manual .env loading
env_path = "../.env"
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_scroll")

API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
if not API_KEY:
    print("Please set FIRECRAWL_API_KEY env var")
    exit(1)

URL = "https://eventstructure.com"

def test_scroll(mode):
    logger.info(f"Testing Scroll Mode: {mode}")
    
    actions = []
    actions.append({"type": "wait", "milliseconds": 2000})

    if mode == "horizontal":
        # The aggressive JS script from aaajiao_scraper.py
        for i in range(5): # Test with 5 iterations
            actions.append({
                "type": "executeJavascript", 
                "script": """
                    window.scrollTo(document.documentElement.scrollWidth, 0);
                    window.dispatchEvent(new Event('scroll'));
                """
            })
            actions.append({"type": "wait", "milliseconds": 2000})
            
    elif mode == "vertical":
        for _ in range(3):
            actions.append({"type": "scroll", "direction": "down"})
            actions.append({"type": "wait", "milliseconds": 1000})
            
    payload = {
        "url": URL,
        "formats": ["html"],
        "actions": actions,
        "onlyMainContent": False
    }

    endpoint = "https://api.firecrawl.dev/v2/scrape"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=300)
        logger.info(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success'):
                html = data.get('data', {}).get('html', '')
                logger.info(f"HTML Length: {len(html)}")
                
                # Test Selector
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                
                # Check 1: nohover
                nohover = soup.select('a.nohover')
                logger.info(f"Selector 'a.nohover' found: {len(nohover)}")
                if len(nohover) > 0:
                    logger.info(f"First link: {nohover[0]}")
                
                # Check 2: content_container a
                container = soup.select_one('#content_container')
                if container:
                    c_links = container.find_all('a')
                    logger.info(f"Selector '#content_container a' found: {len(c_links)}")
                else:
                    logger.info("'#content_container' NOT found")
                    
            else:
                logger.error(f"API Error: {data}")
        else:
            logger.error(f"HTTP Error: {resp.text}")
            
    except Exception as e:
        logger.error(f"Exception: {e}")

if __name__ == "__main__":
    test_scroll("horizontal")
