
import sys
import os

sys.path.append(os.getcwd())

from scraper.constants import QUICK_SCHEMA, FULL_SCHEMA

def verify():
    print("Verifying Fixes...")
    
    # Check QUICK_SCHEMA
    if "required" in QUICK_SCHEMA and "url" in QUICK_SCHEMA["required"] and "title" in QUICK_SCHEMA["required"]:
        print("✅ QUICK_SCHEMA has required fields ['url', 'title'].")
    else:
        print(f"❌ QUICK_SCHEMA missing required fields! Found: {QUICK_SCHEMA.get('required')}")
        return False

    # Check FULL_SCHEMA
    if "required" in FULL_SCHEMA and "url" in FULL_SCHEMA["required"] and "title" in FULL_SCHEMA["required"]:
        print("✅ FULL_SCHEMA has required fields ['url', 'title'].")
    else:
        print(f"❌ FULL_SCHEMA missing required fields! Found: {FULL_SCHEMA.get('required')}")
        return False

    print("Verification Complete.")
    return True

if __name__ == "__main__":
    if verify():
        sys.exit(0)
    else:
        sys.exit(1)
