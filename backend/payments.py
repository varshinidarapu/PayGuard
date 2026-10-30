"""Atomic settlement. Redis is an optimization; PostgreSQL is the authority."""
import hashlib
import json
import logging
import os
import uuid
from fastapi import HTTPException
from redis import Redis
from redis.exceptions import RedisError
from .config import REDIS_URL, TTL, ALLOW_CRASH_TESTS
from .database import pool

class PaymentInterrupted(RuntimeError):
    pass


log = logging.getLogger('payguard')
cache = Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=.2, socket_timeout=.2)
def fingerprint(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def cache_key(client_id, key):
    return 'payguard:v2:' + hashlib.sha256((client_id + ':' + key).encode()).hexdigest()


def result(row):
    return {k: (str(v) if k == 'id' else v.isoformat() if k.endswith('_at') and v else v)
            for k, v in row.items() if k not in ('client_id', 'request_hash')}


def redis_read(client_id, key):
    try:
        raw = cache.get(cache_key(client_id, key))
        return json.loads(raw) if raw else None
    except (RedisError, ValueError):
        log.warning('Redis unavailable or invalid cache. Falling back to PostgreSQL.')
        return None


def redis_write(client_id, key, hashed, payment):
    try:
        cache.set(cache_key(client_id, key), json.dumps({'hash': hashed, 'payment': payment}), ex=TTL)
    except RedisError:
        log.warning('Redis write failed after database settlement. Result remains durable.')


def process(body, key, client_id, fault=None):
    hashed = fingerprint(body)
    cached = redis_read(client_id, key)
    if cached:
        if cached['hash'] != hashed:
            raise HTTPException(409, 'Idempotency key already belongs to a different request')
        return cached['payment'], True, 'redis'
    payment_id = uuid.uuid4()
    replayed = False
    # A competing insert on the same unique key waits for the first transaction.
    # If that transaction rolls back, this insert proceeds. If it commits, replay it.
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute("SET LOCAL statement_timeout = '10s'")
            # Stable account order prevents cross-transfer deadlocks.
            # Validate FKs before inserting the payment.
            accounts = conn.execute('SELECT * FROM accounts WHERE client_id=%s AND id IN (%s,%s) ORDER BY id FOR UPDATE',
                                    (client_id, body['sender_id'], body['receiver_id'])).fetchall()
            if len(accounts) != 2:
                raise HTTPException(403, 'Both accounts must belong to the authenticated client')
            row = conn.execute('''INSERT INTO payments
                (id,client_id,idempotency_key,request_hash,sender_id,receiver_id,amount,currency,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSING')
                ON CONFLICT (client_id,idempotency_key) DO NOTHING RETURNING *''',
                (payment_id, client_id, key, hashed, body['sender_id'], body['receiver_id'], body['amount'], body['currency'])).fetchone()
            if row is None:
                row = conn.execute('SELECT * FROM payments WHERE client_id=%s AND idempotency_key=%s',
                                   (client_id, key)).fetchone()
                if row['request_hash'] != hashed:
                    raise HTTPException(409, 'Idempotency key already belongs to a different request')
                replayed = True
            else:
                sender = next(a for a in accounts if a['id'] == body['sender_id'])
                if sender['balance'] < body['amount']:
                    row = conn.execute("UPDATE payments SET status='FAILED',failure_code='INSUFFICIENT_FUNDS',completed_at=now() WHERE id=%s RETURNING *", (payment_id,)).fetchone()
                else:
                    conn.execute('UPDATE accounts SET balance=balance-%s WHERE id=%s', (body['amount'], body['sender_id']))
                    if fault == 'rollback':
                        raise PaymentInterrupted('Injected failure after debit, before credit')
                    if fault == 'crash-before-commit' and ALLOW_CRASH_TESTS:
                        os._exit(71)
                    conn.execute('UPDATE accounts SET balance=balance+%s WHERE id=%s', (body['amount'], body['receiver_id']))
                    conn.execute('INSERT INTO ledger_entries(payment_id,account_id,delta) VALUES (%s,%s,%s),(%s,%s,%s)',
                                 (payment_id, body['sender_id'], -body['amount'], payment_id, body['receiver_id'], body['amount']))
                    row = conn.execute("UPDATE payments SET status='SUCCEEDED',completed_at=now() WHERE id=%s RETURNING *", (payment_id,)).fetchone()
        # Only publish a result after the transaction context commits successfully.
    payment = result(row)
    if fault == 'crash-after-commit' and ALLOW_CRASH_TESTS:
        os._exit(72)
    redis_write(client_id, key, hashed, payment)
    log.info('payment=%s status=%s replayed=%s', payment['id'], payment['status'], replayed)
    return payment, replayed, 'postgresql' if replayed else 'new'
