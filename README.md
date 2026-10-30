# PayGuard

**An Idempotent Payment Gateway for Secure and Consistent Transaction Processing**

A complete local academic sandbox: FastAPI, PostgreSQL, Redis, and a browser dashboard. Uses simulated internal INR transfers only. No bank, card, paid API or subscription is required.

## Start here for tomorrow's review

1. Start with the Docker option below, or use the native option if PostgreSQL and Redis are already installed.
2. Open `http://127.0.0.1:8000`, paste API_KEY from `.env`, and press **Connect**.
3. Follow `docs/LIVE_DEMO.md` and rehearse the six reliability tests.
4. Read `docs/TEST_RESULTS.md`, `docs/PROJECT_REPORT.md`, and `docs/VIVA.md`.
5. Use the architecture, test results and viva guide for your prototype review. A final slide deck is not included in this prototype package.

## Option A: Docker Desktop (Windows / macOS / Linux)

Prerequisites: Python 3.12+ for one-time local key generation, Docker with Compose v2. On Windows, start Docker Desktop and use Linux containers. Internet is needed for initial images/dependencies. No Python package installation is needed on the host for the application.

From the extracted `payguard` directory:

```powershell
python scripts/configure.py
docker compose up --build -d
docker compose ps
```

The same commands work in a Linux shell. First build may take a few minutes. Open `.env` locally and copy API_KEY. Do not share this file. The UI is `http://127.0.0.1:8000`.

Logs and shutdown:

```powershell
docker compose logs --tail=60 app
docker compose down
```

Stopping preserves the `pgdata` volume. Re-running init does not overwrite balances. Redis is intentionally disposable. To restart later: `docker compose up -d`.

Run the integration suite against an automatically created separate `payguard_test` database:

```powershell
docker compose exec app python scripts/run_tests.py
```

The suite uses ports 8001 and 8002 inside the container and leaves the review database untouched. It resets only a database whose name ends in `_test`. Retrieve its output if desired:

```powershell
docker compose cp app:/app/evidence/integration-results.json ./evidence/latest-integration-results.json
docker compose cp app:/app/evidence/pytest-output.txt ./evidence/latest-pytest-output.txt
```

Docker is included as a portable startup option. Docker itself was unavailable in the build environment, so the Compose build was not executed here. The actual application was executed and tested natively with real PostgreSQL 16.15 and Redis 7.0.15. See `docs/TEST_RESULTS.md` for exact evidence and limitations.

## Option B: Native Python + PostgreSQL + Redis

Prerequisites: Python 3.12+, PostgreSQL 16+, Redis 7+. On Windows, use Docker for Redis or run PostgreSQL/Redis in WSL2. On Linux, use your normal package manager and run services under their usual system users.

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/configure.py
```

Create the role and database using the PostgreSQL administrator (`psql -U postgres`, or `sudo -u postgres psql` on Ubuntu):

```sql
CREATE ROLE payguard LOGIN PASSWORD 'payguard_local_only' CREATEDB;
CREATE DATABASE payguard OWNER payguard;
```

The CREATEDB permission supports automatic creation of the isolated test database. It is a local demonstration convenience, not a production runtime privilege. Keep the password synchronized with DATABASE_URL in `.env`.

Start Redis on loopback (if it is not already running):

```bash
redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no
```

In another activated terminal, start the schema and app:

```bash
python scripts/init_db.py
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Alternatively use `bash scripts/start.sh` on Linux or `./scripts/start.ps1` in PowerShell. Run from the project directory. Both scripts configure a missing `.env`, preserve an existing one, initialize schema, and start the API that serves the frontend.

## Verify

In a second activated terminal:

```bash
python scripts/run_tests.py
```

This needs PostgreSQL and Redis but does not need the review API running. It creates an isolated test database, starts test API workers, executes all integration scenarios, writes JSON/JUnit/text evidence, and stops test workers. Review data stays intact. If CREATEDB is unavailable, have an administrator create `payguard_test` owned by `payguard` first.

Optional browser checks, while the main app is running (these change review sandbox balances):

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/browser_verify.py
```

The app itself has no Node or browser-automation dependency. JavaScript/CSS are local, with no frontend build step. Interactive Swagger `/docs` loads its assets from a CDN; the dashboard and `/openapi.json` work without that CDN.

## Core behavior

- Redis caches completed results and a request fingerprint for 24 hours.
- PostgreSQL permanently enforces `(client_id, idempotency_key)` uniqueness.
- A reused key with different amount or accounts returns 409.
- Both account rows lock in increasing ID order before checking funds.
- Debit, credit, ledger entries and terminal payment status commit together.
- Insufficient funds creates a durable FAILED payment without debiting funds.
- An uncommitted interrupted attempt rolls back; its original key can safely retry.
- A committed payment survives a lost reply or process crash and replays on retry.
- Balances use integer paise. `10000` means INR 100.00, never a float.

## Sample accounts

| ID | Synthetic account | Initial INR | Initial paise |
|---|---|---:|---:|
| 1 | Sandbox Wallet | 10,000.00 | 1,000,000 |
| 2 | Demo Merchant | 5,000.00 | 500,000 |
| 3 | Reserve Wallet | 2,500.00 | 250,000 |

All accounts belong to a single sandbox operator. This API key can transfer among them. It is not a customer login or a real payment authorization system. There is no unrelated registration module.

## Files

```text
backend/       FastAPI routes, input models, PostgreSQL pool, settlement engine
frontend/      Complete dashboard, six demonstrations, styling
db/            Schema, constraints, deferred commit validation and sample accounts
infra/         Redis sandbox configuration
scripts/       Setup, startup, isolated integration runner, browser verification
tests/         Executable API, concurrency, outage, crash and database tests
docs/          Architecture, API, academic report, results, demo, viva, presentation
evidence/      Actual execution JSON, JUnit XML and text output
compose.yaml   PostgreSQL + Redis + app, host ports bound to loopback
.env.example   Configuration template; actual .env is generated locally
```

## Troubleshooting

- **API exits at startup:** check `.env`, PostgreSQL credentials and service readiness. API_KEY must be at least 24 characters.
- **401:** paste the exact API_KEY into Connect, without `Bearer ` prefix.
- **Redis offline:** payments still settle safely through PostgreSQL. Start Redis to demonstrate the fast replay path.
- **503 / timeout:** keep the original idempotency key. Use status lookup or Retry last submitted request. Do not generate a new key for the same intended payment.
- **409:** the original key belongs to different request fields. Restore those fields or consciously start a new payment with a new key.
- **Insufficient funds:** use the form to transfer synthetic funds back from another account. Do not edit balances directly.
- **Port conflict:** free 5432, 6379 and 8000 or adjust service URLs/port mappings consistently. Tests additionally need 8001/8002 free in their environment.
- **Windows venv activation blocked:** use `.venv\Scripts\python.exe` directly for Python commands.
- **Docker unavailable:** use native services or WSL2 as described above. No SQLite substitute is used or required.

## Scope of the guarantee

At most one committed internal settlement per operator/key, backed by one authoritative PostgreSQL database. This does not mean exactly-once HTTP delivery or deduplication across different keys. Production payment processing would require external provider reconciliation and additional security/operational controls. Keep this simulation local. Fault injection requires DEMO_MODE, and process-exit faults additionally require ALLOW_CRASH_TESTS (false by default).
