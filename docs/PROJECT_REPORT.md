# PayGuard
## An Idempotent Payment Gateway for Secure and Consistent Transaction Processing

Academic implementation report. Simulated internal INR payments. Verified 30 October 2026.

## Abstract

Payment requests can repeat when a user clicks twice, a client retries, or a successful response is lost. Simultaneous transfers can also corrupt balances if an application reads and writes account values without synchronization. PayGuard implements a local payment gateway simulator that addresses these problems using idempotency keys, Redis result caching, and PostgreSQL transactions with row-level locks. A permanent unique request key prevents a repeated operation from creating another settlement. A single database transaction includes both account changes, a balanced ledger, and the terminal payment status. Safe original-key retries resolve uncertain outcomes after failure. A complete web dashboard demonstrates normal transfers, duplicate requests, concurrent transfers, lost responses, insufficient funds, and rollback. Verification against real PostgreSQL and Redis passed sixteen integration cases, including actual API-process exits before and after commit. Browser acceptance checks passed all six demonstrations. The system demonstrates consistency within one authoritative database and uses no real banking accounts or external financial network.

## 1. Introduction

A payment request and the response acknowledging it travel independently across a network. The server can commit a transfer even when the caller never receives its response. Retrying is necessary for availability, but retrying without a stable operation identity can create an unwanted second payment. Concurrent requests introduce another risk: two requests can both observe an old balance and each spend funds that are no longer available.

PayGuard treats these as one correctness problem. Request identity must survive retries, and settlement must preserve balances and payment records atomically. The project uses established database and API techniques in a compact architecture that is practical to demonstrate and explain at undergraduate level.

## 2. Problem statement

Slide 2 of the supplied presentation identifies three challenges:

1. Duplicate payments from repeated clicks, repeated requests, or network problems.
2. Incorrect balances when multiple transactions execute at the same time.
3. Uncertain payment outcomes after network or server failures.

The proposed implementation combines Redis-assisted idempotency with PostgreSQL locking and transactional settlement. Its acceptance criterion is that repeated or concurrent requests cannot create duplicate committed settlements for one key, corrupt balances, or leave partially applied transfers.

The original slide describes a gap between duplicate handling and concurrency handling. This report interprets that as an educational integration challenge. It does not claim that commercial payment systems universally lack these protections or that combining these established mechanisms is a new research result.

## 3. Existing system and baseline limitations

The conceptual baseline is a payment endpoint that independently reads a balance, subtracts an amount, writes the new value and creates a payment record. Without an operation key, each retry is a new transfer. Without row locking, simultaneous reads can use stale values. Without an encompassing transaction, a debit can persist without its matching credit or payment status.

Disabling the payment button reduces accidental clicks but cannot prevent retries from another client. Redis-only deduplication can lose protection after expiry or outage. Separately committing a payment record and account balances creates an inconsistency window. These baseline weaknesses motivate a combined transaction boundary and permanent request identity. The baseline is a reasoning comparison, not an unsafe implementation deployed or benchmarked in this project.

## 4. Literature review and background

| Source | Relevant concept | Application in PayGuard | Boundary |
|---|---|---|---|
| Ramalingam and Vaswani, Fault Tolerance via Idempotence, POPL 2013 [1] | Idempotence addresses repeated computation after communication and process failures | Stable operation keys allow safe retries | General distributed-systems work rather than this payment implementation |
| PostgreSQL 16, Explicit Locking [2] | Row locks coordinate conflicting operations | Lock both account rows before inspecting funds | Requires careful lock ordering and transactional code |
| PostgreSQL 16, Transaction Isolation [3] | Isolation controls what concurrent statements observe | READ COMMITTED for settlement plus locks, REPEATABLE READ for audit | Isolation levels do not replace application invariants |
| Redis, SET command documentation [4] | Expiring key-value storage | Cache a terminal result and fingerprint with EX TTL | Cache loss cannot authorize a second settlement |
| Stripe, Designing robust and predictable APIs with idempotency, 2017 [5] | Request keys make retried mutating calls safer | Preserve original keys across lost responses | PayGuard is an internal simulator and does not implement Stripe's API contract |

Only traceable primary references are used here. Unverified bibliography entries from the supplied slides were not carried forward. The contribution is an executable integration and demonstration of known reliability principles, with reproducible bounded tests.

## 5. Objectives

- Settle one intended request at most once under a stable operator/key identity.
- Maintain exact nonnegative balances during overlapping requests.
- Commit debit, credit, ledger and payment state together.
- Recover safely from a lost reply or an API-process crash.
- Demonstrate every core problem through a working browser interface.
- Produce reproducible execution evidence and understandable review materials.

