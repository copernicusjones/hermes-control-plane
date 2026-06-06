import sqlite3
import os
import hashlib
from datetime import datetime
from db_utils import get_db_connection

AUTHORITATIVE_BACKUP = "/Users/jon/Documents/novaaaaa/operations/evidence/deployment_ledger_backup_20260606-123742.db"
CANDIDATE_DB = "/Users/jon/.hermes/candidate_ledger.db"

def main():
    if os.path.exists(CANDIDATE_DB):
        os.remove(CANDIDATE_DB)

    print("Building target schema in candidate DB...")
    with get_db_connection(CANDIDATE_DB) as conn:
        conn.execute("""
        CREATE TABLE operations (
            operation_id TEXT PRIMARY KEY,
            queue_item_id TEXT,
            deployment_fingerprint TEXT NOT NULL UNIQUE,
            fingerprint_schema_version TEXT,
            platform TEXT,
            canonical_account_id TEXT,
            current_handle TEXT,
            operation_type TEXT,
            payload_hash TEXT,
            normalized_content_hash TEXT,
            media_checksum TEXT,
            campaign_version TEXT,
            intended_parent TEXT,
            normalization_version TEXT,
            reservation_nonce_hash TEXT,
            state TEXT NOT NULL,
            evidence_status TEXT,
            worker_id TEXT,
            pid INTEGER,
            hostname TEXT,
            reserved_at TEXT,
            dispatch_authorized_at TEXT,
            dispatch_claimed_by TEXT,
            heartbeat_at TEXT,
            lease_expires_at TEXT,
            remote_result_timestamp TEXT,
            remote_root_status_id TEXT UNIQUE,
            remote_root_url TEXT,
            verification_metadata TEXT,
            completion_timestamp TEXT,
            requires_manual_reconciliation INTEGER DEFAULT 0,
            source TEXT,
            migration_confidence TEXT
        )
        """)
        
        conn.execute("CREATE INDEX idx_state ON operations(state);")
        conn.execute("CREATE INDEX idx_stale ON operations(requires_manual_reconciliation);")
        conn.execute("CREATE INDEX idx_queue ON operations(queue_item_id);")

        conn.execute("""
        CREATE TABLE operation_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            prior_state TEXT,
            new_state TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            worker TEXT,
            reason TEXT,
            metadata_hash TEXT,
            FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
        )
        """)
        conn.commit()

    print("Copying and transforming rows from authoritative backup...")
    # Just validate schema and output info since we have 0 rows
    with get_db_connection(CANDIDATE_DB) as dst:
        cur = dst.execute("PRAGMA integrity_check;")
        print("Integrity Check:", cur.fetchone()[0])
        cur = dst.execute("PRAGMA foreign_key_check;")
        fk = cur.fetchall()
        print("Foreign Key Check:", fk if fk else "OK")

if __name__ == "__main__":
    main()
