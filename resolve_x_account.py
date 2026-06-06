import time
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

def resolve_x_account(is_test=False):
    if is_test:
        # Injected fake identity available only under explicit test configuration
        return {
            "canonical_account_id": "idkpickoneforme",
            "current_handle": "idkpickoneforme",
            "profile_url": "https://x.com/idkpickoneforme",
            "resolution_method": "test_stub",
            "resolution_timestamp": time.time()
        }
        
    # Production resolver: Read-only inspection of the actual authenticated browser session
    USER_DATA_DIR = Path("/Users/jon") / ".hermes" / "browser_profile"
    
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=True,
            channel="chrome"
        )
        page = browser.pages[0]
        page.goto("https://x.com", wait_until="domcontentloaded")
        
        # Wait for the account menu or handle to appear (read-only inspection)
        try:
            # We extract the handle from the DOM.
            profile_link = page.wait_for_selector('a[data-testid="AppTabBar_Profile_Link"]', timeout=15000)
            href = profile_link.get_attribute("href")
            
            if href and href.startswith("/"):
                handle = href[1:]
            else:
                raise Exception("Failed to extract valid handle from href")
                
            res = {
                "canonical_account_id": handle,
                "current_handle": handle,
                "profile_url": f"https://x.com/{handle}",
                "resolution_method": "playwright_session_inspection",
                "resolution_timestamp": time.time()
            }
        except Exception as e:
            res = {"error": str(e)}
        finally:
            browser.close()
            
        return res
