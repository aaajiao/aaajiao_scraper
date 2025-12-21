
import sys
import os

sys.path.append(os.getcwd())

from scraper.constants import QUICK_SCHEMA, FULL_SCHEMA, PROMPT_TEMPLATES

def verify():
    print("Verifying Fixes...")
    
    # Check QUICK_SCHEMA
    if "url" in QUICK_SCHEMA["properties"]:
        print("✅ QUICK_SCHEMA has 'url' field.")
    else:
        print("❌ QUICK_SCHEMA missing 'url'!")
        return False

    # Check FULL_SCHEMA
    if "url" in FULL_SCHEMA["properties"]:
        print("✅ FULL_SCHEMA has 'url' field.")
    else:
        print("❌ FULL_SCHEMA missing 'url'!")
        return False
        
    # Check Prompts
    if "THE URL" in PROMPT_TEMPLATES["full"]:
        print("✅ PROMPT_TEMPLATES['full'] asks for URL.")
    else:
        print("❌ PROMPT_TEMPLATES['full'] does not explicitly ask for URL.")
        
    print("Verification Complete.")
    return True

if __name__ == "__main__":
    if verify():
        sys.exit(0)
    else:
        sys.exit(1)
