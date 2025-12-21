import os
import requests
import json
import time
from dotenv import load_dotenv

# Load env variables
load_dotenv()

API_KEY = os.getenv("FIRECRAWL_API_KEY")
if not API_KEY:
    print("Error: FIRECRAWL_API_KEY not found in environment variables.")
    # Fallback for testing if env not set, but better to enforce env
    # API_KEY = "..." 
    pass

URL = "https://eventstructure.com/Absurd-Reality-Check"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 定义提取结构
schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The English title of the work"},
        "title_cn": {"type": "string", "description": "The Chinese title of the work"},
        "year": {"type": "string", "description": "Creation year or range"},
        "category": {"type": "string", "description": "The type/category of the work (e.g. Video, Installation)"},
        "materials": {"type": "string", "description": "Materials or technical specifications (e.g. LED screen, 3D printing)"},
        "description_en": {"type": "string", "description": "Description in English, excluding metadata"},
        "description_cn": {"type": "string", "description": "Description in Chinese, excluding metadata"},
        "video_url": {"type": "string", "description": "Any Vimeo or video link found"}
    },
    "required": ["title", "year"]
}

payload = {
    "url": URL,
    "formats": ["extract"],
    "extract": {
        "schema": schema
    }
}

print(f"Testing Firecrawl on {URL}...")
start = time.time()
try:
    if not API_KEY:
         print("Skipping request due to missing API Key")
    else:
        response = requests.post("https://api.firecrawl.dev/v2/scrape", headers=headers, json=payload)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("Error:", response.text)

except Exception as e:
    print(f"Exception: {e}")

print(f"Time taken: {time.time() - start:.2f}s")
