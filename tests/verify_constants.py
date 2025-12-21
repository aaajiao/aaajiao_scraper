
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from scraper.constants import QUICK_SCHEMA, FULL_SCHEMA

def verify_schema(name, schema):
    print(f"Verifying {name}...")
    keys = list(schema.keys())
    print(f"Keys: {keys}")
    
    if "type" not in keys:
        print(f"❌ '{name}' missing 'type' key! First key is: '{keys[0] if keys else 'EMPTY'}'")
        return False
    
    if schema["type"] != "object":
        print(f"❌ '{name}' type is not object!")
        return False
        
    print(f"✅ {name} looks valid.")
    return True

if __name__ == "__main__":
    valid_quick = verify_schema("QUICK_SCHEMA", QUICK_SCHEMA)
    valid_full = verify_schema("FULL_SCHEMA", FULL_SCHEMA)
    
    if valid_quick and valid_full:
        print("All schemas valid.")
        sys.exit(0)
    else:
        sys.exit(1)
