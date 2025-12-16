import requests
from bs4 import BeautifulSoup

def debug():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    base_url = "https://eventstructure.com"
    
    print(f"Fetching {base_url}...")
    try:
        r = requests.get(base_url, headers=headers, timeout=10)
        print(f"Status: {r.status_code}")
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Check for project links
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/') and len(href) > 2 and 'filter' not in href and 'aaajiao' not in href:
                links.append(href)
        
        print(f"Found {len(links)} potential project links.")
        print(f"First 5 links: {links[:5]}")
        
        if links:
            target_link = links[0]
            if not target_link.startswith('http'):
                target_link = base_url + target_link
            
            print(f"\nFetching detail page: {target_link}")
            r2 = requests.get(target_link, headers=headers, timeout=10)
            soup2 = BeautifulSoup(r2.text, 'html.parser')
            
            # Print title
            print("\n--- Title extraction attempt ---")
            print(f"Page Title Tag: {soup2.title.string if soup2.title else 'No Title'}")
            
            # Cargo sites often use .project_content or .entry
            print("\n--- Content container check ---")
            project_content = soup2.find(class_='project_content')
            entry = soup2.find(class_='entry')
            container = soup2.find(id='project_content')
            
            if project_content: print("Found class 'project_content'")
            if entry: print("Found class 'entry'")
            if container: print("Found id 'project_content'")
            
            # Dump some text
            text = soup2.get_text()[:500]
            print(f"\n--- First 500 chars of text ---\n{text}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug()
