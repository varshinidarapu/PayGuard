from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from backend.config import DATABASE_URL, ROOT
from backend.auth import ensure_bootstrap_key
with psycopg.connect(DATABASE_URL) as conn:
    conn.execute((ROOT/'db/schema.sql').read_text())
    ensure_bootstrap_key(conn)
print('Schema ready. Existing transactions and balances preserved.')
