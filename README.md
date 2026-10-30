# PayGuard

**An Idempotent Payment Gateway for Secure and Consistent Transaction Processing**

A complete multi-client academic sandbox: FastAPI, PostgreSQL, Redis, database-backed API keys, and a responsive browser dashboard. Uses simulated internal INR transfers only. No bank, card, paid API or subscription is required.

## Why this working prototype is useful

1. **Prevents duplicate payments:** Redis recognizes fast retries, while PostgreSQL permanently enforces one payment per client and idempotency key.
2. **Protects balances during concurrency:** account rows are locked in a fixed order inside PostgreSQL transactions before funds are checked and changed.
3. **Recovers safely from failures:** uncertain requests reuse the original key, committed results replay, and interrupted transactions roll back completely.
4. **Provides auditable evidence:** every successful transfer creates balanced debit and credit ledger entries, and the dashboard verifies stored balances against that ledger.
5. **Demonstrates the behavior clearly:** the browser dashboard includes six executable reliability scenarios using simulated INR, with no bank or real-money integration.

For complete startup, deployment, chat-recovery, testing, and demonstration steps, read `PAYGUARD_HANDOFF.md`.

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

The suite uses ports 8001 and 8002 inside the container and leaves the demonstration database untouched. It resets only a database whose name ends in `_test`. Retrieve its output if desired:

```powershell
docker compose cp app:/app/evidence/integration-results.json ./evidence/latest-integration-results.json
docker compose cp app:/app/evidence/pytest-output.txt ./evidence/latest-pytest-output.txt
```

Docker Compose startup was verified on Windows with real PostgreSQL 16 and Redis 7 services. See `docs/TEST_RESULTS.md` for exact evidence and limitations.

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

This needs PostgreSQL and Redis but does not need the main API running. It creates an isolated test database, starts test API workers, executes all integration scenarios, writes JSON/JUnit/text evidence, and stops test workers. Demonstration data stays intact. If CREATEDB is unavailable, have an administrator create `payguard_test` owned by `payguard` first.

Optional browser checks, while the main app is running (these change demonstration sandbox balances):

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

Accounts belong to database-backed clients. An authenticated client sees and transfers only between its own authorized accounts, and sees only its payment and ledger records. The bootstrap client owns the three sample accounts.

## API keys versus payment idempotency keys

- **Client API keys** authenticate access. Their secrets are stored only as hashes, shown once when created, and can be listed by prefix, expired, rotated or revoked in **API Key Management**.
- **Payment idempotency keys** identify one intended payment. Reuse the same value only for a retry. They remain scoped to the stable client ID, so rotating an API key cannot settle the payment again.
- The `.env` `API_KEY` is the initial administrator bootstrap key. Use the dashboard to create normal expiring client keys; never commit or display any full key.

## Files

```text
backend/       FastAPI routes, input models, PostgreSQL pool, settlement engine
frontend/      Complete dashboard, six demonstrations, styling
db/            Schema, constraints, deferred commit validation and sample accounts
infra/         Redis sandbox configuration
scripts/       Setup, startup, isolated integration runner, browser verification
tests/         Executable API, concurrency, outage, crash and database tests
docs/          Architecture, API, development history, test results and operating guides
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

At most one committed internal settlement per client/payment-idempotency-key, backed by one authoritative PostgreSQL database. This does not mean exactly-once HTTP delivery or deduplication across different payment keys. Production payment processing would require external provider reconciliation and additional security/operational controls. Keep this simulation local. Fault injection requires DEMO_MODE, and process-exit faults additionally require ALLOW_CRASH_TESTS (false by default).
