# Live demonstration: PayGuard

Review target: 31 October 2026. Rehearse once before the review. All transfers are synthetic.

## Before the presentation

1. Extract the project. Run `python scripts/configure.py` and `docker compose up --build -d`, or the README's native startup commands.
2. Visit `http://127.0.0.1:8000`. Paste the API_KEY from `.env` into the password field and click Connect. This is access to a sandbox operator dashboard, not a personal bank login.
3. Confirm PostgreSQL + Redis online and Ledger integrity Verified. Keep this dashboard as the only active writer during browser tests.
4. Keep the README, final slides, and `docs/TEST_RESULTS.md` open. Never display the secret or unrelated personal information during screen sharing.
5. Ensure Sandbox Wallet has at least INR 120. If needed, transfer money back from Demo Merchant using the form with a new key.

## Opening explanation (30 seconds)

“PayGuard addresses the three problems in Slide 2: duplicate payments, incorrect balances during concurrent transfers, and unknown outcomes after failures. Redis recognizes completed duplicate requests. PostgreSQL permanently enforces request uniqueness and commits balances, payment status, and ledger entries together. This demonstration uses simulated internal money only.”

## 1. Normal payment (one minute)

- Show the balances of Sandbox Wallet and Demo Merchant.
- Set From to Sandbox Wallet, To to Demo Merchant, amount to 100.00 rupees. Press New key once and note the key.
- Click Send simulated payment. Show HTTP 201, a payment UUID and SUCCEEDED.
- Verify sender decreased by INR 100 and receiver increased by INR 100. Total sandbox money remains INR 17,500.
- Show the row in Payment history.

Explain: “Money uses integer paise. Both balance updates and the ledger settle inside one database transaction.”

## 2. Duplicate prevention (one minute)

- Click Retry last submitted request. Show the identical UUID, replay `true` and HTTP 200. Balances do not change again.
- Open Reliability test bench and click Test duplicate prevention. This sends two simultaneous same-key requests. Show PASS, same UUID, two API responses, one new payment record and one INR 1 debit.
- Explain that sequential replays commonly come from Redis. A simultaneous duplicate may come from PostgreSQL while the first response has not yet populated Redis. Both paths are safe.
- Explain why pressing New key for a retry would represent a separate payment and defeat this guarantee.

## 3. Concurrent transactions (one minute)

- Record Sandbox Wallet's current balance.
- Click Run concurrent payments. The dashboard sends twelve unique INR 1 transfers simultaneously.
- Show twelve successful records, an exact INR 12 sender debit, and Verified ledger integrity.
- Explain `SELECT ... ORDER BY id FOR UPDATE`. Requests touching the same accounts wait for locks, check the latest balance and settle in a safe order.
- If asked about overdrafts, show the automated test result: 20 competing INR 1,000 payments against INR 10,000 produced 10 successes, 10 insufficient-funds rejections, and sender balance zero.

## 4. Lost response and retry (one minute)

- Click Simulate failure & retry.
- The server commits, then delays its response for 2 seconds. The browser aborts waiting at 250 milliseconds.
- The browser resends the same key. Show one UUID, one new payment record, one INR 1 debit and PASS.
- Explain: “A timeout is an unknown outcome. Reusing the original key resolves it safely.”
- For a server crash question, open integration-results.json or TEST_RESULTS.md. The suite actually exited isolated API workers before commit and after commit, then retried through the surviving server. One settlement resulted in each case.

## 5. Insufficient balance (30 seconds)

- Click Test insufficient funds. It requests one paise above the current balance.
- Show FAILED, INSUFFICIENT_FUNDS and HTTP 422. Show unchanged balances and no ledger entries for that payment.
- Repeat with the same key returns the same failed UUID. Adding funds later does not change a terminal failed outcome; an intentionally new attempt uses a new key.

## 6. Rollback and consistency (one minute)

- Click Verify transaction rollback.
- The API injects an exception after debit and before credit. Show HTTP 503, no committed payment record and unchanged balances.
- Show PASS and Ledger integrity Verified.
- Explain that PROCESSING is an uncommitted internal state. A crash rolls it back, so no abandoned durable PROCESSING row needs a recovery worker.

## 7. Database evidence (one minute)

Click Verify ledger and expand Show debit and credit ledger records. Show:

- Per-account `opening_balance + sum(delta) = balance`.
- `opening_total = current_total = 1750000` paise.
- `invalid_payments = 0`.
- Two offsetting ledger entries per successful transfer.
- No ledger entries for insufficient-funds rejections.

For direct SQL with Docker:

```bash
docker compose exec postgres psql -U payguard -d payguard
```

```sql
SELECT id,name,balance FROM accounts ORDER BY id;
SELECT id,idempotency_key,amount,status,failure_code
FROM payments ORDER BY created_at DESC LIMIT 20;
SELECT payment_id,account_id,delta FROM ledger_entries LIMIT 20;
SELECT sum(balance) AS conserved_total FROM accounts;
```

Type `\q` to exit psql. These commands are read only.

## Closing explanation (20 seconds)

“The verified guarantee is at most one committed internal transfer per operator and idempotency key. PostgreSQL protects correctness. Redis speeds replay. The automated suite includes 100 simultaneous unique transfers and 100 simultaneous requests with one key, plus real process crashes. External bank settlement and production-scale availability are outside this academic sandbox.”

## If something goes wrong during review

- Redis offline: show that PostgreSQL fallback still prevents duplicates, then restart Redis.
- No balance: transfer funds back through the form from another synthetic account.
- A slow request: use Retry last submitted request. Keep the original key.
- API unavailable: inspect `docker compose logs --tail=60 app` and restart with `docker compose up -d`. Do not delete the PostgreSQL volume.
- Internet unavailable: once dependencies/images are already installed, the local dashboard needs no CDN or paid API. OpenAPI JSON and bundled documentation remain available.

## Quick alternative

Press Run all six tests for a sequential automated dashboard demonstration. Show `6 / 6 passed` and the execution evidence. Each run transfers INR 15 in total from account 1 to account 2 and records one insufficient-funds failure; the rollback creates no committed payment.
