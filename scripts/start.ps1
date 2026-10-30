$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python scripts/configure.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/init_db.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
