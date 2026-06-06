#!/usr/bin/env python3
import time
import os
import json
import sqlite3
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
from db_utils import get_db_connection

def compute_fingerprint(platform, account, op_type, content, media_path=None):
    normalized = " ".join(content.split()).strip().lower()
    content_hash = hashlib.sha256(normalized.encode()).hexdigest()
    
    media_checksum = "NO_MEDIA"
    if media_path and os.path.exists(media_path):
        with open(media_path, "rb") as f:
            media_checksum = hashlib.sha256(f.read()).hexdigest()
            
    fingerprint_input = {
        "platform": platform,
        "canonical_account_id": account,
        "operation_type": op_type,
        "normalized_content_hash": content_hash,
        "media_checksum": media_checksum,
        "campaign_version": "UNVERSIONED",
        "intended_parent": "NO_PARENT",
    }
    canon_str = json.dumps(fingerprint_input, sort_keys=True, separators=(',', ':'))
    return content_hash, media_checksum, hashlib.sha256(canon_str.encode('utf-8')).hexdigest()

def scrape_and_seed():
    USER_DATA_DIR = Path("/Users/jon") / ".hermes" / "browser_profile"
    
    conn = get_db_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=True,
            channel="chrome"
        )
        page = browser.pages[0]
        page.goto("https://x.com", wait_until="domcontentloaded")
        
        try:
            profile_link = page.wait_for_selector('a[data-testid="AppTabBar_Profile_Link"]', timeout=15000)
            href = profile_link.get_attribute("href")
            
            if href and href.startswith("/"):
                handle = href[1:]
            else:
                raise Exception("Failed to extract valid handle from href")
                
            print(f"Resolved account handle: {handle}")
            
            # Go to profile
            page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
            time.sleep(5) # allow timeline to load
            
            tweets = page.locator('div[data-testid="tweetText"]').all_inner_texts()
            
            seeded = 0
            for text in tweets:
                # We skip empty tweets or very short ones just in case
                if not text.strip(): continue
                
                content_hash, media_checksum, fingerprint = compute_fingerprint("X", handle, "X_POST", text)
                op_id = str(uuid.uuid4())
                
                try:
                    conn.execute('''
                        INSERT INTO operations (
                            operation_id, deployment_fingerprint, fingerprint_schema_version, platform, canonical_account_id,
                            current_handle, operation_type, payload_hash, normalized_content_hash, media_checksum,
                            normalization_version, state, worker_id, reserved_at, source, completion_timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (op_id, fingerprint, "v2", "X", handle, handle, "X_POST", 
                          hashlib.sha256(text.encode()).hexdigest(), content_hash, media_checksum, 
                          "x-content-v1", "VERIFIED_LIVE", "seed_ledger", now_iso, "REMOTE_RECONCILIATION", now_iso))
                    seeded += 1
                except sqlite3.IntegrityError:
                    pass # Already exists
                
            conn.commit()
            print(f"Seeded {seeded} posts into ledger from timeline.")
            
        except Exception as e:
            print(f"Error scraping timeline: {e}")
        finally:
            browser.close()
            conn.close()

if __name__ == "__main__":
    scrape_and_seed()
