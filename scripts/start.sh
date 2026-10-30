#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python scripts/configure.py
python scripts/init_db.py
exec python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
