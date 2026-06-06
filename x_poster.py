#!/usr/bin/env python3
import sys
import os
import json
import time
import argparse
import hashlib
from datetime import datetime, timezone
from db_utils import get_db_connection
from resolve_x_account import resolve_x_account

def write_result(path, payload):
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)
    os.chmod(path, 0o400)

def post_tweet(args):
    result = {
        "schema_version": "v2",
        "operation_id": args.op_id,
        "deployment_fingerprint": args.fingerprint,
        "canonical_account_id": args.account,
        "payload_hash": args.payload_hash,
        "normalized_content_hash": args.content_hash,
        "media_checksum": args.media_hash,
        "normalization_version": "x-content-v1",
        "creation_timestamp": datetime.now(timezone.utc).isoformat(),
        "final_result_state": "UNKNOWN_REMOTE_STATE",
        "error_classification": None
    }
    
    try:
        with open(args.nonce_file, 'r') as f:
            nonce = f.read().strip()
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    except Exception as e:
        result["error_classification"] = f"Failed to read nonce"
        write_result(args.result_path, result)
        return

    account_info = resolve_x_account(is_test=args.test)
    if account_info.get("canonical_account_id") != args.account:
        result["error_classification"] = "Account mismatch"
        write_result(args.result_path, result)
        return
        
    try:
        conn = get_db_connection()
        auth_ts = datetime.now(timezone.utc).isoformat()
        
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("""
            UPDATE operations
            SET reservation_nonce_hash = NULL, dispatch_authorized_at = ?
            WHERE operation_id = ?
              AND state = 'DISPATCHING'
              AND reservation_nonce_hash = ?
              AND deployment_fingerprint = ?
              AND canonical_account_id = ?
        """, (auth_ts, args.op_id, nonce_hash, args.fingerprint, args.account))
        
        if cur.rowcount != 1:
            conn.rollback()
            result["error_classification"] = "Dispatch claim failed"
            write_result(args.result_path, result)
            return
            
        conn.commit()
        result["dispatch_authorization_timestamp"] = auth_ts
    except Exception as e:
        result["error_classification"] = f"SQLite error: {e}"
        write_result(args.result_path, result)
        if 'conn' in locals(): conn.rollback()
        return
    finally:
        if 'conn' in locals(): conn.close()

    if args.test:
        result["final_result_state"] = "VERIFIED_LIVE"
        result["remote_root_status_id"] = "mock_status_123"
        result["ordered_status_ids"] = ["mock_status_123"]
        result["expected_author_id"] = args.account
        result["observed_author_id"] = args.account
        result["expected_status_count"] = 1
        result["observed_status_count"] = 1
        result["verification_method"] = "isolated_test_mock"
        write_result(args.result_path, result)
        return
        
    # Production fallback
    result["final_result_state"] = "FAILED_PRE_DISPATCH"
    result["error_classification"] = "Network isolation enforced"
    write_result(args.result_path, result)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--op_id", required=True)
    parser.add_argument("--nonce_file", required=True)
    parser.add_argument("--result_path", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--payload_hash", required=True)
    parser.add_argument("--media_hash", required=True)
    parser.add_argument("--content_hash", required=True)
    parser.add_argument("--op_type", required=True)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    post_tweet(args)
