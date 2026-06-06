import sqlite3
import os
import hashlib
from datetime import datetime
from pathlib import Path

DB_PATH = "/Users/jon/.hermes/deployment_ledger.db"
BACKUP_DIR = "/Users/jon/Documents/novaaaaa/operations/evidence"

def main():
    if not os.path.exists(DB_PATH):
        print("DB does not exist.")
        return

    # 1. Consistent Backup
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"deployment_ledger_backup_{ts}.db")
    
    with sqlite3.connect(DB_PATH) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
        
    with open(backup_path, "rb") as f:
        backup_hash = hashlib.sha256(f.read()).hexdigest()
        
    print(f"Backup created at {backup_path} with SHA-256: {backup_hash}")

    # 2. Fix Schema
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        
        # We will create a new table and copy if needed, then drop old.
        conn.execute("""
        CREATE TABLE IF NOT EXISTS operations_v2 (
            operation_id TEXT PRIMARY KEY,
            queue_item_id TEXT,
            deployment_fingerprint TEXT NOT NULL UNIQUE,
            platform TEXT,
            canonical_account_id TEXT,
            operation_type TEXT,
            normalized_content_hash TEXT,
            media_checksum TEXT,
            campaign_version TEXT,
            intended_parent TEXT,
            normalization_version TEXT,
            reservation_nonce_hash TEXT,
            remote_id TEXT,
            state TEXT NOT NULL,
            evidence_status TEXT,
            worker_id TEXT,
            pid INTEGER,
            hostname TEXT,
            reserved_at TEXT,
            dispatch_authorized_at TEXT,
            remote_result_timestamp TEXT,
            verification_metadata TEXT,
            completion_timestamp TEXT,
            requires_manual_reconciliation INTEGER DEFAULT 0,
            source TEXT,
            migration_confidence TEXT
        )
        """)
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS operation_events_v2 (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            prior_state TEXT,
            new_state TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            worker TEXT,
            reason TEXT,
            metadata_hash TEXT,
            FOREIGN KEY(operation_id) REFERENCES operations_v2(operation_id)
        )
        """)
        
        conn.execute("DROP TABLE IF EXISTS operation_events")
        conn.execute("DROP TABLE IF EXISTS operations")
        conn.execute("ALTER TABLE operations_v2 RENAME TO operations")
        conn.execute("ALTER TABLE operation_events_v2 RENAME TO operation_events")
        conn.commit()

    print("Schema updated successfully.")

if __name__ == "__main__":
    main()
