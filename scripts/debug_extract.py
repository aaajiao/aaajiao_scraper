
import requests
import time
import os

# Manual env loading
try:
    with open("../.env", "r") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                if key == "FIRECRAWL_API_KEY":
                    API_KEY = val.strip()
                    break
except Exception as e:
    API_KEY = ""

def check_status(job_id):
    print(f"Checking status for job: {job_id}")
    url = f"https://api.firecrawl.dev/v2/extract/{job_id}"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
    }
    
    resp = requests.get(url, headers=headers)
    print(f"Status Code: {resp.status_code}")
    print(f"Response: {resp.text}")

if __name__ == "__main__":
    # Use the ID from the previous successful run output
    job_id = "019b40b5-cbb1-7288-9762-061c71341926" 
    check_status(job_id)
