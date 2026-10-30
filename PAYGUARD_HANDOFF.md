# PayGuard complete handoff and startup guide

This file preserves the useful development context and gives step-by-step instructions for reopening, running, testing, and demonstrating PayGuard. It can be provided to ChatGPT or followed manually.

## 1. Current working result

- Local project folder: `C:\Projects\payguard`
- GitHub repository: `https://github.com/varshinidarapu/PayGuard`
- Public Render application: `https://payguard-app-tmwg.onrender.com/`
- Stack: FastAPI, PostgreSQL 16, Redis-compatible cache, Docker Compose, and a browser dashboard.
- Backend result: 21 of 21 isolated integration tests passed.
- Hosted dashboard result: 6 of 6 reliability demonstrations passed.
- The application uses simulated INR only. It does not move real money.

## 2. What was developed

1. PostgreSQL schema for accounts, payments, and double-entry ledger records.
2. Permanent `(client_id, idempotency_key)` uniqueness to prevent duplicate settlement.
3. Redis replay caching with request fingerprints and PostgreSQL fallback.
4. Transactions that lock account rows in increasing ID order before changing balances.
5. Atomic payment status, balance, and ledger updates with rollback on interruption.
6. Failure demonstrations for delayed responses, insufficient funds, and rollback.
7. A responsive dashboard with payment, reliability tests, history, ledger audit, and About sections.
8. Docker Compose startup, isolated test database automation, GitHub source control, and Render deployment.
9. Database-backed clients and hashed API keys with one-time secret display, safe prefix listing, expiry, rotation and revocation.
10. Client-owned accounts plus private payment and ledger records; API-key rotation preserves client-scoped payment idempotency.

During setup, `scripts/run_tests.py` was corrected to create its excluded `evidence` directory inside the Docker image. Render support was added through `render.yaml`, and the Docker command was updated to respect Render's `PORT` while keeping local port 8000.

## 3. Reopen the project and this Codex chat

1. Start Docker Desktop and wait for **Docker Desktop is running**.
2. Open VS Code.
3. Select **File > Open Folder** and choose `C:\Projects\payguard`.
4. Open the Codex/Chat panel and select this PayGuard conversation from **Recent chats** or chat history.
5. If using Codex CLI, open PowerShell in the project folder and use `/resume` or `codex resume` to select a saved discussion.
6. Keep this file and the GitHub repository as the permanent handoff even if chat history is unavailable.

The exact chat transcript is stored by the Codex client, not inside this Git repository. This handoff records the material development decisions and results without storing secrets.

## 4. Wake and use the free Render deployment

1. Open `https://payguard-app-tmwg.onrender.com/`.
2. A free service may be asleep. Wait up to a few minutes for the first page load, then refresh once.
3. Confirm the top-right status says **PostgreSQL + Redis online**.
4. Open Render Dashboard > `payguard-app` > **Environment**.
5. Reveal and copy `API_KEY`. Never paste it into chat, GitHub, screenshots, or documentation.
6. Paste the key into PayGuard and click **Connect**.
7. Confirm the three accounts appear and **Ledger integrity** says **Verified**.

If Render reports a deployment problem, open the service's **Logs** tab and check whether the database and Redis resources are available. The Blueprint definitions are in `render.yaml`.

## 5. Guaranteed localhost fallback

Use this if Render is sleeping, slow, or unavailable.

### First-time or clean startup

1. Start Docker Desktop.
2. Open PowerShell in `C:\Projects\payguard`.
3. Check that `.env` exists. It contains the local secret and must never be committed.
4. If `.env` is missing and Python 3.12+ is installed, run `python scripts/configure.py` once. If Python is unavailable, copy `.env.example` to `.env` and replace the placeholder `API_KEY` with a private value at least 24 characters long.
5. Run:

```powershell
docker compose up --build -d
docker compose ps
```

6. Wait until `postgres` and `redis` show **healthy** and `app` shows **Up**.
7. Open `http://127.0.0.1:8000`.
8. Open `.env`, copy only the value after `API_KEY=`, paste it into the dashboard, and click **Connect**.

### Normal startup after the images already exist

```powershell
docker compose up -d
docker compose ps
```

### Health and troubleshooting checks

```powershell
docker compose logs --tail=60 app
docker compose exec redis redis-cli ping
```

Expected Redis response: `PONG`. The application health URL is `http://127.0.0.1:8000/api/health`.

Do not delete volumes or use `docker compose down -v`. The normal command `docker compose down` stops containers while preserving PostgreSQL data.

## 6. Run the automated backend tests

The test runner uses the isolated `payguard_test` database and does not reset the demonstration database.

```powershell
docker compose exec app python scripts/run_tests.py
```

Expected final result:

```text
21 passed
```

These tests cover all original payment safeguards plus multiple clients, ownership isolation, safe key listing, expiry, revocation, rotation, unauthorized administration and duplicate retry after rotation.

