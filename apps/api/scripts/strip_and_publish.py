import os
import sys
import re
from pathlib import Path

# Add app to path
app_root = Path(r"d:\Donggri_Platform\BloggerGent\apps\api")
sys.path.append(str(app_root))

from scripts.package_common import CloudflareIntegrationClient

def main():
    client = CloudflareIntegrationClient(
        base_url="https://api.dongriarchive.com",
        token="X63TSM9wj17J30aELJYe9M2tolMqniQ3ADfxb1WKGMmxjA8m6caybo5pWISLH29-"
    )
    
    post_id = "575dda3c-b707-471e-aa88-16e875771e88"
    detail = client.get_post(post_id)
    content = detail.get("content", "")
    
    print("[*] Stripping all style attributes...")
    # Robustly strip style="..." from any tag
    cleaned = re.sub(r'\s+style\s*=\s*[\'"].*?[\'"]', "", content, flags=re.IGNORECASE)
    
    print("[*] Updating content and status to 'published'...")
    category_id = detail.get("category", {}).get("id")
    
    payload = {
        "title": detail.get("title"),
        "content": cleaned,
        "status": "published",
        "categoryId": category_id
    }
    
    try:
        res = client.update_post(post_id, payload)
        print("Success! Post published with iframe (and no styles).")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    main()
