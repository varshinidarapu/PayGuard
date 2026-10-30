# PayGuard viva preparation: 30 questions and answers

## 1. What problem does PayGuard solve?
It prevents repeated requests from settling a payment twice, protects balances during concurrent transfers, and lets clients recover safely after interrupted requests. These correspond directly to Slide 2 of the original presentation.

## 2. What is idempotency?
An operation is idempotent when repeating the same intended operation has no additional effect after the first successful application. In PayGuard, repeated requests with the same key and fields return the original payment UUID and do not debit again.

## 3. Why is an ordinary POST payment API vulnerable to duplicates?
Each request can create a new payment unless the server remembers the business operation. A double click or retry after a lost reply can otherwise produce a second debit.

## 4. Who creates the idempotency key?
The client generates a random UUID-based key before the first attempt and preserves it across retries. PayGuard's form retains the last request locally so a page refresh can retry the same key and payload.

## 5. What happens if the same key has a different amount?
PayGuard compares a SHA-256 fingerprint of canonical request fields and returns HTTP 409. Reusing a key for a different operation is an error. The Redis and database replay paths both check the fingerprint.

## 6. What is Redis's role?
Redis stores terminal payment results with request fingerprints for fast duplicate detection and replay. Keys expire after 24 hours by default. Redis never changes account balances.

## 7. Why is Redis alone insufficient?
It can expire, evict or lose keys, and its writes cannot atomically commit PostgreSQL balances. PostgreSQL therefore enforces permanent request uniqueness and owns all financial records.

## 8. What happens when Redis is down?
A short Redis timeout leads to PostgreSQL fallback. A new payment settles through the database transaction, and a repeated request retrieves the stored payment through the unique key. The suite executed this with a genuinely unavailable Redis endpoint.

## 9. What is the difference between a Redis TTL and database key retention?
TTL controls how long the cache retains a result. Database uniqueness lasts as long as the payment record, so cache expiry does not make an old request new. The project does not delete payment records.

## 10. How do you prevent race conditions in balances?
The transaction locks both account rows with SELECT FOR UPDATE, sorted by account ID, then checks funds and updates balances while holding those locks. Competing transfers wait and use the updated balance.

## 11. Why lock accounts in a fixed order?
Two opposite transfers could otherwise lock different rows first and wait on each other. Increasing account ID order prevents that lock-order cycle in this transfer algorithm.

## 12. What isolation level do payment transactions use?
PostgreSQL's default READ COMMITTED. Explicit account row locks protect the balance-dependent decision. The audit separately uses REPEATABLE READ so all its queries observe one coherent snapshot.

## 13. Explain ACID using PayGuard.
Atomicity commits or rolls back debit, credit, ledger and status together. Consistency preserves balance and payment constraints. Isolation protects concurrent account updates with row locks. Durability preserves committed results through PostgreSQL's normal WAL and commit mechanisms, subject to storage configuration and failures outside this test scope.

## 14. What is rollback?
Rollback discards all changes in an uncommitted transaction. PayGuard injects a failure after debit but before credit; neither balance change nor a payment record survives. The original key can then safely retry.

## 15. Why store money as integer paise?
Floating-point numbers cannot exactly represent many decimal fractions. Integer minor units support exact addition, subtraction and equality. INR 100.00 is stored as 10,000 paise.

## 16. What payment states exist?
PROCESSING is internal and uncommitted. The transaction changes it to SUCCEEDED or FAILED before commit. A deferred constraint trigger rejects a committed PROCESSING record, and a trigger blocks later changes to terminal payments.

## 17. Does every technical failure create a FAILED payment?
No. An exception before commit rolls back the whole attempt and leaves no payment row. FAILED is a durable business rejection for insufficient funds. A timeout may occur after successful commit and must be treated as unknown until verified.

## 18. What happens if the API crashes after debit?
If the transaction has not committed, PostgreSQL rolls it back when the connection disappears. The process-crash test exits the worker at that point and verifies unchanged balances before retrying the same key.

## 19. What happens if it crashes after commit but before responding?
The terminal payment and balance updates remain in PostgreSQL. Retrying the original key retrieves that result instead of settling again, even if Redis was never populated.

## 20. How do you distinguish failure from a lost response?
A network error alone cannot prove failure. Query payment status by idempotency key, then retry with that same key if necessary. A 404 during an in-flight transaction also does not prove permanent failure.

## 21. What database tables exist?
Accounts stores names, currency, opening and current balances. Payments stores UUIDs, keys, fingerprints, amount, sender, receiver, timestamps and terminal status. Ledger entries stores the negative sender and positive receiver delta for each success.

## 22. Why maintain a ledger in addition to balances?
The ledger explains balance changes and supports reconciliation. Every success has exactly two entries summing to zero. The audit reconstructs each account's balance from its opening balance plus ledger deltas.

## 23. Which constraints enforce correctness?
Primary and foreign keys, unique operator/key pairs, positive bounded amounts, different sender and receiver, nonnegative balances, valid state/timestamp combinations, one ledger entry per payment/account, deferred payment-to-ledger validation, and terminal-payment immutability.

## 24. How is insufficient balance handled under concurrency?
The funds check occurs after acquiring locks. Once available money is exhausted, later requests create FAILED records without debits. The executed test submitted twenty INR 1,000 transfers against INR 10,000 and observed ten successes and ten rejections, with final sender balance zero.

## 25. What proves duplicate prevention?
Sequential same-key requests returned equal result bodies and one payment record. One hundred simultaneous same-key requests produced one new settlement and ninety-nine replays. The sender was debited only once.

## 26. How are APIs secured in this project?
A random environment-configured Bearer token authorizes the sandbox operator. Strict validation and parameterized SQL protect inputs. Same-origin requests and CSP protect the dashboard. The default server and exposed service ports bind to loopback. No real payment credentials exist.

## 27. Is this customer-level authentication?
No. One sandbox operator owns all three synthetic accounts. It demonstrates payment consistency without an unrelated user-management module. A production system would need merchant/customer authorization and account ownership enforcement.

## 28. Does this achieve exactly-once delivery?
No. HTTP requests and replies may repeat or disappear. The guarantee is at most one committed internal settlement per operator/key while durable database records remain intact. Different keys represent different payment intents and can settle separately.

## 29. How did you verify the implementation?
The suite ran real HTTP requests against FastAPI, PostgreSQL and Redis. Six required scenarios plus edge cases passed. Separate workers actually exited before and after commit. A Chromium browser also exercised the six dashboard tests, form payment, retry, reload recovery and a 390-pixel mobile layout.

## 30. What are the limitations and future improvements?
This is a local internal-transfer simulator. It has no external bank integration, replicated failover or production-scale benchmark. Future work can add provider reconciliation, merchant-scoped credentials, least-privilege DB roles, TLS, monitoring, rate limiting and verified backup recovery without changing the core atomic settlement boundary.

## A concise architecture explanation

“The frontend sends an authenticated request and an idempotency key. Redis can replay a completed result. On a miss, the API starts a PostgreSQL transaction, locks both accounts in ID order, enforces a unique request key, checks funds, and atomically commits the ledger, balances and final status. A failure before commit leaves no partial settlement. A retry after commit reads the original result.”

## Common review traps

- A new key for a retry is a new payment, so do not claim protection across arbitrary different keys.
- Disabling a button improves usability but does not replace server-side idempotency.
- A Redis lock alone cannot prove database settlement or survive key loss.
- A timeout does not mean the payment failed.
- One successful concurrency run demonstrates the tested bound, not unlimited scalability.
- This project applies established techniques together. It does not establish that commercial gateways lack those techniques.
