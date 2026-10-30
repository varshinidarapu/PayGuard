# Verified execution results

Final verification: 30 October 2026. Backend: **16 passed in 5.22 seconds**. Browser: **6 / 6 demonstration tests passed**.

All amounts below are integer paise. Each backend case starts with fresh accounts: sender 1,000,000, receiver 500,000, reserve 250,000. The browser suite instead performs six tests sequentially against its sandbox.

## Required demonstrations

| Case | Expected | Executed result | Explanation |
|---|---|---|---|
| 1 Normal | One success, sender 990000, receiver 510000 | HTTP 201, SUCCEEDED, two ledger entries, exact balances | Atomic debit and credit commit together |
| 2 Duplicate | Same UUID and one debit | First 201, repeat 200, identical JSON, Redis replay, one record | Redis recognizes the completed key; DB uniqueness remains permanent |
| 3 Concurrent | 100 unique 1000-paise payments, sender 900000 | 100 successes, 100 IDs, sender 900000, receiver 600000 | Ordered row locks serialize balance-dependent decisions |
| 4 Lost response | Timeout followed by one original result | Actual HTTP read timeout at 250 ms, retry 200, same ID, one record | Server commits before delaying reply for two seconds |
| 5 Insufficient funds | FAILED, no debit, no ledger entries | HTTP 422 and INSUFFICIENT_FUNDS, balances unchanged, failed result replays | Rejection is durable and terminal |
| 6 Rollback | No partial debit and safe original-key retry | Injected 503, original balances intact, lookup 404, retry 201, one final record | Exception occurs after debit and rolls back the transaction |

## Additional executed cases

| Case | Observed result |
|---|---|
| Concurrent overspending | 20 requests, 10 successes, 10 failures, final sender zero |
| 100 simultaneous duplicates | One new settlement, 99 replays, one UUID |
| Key with changed fields | 409 through Redis and database replay paths |
| Redis TTL expiry | Same UUID replays from PostgreSQL after actual cache expiry |
| Authentication / validation | Missing token 401, invalid inputs 422, missing account 404, no records created |
| Redis unavailable | Real connection refusal at test Redis endpoint, one settlement and database replay |
| API process crash before commit | Worker exit 71, no committed payment, balances unchanged, retry creates one settlement |
| API process crash after commit | Worker exit 72 before Redis write, stored payment present, retry replays same settlement |
| Opposite-direction transfers | 40 successes with original final balances and no observed deadlock |
| Database guards | Negative balance and unfinished PROCESSING commit both rejected |

## Browser acceptance

Chromium 134 executed the actual dashboard. All six tests passed. A normal form payment followed by Retry last submitted request returned the same payment ID. The original key survived reload. At 390 pixels, the document did not overflow horizontally. No JavaScript page errors were observed. Screenshots were used internally for layout inspection and are not distributed.

## Evidence and reproduction

- `evidence/pytest-output.txt`: final terminal output, including all 16 case results.
- `evidence/junit.xml`: JUnit test report.
- `evidence/integration-results.json`: expected and actual values for each passed case, with payment IDs, balances and audit snapshots.
- `evidence/browser-results.json`: browser checks and full six-test execution log.
- Run `python scripts/run_tests.py` for isolated integration verification.
- Run `python scripts/browser_verify.py` with the main application running for browser acceptance.

The observed 100-unique-request case took 0.922 seconds in this local environment. It is a bounded correctness exercise, not an SLA or production benchmark.

## Not executed

Docker image build / Compose startup, Windows-specific launchers, database-server power failure, disk corruption, replicated failover and external banking integration were not executed. No such results are claimed. PostgreSQL and Redis were real services, not mocks or SQLite substitutes.

## Debugging history

The initial backend run exposed a keep-alive connection reset after the intentionally injected rollback exception. The API now handles this controlled interruption explicitly and returns a normal 503 response. The final full run passed. Browser startup required the headless shell because UNIX-domain sockets are blocked in the build environment; the final browser run passed.
