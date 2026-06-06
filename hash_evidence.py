import os
import hashlib
import json
from datetime import datetime

TARGETS = [
    "/Users/jon/.hermes/deployment_ledger.db",
    "/Users/jon/.hermes/deployment_ledger.db-shm",
    "/Users/jon/.hermes/deployment_ledger.db-wal",
    "/Users/jon/.hermes/deployment_ledger.pre-sqlite.json",
    "/Users/jon/.hermes/scripts/migrate_ledger.py",
    "/Users/jon/.hermes/scripts/fix_schema.py",
    "/Users/jon/.hermes/scripts/approve.py",
    "/Users/jon/.hermes/scripts/x_poster.py",
    "/Users/jon/.hermes/scripts/reconcile_stale_dispatch.py",
    "/Users/jon/.hermes/scripts/test_isolated_suite.py",
    "/Users/jon/.hermes/scripts/check_timeline.py",
    "/Users/jon/.hermes/scripts/test_approve_concurrency.py",
    "/Users/jon/Documents/novaaaaa/operations/evidence/db_inspection_results.json",
    "/Users/jon/Documents/novaaaaa/operations/evidence/migration_reconciliation.json",
    "/Users/jon/Documents/novaaaaa/operations/evidence/incident_reconciliation.json",
    "/Users/jon/Documents/novaaaaa/operations/evidence/schedule_audit.json",
    "/Users/jon/Documents/novaaaaa/operations/evidence/test_results_v4.json",
    "/Users/jon/Documents/novaaaaa/operations/evidence/remaining_blockers.json",
    "/Users/jon/Documents/novaaaaa/operations/evidence/phase-3-ledger-recovery-and-dispatch-integrity-report-2026-06-06.md",
]

# Add backups
import glob
backups = glob.glob("/Users/jon/Documents/novaaaaa/operations/evidence/deployment_ledger_backup_*.db")
TARGETS.extend(backups)

evidence = []

for t in TARGETS:
    if os.path.exists(t):
        size = os.path.getsize(t)
        mtime = os.path.getmtime(t)
        with open(t, 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest()
        evidence.append({
            "path": t,
            "size_bytes": size,
            "mtime_iso": datetime.fromtimestamp(mtime).isoformat(),
            "sha256": h
        })
    else:
        evidence.append({
            "path": t,
            "status": "NOT_FOUND"
        })

out_path = "/Users/jon/Documents/novaaaaa/operations/evidence/freeze_manifest_v2.json"
with open(out_path, 'w') as f:
    json.dump(evidence, f, indent=2)

print(f"Manifest written to {out_path}")
