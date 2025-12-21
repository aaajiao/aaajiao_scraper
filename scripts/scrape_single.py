
from scraper import AaajiaoScraper
import json
import os

def scrape_single_page():
    url = "https://eventstructure.com/Absurd-Reality-Check"
    print(f"Scraping: {url}")
    
    scraper = AaajiaoScraper(use_cache=False)
    
    # 1. Extract Details
    work_data = scraper.extract_work_details(url)
    
    if not work_data:
        print("❌ Extraction failed")
        return

    print(f"✅ Extracted: {work_data.get('title')} ({work_data.get('year')})")
    print(f"Source: {work_data.get('source')}")
    
    # 2. Generate Markdown
    filename = "Absurd-Reality-Check.md"
    
    with open(filename, "w", encoding="utf-8") as f:
        # Title
        f.write(f"# {work_data.get('title')}\n")
        if work_data.get('title_cn'):
            f.write(f"## {work_data.get('title_cn')}\n")
        f.write("\n")
        
        # Metadata
        f.write(f"- **Year**: {work_data.get('year')}\n")
        f.write(f"- **Category**: {work_data.get('category') or work_data.get('type')}\n")
        f.write(f"- **URL**: [{url}]({url})\n")
        f.write(f"- **Source**: {work_data.get('source')}\n")
        f.write("\n---\n\n")
        
        # English Description
        if work_data.get('description_en'):
            f.write("### English Description\n")
            f.write(f"{work_data.get('description_en')}\n\n")
            
        # Chinese Description
        if work_data.get('description_cn'):
            f.write("### Chinese Description\n")
            f.write(f"{work_data.get('description_cn')}\n\n")
            
        # Images
        images = work_data.get('high_res_images') or work_data.get('images') or []
        if images:
            f.write("### Images\n\n")
            for i, img in enumerate(images):
                f.write(f"![Image {i+1}]({img})\n\n")
                
    print(f"✅ Saved to: {os.path.abspath(filename)}")

if __name__ == "__main__":
    scrape_single_page()