## 6. Scope

The project supports three seeded synthetic INR accounts managed by a single authenticated sandbox operator. It supports internal transfers, durable success and insufficient-funds rejection, history, status lookup, a ledger audit and controlled fault injection. The dashboard and API share one service. Redis and PostgreSQL are separate services.

There are no real banking accounts, card details, external settlement calls, currency conversion, refunds, subscriptions, customer onboarding or unrelated AI features. Different idempotency keys intentionally represent different operations. The system does not infer whether two different keys refer to the same purchase.

## 7. Methodology

Requirements were extracted from the supplied problem statement and mapped to executable acceptance criteria. The database model and transaction boundary were designed before interface work. Payment processing was implemented using parameterized queries and deterministic account locking. Redis caching was added without making it the financial authority. A dashboard then exposed the core operations and failure demonstrations.

Verification used a separate test database with freshly seeded accounts for each integration case. Tests submitted real HTTP requests, including concurrent requests and workers that actually exited at controlled transaction boundaries. Browser acceptance checks exercised the finished dashboard. A failing rollback error path found during the first run was corrected before the final successful run. The final report distinguishes executed tests from deployment paths that were not executed.

## 8. System architecture

The browser sends authenticated requests to FastAPI. The API validates inputs and an idempotency key, then consults Redis for a completed result. A cache miss leads to PostgreSQL. The service locks both account rows in increasing ID order, enforces unique request identity, and settles or rejects the request within one transaction. Only after commit does it publish a cache entry and success response.

A bounded psycopg pool limits simultaneous database connections. Lock and statement timeouts avoid unbounded waits. Busy or uncertain outcomes return a retryable 503 message directing the caller to preserve the key. The application serves all frontend HTML, CSS and JavaScript locally.

See ARCHITECTURE.md for the component diagram, entity relationship diagram, transaction walk-through and failure matrix.

## 9. Database design

### Accounts

`id` is the primary key. `name` identifies the synthetic account. `currency` is INR. `opening_balance` establishes the audit baseline and `balance` stores current integer paise. Both values must be nonnegative. The three initial balances are 1,000,000, 500,000 and 250,000 paise, totaling 1,750,000 paise.

### Payments

Each payment has a UUID primary key, operator scope, unique idempotency key within that scope, canonical request hash, sender and receiver foreign keys, positive bounded amount, INR currency, payment status, optional insufficient-funds reason, and timestamps. Sender and receiver must differ. Terminal status and timestamp constraints reject invalid combinations.

### Ledger entries

The composite primary key is `(payment_id, account_id)`. Each successful transfer has exactly two entries: a sender debit equal to negative amount and a receiver credit equal to positive amount. A deferred trigger validates this relationship at commit and rejects a committed PROCESSING payment. A separate trigger makes terminal payments immutable.

### Reconciliation invariants

For every account: `balance = opening_balance + sum(ledger delta)`. Across all accounts: total current money equals total opening money. For each success: two correct zero-sum entries. For each business rejection: zero entries. Audit reads one repeatable snapshot so its own multiple queries do not mix different commit points.

## 10. Module descriptions

| Module | Responsibility |
|---|---|
| backend/config.py | Environment configuration and feature gates |
| backend/models.py | Strict input validation and allowed currency |
| backend/database.py | Bounded PostgreSQL connection pool |
| backend/payments.py | Fingerprints, Redis replay, row locks, unique keys and atomic settlement |
| backend/main.py | Authentication, APIs, error handling, audit, static frontend and fault simulation |
| db/schema.sql | Tables, constraints, commit validation and seeded synthetic accounts |
| frontend/ | Dashboard, transfer form, history, six live checks and database evidence |
| tests/ | Integration, concurrency, outage, crash, validation and constraint verification |
| scripts/ | Configuration, initialization, startup and reproducible verification |

## 11. Implementation details

### Idempotency and Redis

The client generates a key before sending an operation and retains it for retries. The server hashes a sorted canonical JSON representation of sender, receiver, amount and currency. Redis stores the terminal response and hash under an operator-scoped hashed key with a configurable 24-hour default TTL. Matching duplicates replay; mismatched requests return 409. Redis failures fall back to PostgreSQL.

PostgreSQL permanently enforces the unique operator/key pair. If a duplicate reaches the database, the stored request hash must match before replay. The same durable failed result also replays, so later funding does not silently change a previously rejected request into a settlement.

### Concurrency control

Inside the transaction, account rows are selected with `ORDER BY id FOR UPDATE`. Every transfer uses that ordering. The funds check occurs while holding both locks, so competing requests cannot each spend the same old balance. Successful transfers update both balances and append exact ledger entries before reaching terminal status.

