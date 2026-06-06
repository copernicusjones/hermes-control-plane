import os
import json
import sqlite3
import hashlib
import shutil
import uuid
from datetime import datetime

LEDGER_JSON = "/Users/jon/.hermes/deployment_ledger.json"
LEDGER_PRE = "/Users/jon/.hermes/deployment_ledger.pre-sqlite.json"
LEDGER_DB = "/Users/jon/.hermes/deployment_ledger.db"
EVIDENCE_DIR = "/Users/jon/Documents/novaaaaa/operations/evidence"

def setup_db():
    conn = sqlite3.connect(LEDGER_DB)
    # Use WAL mode
    conn.execute('PRAGMA journal_mode=WAL;')
    
    conn.execute('''
    CREATE TABLE IF NOT EXISTS operations (
        operation_id TEXT PRIMARY KEY,
        queue_item_id TEXT,
        deployment_fingerprint TEXT NOT NULL UNIQUE,
        remote_id TEXT,
        state TEXT NOT NULL,
        evidence_status TEXT,
        worker_id TEXT,
        pid INTEGER,
        hostname TEXT,
        reserved_at TEXT,
        dispatched_at TEXT,
        source TEXT,
        migration_confidence TEXT
    )
    ''')
    
    conn.execute('''
    CREATE TABLE IF NOT EXISTS operation_events (
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
    ''')
    
    conn.commit()
    return conn

def migrate():
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    
    if not os.path.exists(LEDGER_JSON):
        print(f"No {LEDGER_JSON} found to migrate.")
        setup_db()
        return
        
    # Read and Hash
    with open(LEDGER_JSON, 'rb') as f:
        data_bytes = f.read()
    file_hash = hashlib.sha256(data_bytes).hexdigest()
    
    # Copy to evidence
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    evidence_copy = os.path.join(EVIDENCE_DIR, f"deployment_ledger_snapshot_{ts}.json")
    shutil.copy2(LEDGER_JSON, evidence_copy)
    print(f"Copied original ledger to {evidence_copy} (SHA-256: {file_hash})")
    
    # Load JSON
    try:
        data = json.loads(data_bytes.decode('utf-8'))
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        # Move to pre-sqlite and make read-only
        os.rename(LEDGER_JSON, LEDGER_PRE)
        os.chmod(LEDGER_PRE, 0o400)
        setup_db()
        return

    conn = setup_db()
    
    total = len(data)
    imported = 0
    quarantined = 0
    
    quarantine_items = []
    
    for item in data:
        platform = item.get("platform")
        account = item.get("account")
        op_type = item.get("operation_type")
        content_hash = item.get("content_hash")
        
        if not (platform and account and op_type and content_hash):
            quarantine_items.append(item)
            quarantined += 1
            continue
            
        # Create a deterministic fingerprint from canonical JSON as per new rules,
        # but using legacy data. The legacy data is missing intended_parent etc.
        fingerprint_input = {
            "platform": platform,
            "canonical_account_id": account,
            "operation_type": op_type,
            "normalized_content_hash": content_hash,
            "media_checksum": "LEGACY_NO_MEDIA",
            "campaign_version": "LEGACY_UNVERSIONED",
            "intended_parent": "LEGACY_NO_PARENT",
            "legacy": True
        }
        
        # Canonical JSON string
        canon_str = json.dumps(fingerprint_input, sort_keys=True, separators=(',', ':'))
        fingerprint = hashlib.sha256(canon_str.encode('utf-8')).hexdigest()
        
        op_id = str(uuid.uuid4())
        
        try:
            conn.execute('''
                INSERT INTO operations (
                    operation_id, deployment_fingerprint, state, 
                    source, migration_confidence, reserved_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (op_id, fingerprint, "VERIFIED_LIVE", "LEGACY_JSON", "PARTIAL", datetime.now().isoformat()))
            
            conn.execute('''
                INSERT INTO operation_events (
                    operation_id, new_state, timestamp, worker, reason
                ) VALUES (?, ?, ?, ?, ?)
            ''', (op_id, "VERIFIED_LIVE", datetime.now().isoformat(), "migration", "Migrated from JSON ledger"))
            
            imported += 1
        except sqlite3.IntegrityError:
            # Duplicate fingerprint in legacy data
            quarantine_items.append(item)
            quarantined += 1
            
    conn.commit()
    conn.close()
    
    # Quarantine
    if quarantine_items:
        q_path = os.path.join(EVIDENCE_DIR, f"quarantined_legacy_ledger_{ts}.json")
        with open(q_path, 'w') as f:
            json.dump(quarantine_items, f, indent=2)
        print(f"Quarantined {quarantined} invalid/duplicate legacy items to {q_path}")
        
    # Finish up
    os.rename(LEDGER_JSON, LEDGER_PRE)
    os.chmod(LEDGER_PRE, 0o400)
    print(f"Migrated {imported}/{total} items successfully. Renamed original to {LEDGER_PRE} (read-only).")

if __name__ == "__main__":
    migrate()
