# PayGuard beginner guide

## What this prototype is

PayGuard is a local academic sandbox for simulated INR transfers. It demonstrates three reliability safeguards:

1. Redis detects fast duplicate retries, while PostgreSQL permanently enforces one `(client_id, idempotency_key)` payment.
2. PostgreSQL transactions lock both account rows in ID order, preventing concurrent transfers from creating incorrect balances.
3. Balances, payment status, and ledger entries commit together. A failed transaction rolls back; a retry reuses the original key.

It does not connect to a bank, card network, or real-money service.

## Start the project on Windows

Open PowerShell in `C:\Projects\payguard` and run:

```powershell
docker compose up --build -d
docker compose ps
```

All three services should be running: `app`, `postgres` (healthy), and `redis` (healthy).

Open http://127.0.0.1:8000. The API key is stored only in the local `.env` file. Never commit or share `.env`.

## Dashboard steps

1. Paste the value after `API_KEY=` in `.env` into the dashboard and click **Connect**.
2. Confirm the account cards and **Ledger integrity: Verified**.
3. For a normal payment, select Sandbox Wallet -> Demo Merchant, enter `100.00`, keep the generated key, and click **Send simulated payment**.
4. Click **Retry last submitted request**. The same payment ID should appear and balances must not change a second time.
5. In **Reliability test bench**, run the six tests. They use real API requests and change the sandbox balances.
6. In **Database evidence**, click **Verify ledger**. This proves that opening balance plus ledger changes equals each stored balance.

When a request times out, do not create a new key. Use **Retry last submitted request** with the original key.

## Automated testing

Run the isolated suite without touching review data:

```powershell
docker compose exec app python scripts/run_tests.py
```

It creates/uses `payguard_test`, starts temporary API workers on internal ports, runs the backend tests, and writes evidence under `evidence/`. Do not delete the PostgreSQL volume to run tests.

## Current verified status

- Docker Compose application is running locally.
- PostgreSQL and Redis health checks pass.
- 16 backend integration tests pass.
- Review database balances remain conserved at 1,750,000 paise.
- Browser dashboard loads; the six browser buttons can be run manually after connecting.

## GitHub and Vercel

This project is a Docker Compose application with FastAPI, PostgreSQL, and Redis. Vercel can host a static frontend, but it cannot replace the PostgreSQL/Redis services or run this Compose stack as-is. The simplest reliable deployment is:

- GitHub: store the source repository, excluding `.env`, `.venv`, caches, and generated secrets.
- Backend: deploy the Docker application to a container host with managed PostgreSQL and Redis.
- Vercel: use only for a separately configured frontend if the backend URL and CORS policy are added.

Before publishing, create a GitHub repository and provide its HTTPS or SSH remote URL. Then run `git init`, `git add .`, `git commit`, `git branch -M main`, `git remote add origin <URL>`, and `git push -u origin main`. Never push `.env` or API keys.

