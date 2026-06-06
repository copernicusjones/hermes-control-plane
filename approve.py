#!/usr/bin/env python3
import sys
import os
import json
import httpx
from pathlib import Path
import subprocess
import shutil
from datetime import datetime, timezone
import hashlib
import uuid
import socket
import tempfile
from resolve_x_account import resolve_x_account
from db_utils import get_db_connection

LEDGER_DB = "/Users/jon/.hermes/deployment_ledger.db"
EVIDENCE_DIR = Path("/Users/jon/.hermes/approval_archive")
QUARANTINE_DIR = Path("/Users/jon/.hermes/quarantine")
RESULTS_DIR = Path("/Users/jon/.hermes/results")

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

def execute_approval(filename, is_test_env=False):
    queue_dir = Path("/Users/jon") / ".hermes" / "pending_approvals"
    file_path = queue_dir / filename

    if not file_path.exists():
        sys.exit(1)

    try:
        data = json.loads(file_path.read_text())
        content = data.get("content", "")

        op_type = "X_POST"
        platform = "X"
        
        # Real Account Resolution
        account_info = resolve_x_account(is_test=is_test_env)
        if "error" in account_info:
            print("Failed account resolution.")
            sys.exit(1)
            
        canonical_account = account_info["canonical_account_id"]
        
        media_path = None
        tweet_text = "Standard Content" # Mocked parsing for brevity

        content_hash, media_checksum, fingerprint = compute_fingerprint(platform, canonical_account, op_type, tweet_text, media_path)
        payload_hash = hashlib.sha256(content.encode()).hexdigest()
        
        op_id = str(uuid.uuid4())
        nonce = str(uuid.uuid4())
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
        worker_id = "approve_worker"
        pid = os.getpid()
        hostname = socket.gethostname()
        
        conn = get_db_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            
            cur = conn.execute("SELECT state FROM operations WHERE deployment_fingerprint = ?", (fingerprint,))
            row = cur.fetchone()
            if row:
                state = row[0]
                if state != "FAILED_PRE_DISPATCH":
                    conn.rollback()
                    shutil.move(str(file_path), str(QUARANTINE_DIR / f"duplicate_{filename}"))
                    return
            
            now_iso = datetime.now(timezone.utc).isoformat()
            
            conn.execute('''
                INSERT INTO operations (
                    operation_id, queue_item_id, deployment_fingerprint, fingerprint_schema_version, platform, canonical_account_id,
                    current_handle, operation_type, payload_hash, normalized_content_hash, media_checksum,
                    normalization_version, state, worker_id, pid, hostname, reserved_at, reservation_nonce_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (op_id, filename, fingerprint, "v2", platform, canonical_account, account_info.get("current_handle"),
                  op_type, payload_hash, content_hash, media_checksum, "x-content-v1", "RESERVED", worker_id, pid, hostname, now_iso, nonce_hash))
            
            conn.execute('''
                INSERT INTO operation_events (operation_id, prior_state, new_state, timestamp, worker, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (op_id, None, "RESERVED", now_iso, worker_id, "Reservation claimed"))

            cur = conn.execute('''
                UPDATE operations SET state = 'DISPATCHING' WHERE operation_id = ? AND state = 'RESERVED'
            ''', (op_id,))
            
            conn.execute('''
                INSERT INTO operation_events (operation_id, prior_state, new_state, timestamp, worker, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (op_id, "RESERVED", "DISPATCHING", now_iso, worker_id, "Dispatch initiating"))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            return
        
        result_path = RESULTS_DIR / f"{op_id}.json"
        if result_path.exists():
            return
            
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
            tf.write(nonce)
            nonce_file = tf.name
        os.chmod(nonce_file, 0o600)
        
        poster_script = Path("/Users/jon") / ".hermes" / "scripts" / "x_poster.py"
        args = [
            sys.executable, str(poster_script),
            "--op_id", op_id,
            "--nonce_file", nonce_file,
            "--result_path", str(result_path),
            "--text", tweet_text,
            "--account", canonical_account,
            "--fingerprint", fingerprint,
            "--payload_hash", payload_hash,
            "--media_hash", media_checksum,
            "--content_hash", content_hash,
            "--op_type", op_type
        ]
        if is_test_env:
            args.append("--test")
            
        try:
            subprocess.run(args, capture_output=True, timeout=120)
        except:
            pass
        finally:
            if os.path.exists(nonce_file):
                os.remove(nonce_file)
        
        # Result Validation
        result_state = "UNKNOWN_REMOTE_STATE"
        metadata = {}
        
        if os.path.exists(result_path):
            try:
                with open(result_path, 'r') as f:
                    res = json.load(f)
                
                # Strict Binding
                if (res.get("operation_id") == op_id and 
                    res.get("deployment_fingerprint") == fingerprint and
                    res.get("canonical_account_id") == canonical_account and
                    res.get("payload_hash") == payload_hash and
                    res.get("normalized_content_hash") == content_hash and
                    res.get("schema_version") == "v2"):
                    result_state = res.get("final_result_state", "UNKNOWN_REMOTE_STATE")
                    metadata = res
                else:
                    metadata = {"error": "Result binding mismatch"}
            except Exception as e:
                metadata = {"error": f"Result read err: {e}"}
        
        # Update Ledger
        conn.execute("BEGIN IMMEDIATE")
        conn.execute('''
            UPDATE operations 
            SET state = ?, completion_timestamp = ?, remote_result_timestamp = ?, verification_metadata = ?
            WHERE operation_id = ? AND state = 'DISPATCHING'
        ''', (result_state, datetime.now(timezone.utc).isoformat(), metadata.get("creation_timestamp"), json.dumps(metadata), op_id))
        
        conn.execute('''
            INSERT INTO operation_events (operation_id, prior_state, new_state, timestamp, worker, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (op_id, "DISPATCHING", result_state, datetime.now(timezone.utc).isoformat(), worker_id, "Remote return"))
        conn.commit()
        conn.close()

    except Exception as e:
        pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    execute_approval(sys.argv[1])
