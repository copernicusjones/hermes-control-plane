import sqlite3
import os

LEDGER_DB = "/Users/jon/.hermes/deployment_ledger.db"

def get_db_connection(db_path=LEDGER_DB, timeout=10.0):
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    
    # Ensure owner-only permissions
    try:
        os.chmod(db_path, 0o600)
    except:
        pass
    return conn
