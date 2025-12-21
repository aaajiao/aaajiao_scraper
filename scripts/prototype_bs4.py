
from bs4 import BeautifulSoup
import re

with open("sample_work.html", "r") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

# 1. Title
title_div = soup.find("div", class_="project_title")
title = clean_text(title_div.get_text()) if title_div else "N/A"
print(f"Title: {title}")

# 2. Content (Description + Year maybe?)
content_div = soup.find("div", class_="project_content")
if content_div:
    # Remove scripts and styles
    for s in content_div(["script", "style"]):
        s.decompose()
        
    text = content_div.get_text(separator="\n")
    lines = [clean_text(line) for line in text.split("\n") if clean_text(line)]
    print("\n--- Content Lines ---")
    for line in lines:
        print(line)
        
    # Attempt to find Year (4 digits)
    year = "N/A"
    for line in lines:
        # Match standalone year or year range: 2023 or 2018-2022
        match = re.search(r'\b(20\d{2}(?:[-–]20\d{2})?)\b', line)
        if match:
            year = match.group(1)
            break
    print(f"\nExtracted Year: {year}")

