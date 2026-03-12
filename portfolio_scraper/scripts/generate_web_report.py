
import logging
import sys
from datetime import datetime
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT))

from scraper import AaajiaoScraper
from scraper.paths import REPORTS_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebReport")

def generate_web_image_report():
    """Generates a Markdown report using existing cache but with ONLINE image URLs."""
    scraper = AaajiaoScraper()
    
    # 1. Load all cached works
    logger.info("Loading cache...")
    works = scraper.get_all_cached_works()
    
    if not works:
        logger.warning("No works found in cache!")
        return

    logger.info(f"Found {len(works)} works. Generating report...")

    # Sort by year (descending)
    def get_sort_year(w):
        y = w.get("year", "0000")
        if "-" in y: return y.split("-")[-1]
        return y
        
    works.sort(key=get_sort_year, reverse=True)

    lines = [
        "# aaajiao Portfolio (Web Images)\n",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        "> **Note**: Images are direct links to eventstructure.com\n\n",
        "---\n\n"
    ]

    for i, work in enumerate(works, 1):
        title = work.get("title", "Untitled")
        url = work.get("url", "")
        
        logger.info(f"Processing [{i}/{len(works)}]: {title}")
        
        # Header
        lines.append(f"## {work.get('year', '')} - {title}")
        if work.get('title_cn'):
            lines.append(f" / {work['title_cn']}")
        lines.append("\n\n")
        
        # Metadata
        lines.append(f"**URL**: [{url}]({url})\n\n")
        if work.get("type"): lines.append(f"**Type**: {work['type']}\n\n")
        
        # Descriptions
        if work.get("description_cn"):
            lines.append(f"> {work['description_cn']}\n\n")
        if work.get("description_en"):
            lines.append(f"{work['description_en']}\n\n")

        # --- IMAGES LOGIC ---
        # 1. Check if URLs already exist in cache
        image_urls = work.get("images", [])
        
        # 2. If NOT in cache (legacy data), fetching fresh URLs safely
        # We use scraper.extract_images_from_page() which is non-destructive
        if not image_urls and url:
            try:
                # Only if we really need them. This makes it a bit slower but complete.
                image_urls = scraper.extract_images_from_page(url)
            except Exception as e:
                logger.warning(f"  Failed to fetch images: {e}")

        # 3. Write Image Links
        if image_urls:
            lines.append("### Images\n\n")
            for img in image_urls:
                # Use the raw web URL
                lines.append(f"![]({img})\n\n")
        
        lines.append("---\n")

    # Save
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / "aaajiao_web_images_report.md"
    with report_file.open("w", encoding="utf-8") as f:
        f.write("".join(lines))
        
    logger.info(f"✅ Report generated: {report_file}")

if __name__ == "__main__":
    generate_web_image_report()
