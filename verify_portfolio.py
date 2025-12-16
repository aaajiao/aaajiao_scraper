import csv
import re

def parse_markdown(md_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    entries = {}
    current_year = None
    
    # Regex for headers like "## 2025" or "## 2025-2024" etc.
    year_re = re.compile(r'^##\s+(\d{4})')
    # Regex for entry headers: "### [Title](URL)" or "### [Title](URL) / Chinese"
    # capturing title, url, and optional chinese title part
    entry_re = re.compile(r'^###\s+\[(.*?)\]\((.*?)\)(?:\s*/\s*(.*))?')

    for line in lines:
        line = line.strip()
        year_match = year_re.match(line)
        if year_match:
            current_year = year_match.group(1)
            continue

        entry_match = entry_re.match(line)
        if entry_match:
            title = entry_match.group(1)
            url = entry_match.group(2)
            cn_title_suffix = entry_match.group(3)
            
            # Normalize URL (remove trailing slash, etc if needed)
            url = url.strip()
            
            entries[url] = {
                'year_section': current_year,
                'title_md': title,
                'cn_title_md': cn_title_suffix,
                'full_header': line
            }
            
    return entries

def parse_csv(csv_path):
    data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data

def verify(md_path, csv_path):
    md_entries = parse_markdown(md_path)
    csv_data = parse_csv(csv_path)

    missing_in_md = []
    year_mismatches = []
    title_mismatches = []
    
    print(f"Total CSV entries: {len(csv_data)}")
    print(f"Total MD entries: {len(md_entries)}")
    
    for row in csv_data:
        url = row['url'].strip()
        if not url:
            continue
            
        csv_title = row['title']
        csv_title_cn = row['title_cn']
        csv_year = row['year'] # This might be a range or list
        
        if url not in md_entries:
            # Try fuzzy match or check if URL might be different?
            # For now strict match
            missing_in_md.append(url)
            continue
            
        md_entry = md_entries[url]
        
        # Check Year consistency (approximate)
        # MD structure is strictly by year sections (e.g. ## 2025). 
        # CSV year might be "2018-2021" or "2025".
        # If CSV has a range, MD usually places it under the *start* or *end* year or *most recent*?
        # Let's check if the MD section year appears in the CSV Year string.
        md_year = md_entry['year_section']
        # Relaxed check: is the section year present in the CSV year string?
        # e.g. CSV "2018-2021", MD section "2021" -> OK
        # But wait, commonly portfolios are ordered by start or end date.
        
        if md_year and md_year not in str(csv_year):
             year_mismatches.append(f"URL: {url} | CSV Year: {csv_year} | MD Section: {md_year}")

        # Check Title consistency
        # MD might have "Title / CN" or just "Title"
        md_title_full = md_entry['title_md']
        if md_entry['cn_title_md']:
             # normalized check?
             pass
        
        # Just simple check: is the main title in MD similar to CSV title?
        if csv_title.strip() != md_entry['title_md'].strip():
            # Sometimes punctuation or spacing differs
             title_mismatches.append(f"URL: {url} | CSV: {csv_title} | MD: {md_entry['title_md']}")

        # Check for missing Chinese title in MD
        if csv_title_cn and csv_title_cn != csv_title: # Avoid verifying if title_cn is same as title (sometimes happens)
             # We check if csv_title_cn is in the full_header or cn_title_md
             # md_entry['cn_title_md'] capture might be None if no "/"
             
             md_cn = md_entry['cn_title_md'] or ""
             if csv_title_cn.strip() not in md_cn and csv_title_cn.strip() not in md_entry['full_header']:
                 # relaxed check: maybe it's partially there or format differs?
                 missing_in_md.append(f"CN Title Missing/Mismatch: URL: {url} | CSV CN: {csv_title_cn} | MD Line: {md_entry['full_header']}")

    print("\n--- Summary of Verification ---")
    
    if len(missing_in_md) > 0:
        # We reused the list, filtering for 'CN Title' strings to separate
        true_missing = [x for x in missing_in_md if "CN Title" not in x and "URL:" not in x] # sloppy reuse fix
        cn_missing = [x for x in missing_in_md if "CN Title" in x]
        
        if true_missing:
             print(f"\n[MISSING] {len(true_missing)} entries from CSV are missing in MD:")
             for u in true_missing:
                 print(f"  - {u}")
        
        if cn_missing:
             print(f"\n[CN TITLE ISSUE] {len(cn_missing)} entries might be missing Chinese title in MD:")
             for m in cn_missing:
                 print(f"  - {m}")
    else:
        print("\n[OK] All CSV entries found in MD.")

    if year_mismatches:
        print(f"\n[YEAR WARN] {len(year_mismatches)} entries might be in wrong year section (Subjective):")
        for m in year_mismatches[:10]: # Validating first 10
            print(f"  - {m}")
        if len(year_mismatches) > 10: print("  ... and more")
            
    if title_mismatches:
        print(f"\n[TITLE MISMATCH] {len(title_mismatches)} entries have different titles:")
        for m in title_mismatches:
            print(f"  - {m}")

if __name__ == "__main__":
    verify("aaajiao_portfolio.md", "xxx/2025-12-16T18-17_export.csv")