## 7. Run the six dashboard demonstrations

1. Connect with the correct API key.
2. Select **Reliability tests** from the left menu.
3. Click **Run all six tests**.
4. Wait for **6 / 6 passed**.
5. Confirm every card says **PASS - Verified**.
6. Open **Transactions** to show the committed payment records.
7. Open **Ledger & audit**, click **Verify ledger**, and show that the total balance remains conserved.

The six demonstrations prove:

1. A normal payment changes both balances exactly once.
2. Duplicate requests return one payment ID and debit only once.
3. Concurrent unique transfers produce exact balances.
4. A lost response can be retried with the original key safely.
5. Insufficient funds produces a durable failure with no debit.
6. An injected mid-transaction failure rolls back all changes.

## 8. Simple explanation of each dashboard section

- **Overview:** service health, total sandbox money, successful payment count, volume, and ledger integrity.
- **Create payment:** select sender, receiver, amount, and an idempotency key. Reuse the same key only when retrying the same intended payment.
- **Reliability tests:** executable demonstrations of the project's three main safeguards.
- **Transactions:** latest authoritative payment records and statuses from PostgreSQL.
- **Ledger & audit:** verifies that opening balances plus ledger changes equal current balances.
- **About:** summarizes the prototype, architecture, usage, and limitations.

## 9. How to build the entire prototype from the beginning

Follow this order if the project must be recreated or explained as a development process. The finished implementations are already present in the named files.

1. **Create the project structure:** add `backend`, `frontend`, `db`, `infra`, `scripts`, `tests`, `docs`, and `evidence` folders.
2. **Define configuration:** create `.env.example`, then use `scripts/configure.py` to generate a private `.env` without overwriting an existing one.
3. **Design PostgreSQL storage:** implement accounts, payments, and double-entry ledger tables in `db/schema.sql`. Add the permanent unique constraint on `(client_id, idempotency_key)`.
4. **Add the API foundation:** use `backend/config.py` for settings, `backend/database.py` for the PostgreSQL pool, `backend/models.py` for request validation, and `backend/main.py` for FastAPI routes and static dashboard hosting.
5. **Implement safe settlement:** in `backend/payments.py`, start a PostgreSQL transaction, lock both account rows in increasing ID order, verify funds, update balances, create balanced ledger entries, and commit the final payment status atomically.
6. **Add duplicate protection:** reserve each idempotency key in PostgreSQL, store request fingerprints and completed responses in Redis, and always fall back to PostgreSQL when Redis is unavailable or expired.
7. **Add failure recovery:** ensure exceptions roll back the transaction, failed payments cannot change balances, committed payments replay after a lost response, and retries use the original idempotency key.
8. **Build the dashboard:** create the layout in `frontend/index.html`, styling in `frontend/style.css` and `frontend/about.css`, and API calls plus six reliability demonstrations in `frontend/app.js`.
9. **Containerize everything:** define the Python application in `Dockerfile`; define PostgreSQL, Redis, health checks, volumes, and the app in `compose.yaml`; configure Redis with `infra/redis.conf`.
10. **Add initialization and startup:** use `scripts/init_db.py` for schema/sample data and `scripts/start.ps1` for Windows startup. Build locally with:

```powershell
python scripts/configure.py
docker compose up --build -d
docker compose ps
```

11. **Add isolated automated tests:** implement fixtures in `tests/conftest.py`, safeguard scenarios in `tests/test_payments.py`, and execute them through `scripts/run_tests.py` against `payguard_test` only:

```powershell
docker compose exec app python scripts/run_tests.py
```

12. **Verify the user demonstration:** connect at `http://127.0.0.1:8000`, show the authenticated client, create and revoke a temporary API key, run all six dashboard tests, inspect Transactions, and verify Ledger & audit. The expected results are `21 passed` in the backend and `6 / 6 passed` in the dashboard.
13. **Publish the source:** initialize Git, exclude `.env`, commit the project, add the GitHub remote, and push `main`. Never commit API keys.
14. **Deploy on Render:** use `render.yaml` to create the web service, PostgreSQL, and Redis-compatible service. After deployment, obtain `API_KEY` from Render Environment, connect the dashboard, and repeat all six demonstrations.

The architecture explanation is in `docs/ARCHITECTURE.md`, API behavior is in `docs/API.md`, and recorded test evidence is summarized in `docs/TEST_RESULTS.md`.

## 10. Important safety and scope

- Never commit `.env` or expose `API_KEY`.
- Keep `ALLOW_CRASH_TESTS=false` on Render.
- Redis improves replay speed, but PostgreSQL remains the correctness authority.
- The guarantee is at most one committed internal settlement per client and idempotency key.
- External bank settlement, production security controls, replication, and real-money processing are outside this academic prototype.