### State and failure handling

PROCESSING is deliberately uncommitted. A successful transaction reaches SUCCEEDED; insufficient funds reaches FAILED. A technical error before commit discards all changes and leaves no abandoned payment record. A failure after commit may lose the reply, but retrying the same key returns the original stored result. No external provider side effect exists outside this transaction boundary.

### Security

A generated environment secret authenticates the single sandbox operator. Inputs are strict, SQL parameters are bound, application assets load from the same origin, and CSP restricts script execution. Default host bindings are loopback. Fault injection is explicitly gated, and process-exit faults are disabled on the review server. The app logs payment IDs and outcomes without logging the operator token.

## 12. Testing and results

The final backend run passed **16 integration cases in 5.22 seconds**. All six required scenarios passed. The bounded concurrency case submitted 100 distinct transfers of 1,000 paise each from a 1,000,000-paise sender balance; all settled and the final balance was exactly 900,000 paise. That case completed in 0.922 seconds in this environment. This is one observed local test duration, not a production throughput claim.

One hundred simultaneous requests using one key produced one new settlement and ninety-nine replays. In the overspending case, twenty requests of 100,000 paise competed for 1,000,000 paise; ten settled, ten were rejected, and the sender ended at zero. Real API worker exits before and after commit both recovered to one final settlement after original-key retry. Redis expiry and an unavailable Redis endpoint preserved database deduplication.

Chromium acceptance checks also passed six of six dashboard demonstrations, normal form submission, same-ID retry, persistence of request identity across reload, and a 390-pixel mobile layout with no JavaScript page errors.

Detailed expected/actual outcomes, explanations and machine-readable evidence are in TEST_RESULTS.md and evidence/. Test databases are isolated from the review database.

## 13. Execution environment and limitations

The application executed with Python 3.12.14, FastAPI 0.162.0, PostgreSQL 16.15, Redis 7.0.15 and Chromium 134. Dependencies were installed from the pinned requirements. The local environment denied normal package installation, UNIX user switching and UNIX-domain sockets. PostgreSQL and Redis were therefore extracted as local binaries; a sandbox-only UID-reporting shim allowed PostgreSQL startup, and TCP replaced UNIX sockets. All services, API workers and test clients ran together inside one command environment. The shim is not part of the deliverable and is not needed on an ordinary machine or in Docker.

Docker was unavailable here. The Compose file is supplied for portable startup but its container build was not executed. Windows-specific launcher commands were not executed on Windows. The native Python initialization/startup path and the actual application behavior were executed. PostgreSQL fsync and synchronous commit were left enabled; power loss, corrupted storage, replicated failover and sustained production load were not tested.

The system is an academic sandbox, not a certified payment processor. A database owner can still manually alter underlying records; audit detects inconsistencies, but this is not tamper-proof accounting. Authentication is one operator secret, not individual customer authorization.

## 14. Conclusion

PayGuard implements the three Slide 2 objectives as a working local system. Redis recognizes completed repeated requests, while PostgreSQL provides permanent request uniqueness and atomic balance settlement under ordered row locks. Safe original-key retries recover ambiguous outcomes without creating a second committed payment. The executed integration and browser checks support these claims within the tested internal-transfer scope.

## 15. Future enhancements

Extend merchant-scoped credentials and account ownership enforcement, introduce least-privilege runtime database roles, verify backups and replicated recovery, and add deployment monitoring and rate limits. An external-provider version would need provider-side idempotency, an outbox or durable workflow, and reconciliation for settlements that cannot share a local database transaction. Benchmarking should measure latency percentiles and resource limits under sustained load before claiming production scalability.

## References

[1] G. Ramalingam and K. Vaswani. Fault Tolerance via Idempotence. Principles of Programming Languages (POPL), January 2013. Microsoft Research publication page: https://www.microsoft.com/en-us/research/publication/fault-tolerance-via-idempotence/

[2] PostgreSQL Global Development Group. PostgreSQL 16 Documentation: Explicit Locking. https://www.postgresql.org/docs/16/explicit-locking.html

[3] PostgreSQL Global Development Group. PostgreSQL 16 Documentation: Transaction Isolation. https://www.postgresql.org/docs/16/transaction-iso.html

[4] Redis. SET command documentation. https://redis.io/docs/latest/commands/set/

[5] Brandur Leach. Designing robust and predictable APIs with idempotency. Stripe Engineering, 22 February 2017. https://stripe.com/blog/idempotency

References were checked against primary publication/documentation pages during preparation. The supplied presentation is the requirements source; its personal/institutional details are excluded from generated materials.
