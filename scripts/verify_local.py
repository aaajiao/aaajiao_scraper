
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.curdir))

from scraper import AaajiaoScraper

# Configure logging
logging.basicConfig(level=logging.INFO)

def verify_local_extraction():
    url = "https://eventstructure.com/Absurd-Reality-Check"
    
    print(f"Testing local extraction for: {url}")
    print("-" * 50)
    
    scraper = AaajiaoScraper(use_cache=False) # Disable cache to force extraction
    
    # 1. Direct BS4 call
    print("\n[Test 1] Direct BS4 Call:")
    bs4_result = scraper.extract_metadata_bs4(url)
    if bs4_result:
        print("✅ SUCCESS")
        print(f"Title: {bs4_result.get('title')}")
        print(f"Title CN: {bs4_result.get('title_cn')}")
        print(f"Year: {bs4_result.get('year')}")
        print(f"Source: {bs4_result.get('source')}")
        print(f"Images: {len(bs4_result.get('images', []))}")
    else:
        print("❌ FAILED: extract_metadata_bs4 returned None")

    # 2. Integration via extract_work_details
    print("\n[Test 2] Integration via extract_work_details (should be local):")
    # Mocking Firecrawl key to ensure it doesn't actually call API if local works
    # If local fails, this would error out or log error, which proves priority
    result = scraper.extract_work_details(url)
    
    if result and result.get("source") == "local":
        print("✅ SUCCESS: Integrated call used local source")
    elif result:
         print(f"⚠️  Result returned but source is: {result.get('source', 'unknown')}")
    else:
        print("❌ FAILED: Integrated call returned None")

if __name__ == "__main__":
    verify_local_extraction()
