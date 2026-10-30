# PayGuard API

Base URL: `http://127.0.0.1:8000`. All money amounts are **integer paise**, so `10000` is INR 100.00. Only INR is supported. Accounts are synthetic and belong to one sandbox operator. This is an internal transfer simulator, not a bank integration.

## Authentication

All `/api` routes except health require `Authorization: Bearer <API_KEY>`. Copy the generated key from `.env` into the dashboard's password field. The dashboard keeps it in sessionStorage until Disconnect or the tab session ends. Do not embed the key in source, URLs, screenshots or client bundles. The operator is authorized over all three sandbox accounts. This is not individual customer authentication.

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard and six reliability demonstrations |
| GET | `/api/health` | Database readiness and Redis fallback status |
| GET | `/api/accounts` | Current authoritative balances |
| POST | `/api/payments` | Settle or replay a simulated payment |
| GET | `/api/payments?limit=100` | Latest committed payments, limit 1–500 |
| GET | `/api/payments/by-key/{key}` | Resolve a potentially lost result |
| GET | `/api/payments/{uuid}` | Verify a specific payment |
| GET | `/api/ledger` | First up to 1,000 ledger entries in payment ID order |
| GET | `/api/audit` | Snapshot reconciliation, total conservation, payment/ledger checks |
| GET | `/docs` | Interactive OpenAPI reference (CDN assets need internet) |
| GET | `/openapi.json` | Offline-readable machine API specification |

## Create payment

Headers: Authorization plus `Idempotency-Key`, 8–128 characters `[A-Za-z0-9._:-]`. Use a UUID with `pg-` prefix. The key is scoped to the authenticated sandbox operator. Reuse **exactly the same key and payment fields** for retries.

```json
{"sender_id":1,"receiver_id":2,"amount":10000,"currency":"INR"}
```

Body rejects extra fields, fractions, booleans, zero/negative amounts, self-transfers and non-INR currency. Maximum amount: 100,000,000 paise (INR 1,000,000).

Response includes `id`, `idempotency_key`, account IDs, amount, currency, status, failure code, creation and completion timestamps. `Idempotency-Replayed: true` identifies a repeated result. `Idempotency-Source` is `new`, `redis` or `postgresql`. Replays preserve the original JSON body. First successful settlement returns 201 and a replay returns 200. Failed insufficient-funds payments return 422 on both first request and replay.

| HTTP code | Meaning | Caller action |
|---|---|---|
| 201 | New committed success | Save returned payment ID |
| 200 | Replayed committed success | Use original payment ID |
| 401 | Invalid or missing operator token | Supply correct token |
| 403 | Fault injection disabled | Use ordinary payment route |
| 404 | Unknown account or no committed result | For status lookup, retry the same key, since a request may be in flight |
| 409 | Same key reused with different fields | Restore original fields or explicitly start a separate new payment |
| 422 | Input validation or durable insufficient-funds outcome | Inspect body. A durable FAILED payment will keep replaying FAILED |
| 503 | Server interrupted, database unavailable or busy | Outcome may be unknown. Query status and retry the same key with backoff |

Never interpret a network error or 503 as proof of failure. A commit acknowledgment can be lost. PostgreSQL's unique key resolves the ambiguity on the next request. A 404 lookup also does not prove an in-flight payment will fail.

## Demonstration fault injection

Requires `DEMO_MODE=true`, the normal authentication token, and `X-Demo-Fault`:

- `rollback`: raises an exception after sender debit and before receiver credit. The transaction rolls back. The key remains available for a safe retry.
- `delayed-response`: commits first, then delays response for 2 seconds. A client timeout below 2 seconds models a lost reply. Retry the original key.
- `crash-before-commit` and `crash-after-commit`: additionally require `ALLOW_CRASH_TESTS=true`. Exit an isolated API worker with codes 71 and 72. Used only by the automated tests, never enabled on the review server.

Faults are learning tools, not public API features. Set both demo and crash flags false outside a local demonstration.

## Redis retention

Cached terminal responses have a configurable 86,400-second TTL. Cache entries include a SHA-256 canonical request fingerprint. Database `(client_id, idempotency_key)` uniqueness lasts as long as the payment record. No cleanup job removes payment records. Redis misses, evictions, expiry or outage fall back to the database. Redis does not authorize, debit or commit payments.
