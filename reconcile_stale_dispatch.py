#!/usr/bin/env python3
import datetime
import sys
from db_utils import get_db_connection

# Timeout + safety margin. Production timeout is 120s, so we use 600s (5x) to ensure complete worst-case execution.
STALE_THRESHOLD_SECONDS = 600

def main():
    try:
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        
        cur = conn.execute("SELECT operation_id, lease_expires_at, reserved_at, state FROM operations WHERE state IN ('DISPATCHING', 'DISPATCH_AUTHORIZED', 'RESERVED')")
        
        now = datetime.datetime.now(datetime.timezone.utc)
        for row in cur.fetchall():
            op_id, lease_expires_at, reserved_at, state = row
            try:
                # Use lease if available, otherwise fallback to reserved_at + threshold
                ts_str = lease_expires_at if lease_expires_at else reserved_at
                if ts_str:
                    ts = datetime.datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=datetime.timezone.utc)
                    
                    is_stale = False
                    if lease_expires_at:
                        is_stale = now > ts
                    else:
                        is_stale = (now - ts).total_seconds() > STALE_THRESHOLD_SECONDS

                    if is_stale:
                        new_state = "UNKNOWN_REMOTE_STATE" if state in ('DISPATCHING', 'DISPATCH_AUTHORIZED') else "FAILED_PRE_DISPATCH"
                        
                        # Guard update with exact state and timestamp matching
                        if lease_expires_at:
                            upd_cur = conn.execute("""
                                UPDATE operations 
                                SET state = ?, requires_manual_reconciliation = 1
                                WHERE operation_id = ? AND state = ? AND lease_expires_at = ?
                            """, (new_state, op_id, state, lease_expires_at))
                        else:
                            upd_cur = conn.execute("""
                                UPDATE operations 
                                SET state = ?, requires_manual_reconciliation = 1
                                WHERE operation_id = ? AND state = ? AND reserved_at = ?
                            """, (new_state, op_id, state, reserved_at))
                        
                        if upd_cur.rowcount == 1:
                            conn.execute("""
                                INSERT INTO operation_events (
                                    operation_id, prior_state, new_state, timestamp, worker, reason
                                ) VALUES (?, ?, ?, ?, ?, ?)
                            """, (op_id, state, new_state, now.isoformat(), "stale_reconciler", "Exceeded stale dispatch threshold or lease"))
            except Exception as e:
                pass
                
        conn.commit()
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    main()
