import asyncio
import logging
import re
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from psycopg import OperationalError, errors
from psycopg_pool import PoolTimeout
from redis.exceptions import RedisError
from .config import ROOT, API_KEY, DEMO_MODE, ALLOW_CRASH_TESTS
from .database import pool
from .models import PaymentRequest, KeyCreate, ClientCreate
from .payments import process, cache, result, PaymentInterrupted
from .auth import ClientIdentity, authenticate, create_key, ensure_bootstrap_key

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('payguard')

@asynccontextmanager
async def lifespan(app):
    if len(API_KEY) < 24:
        raise RuntimeError('Set API_KEY to at least 24 characters in .env. Run scripts/configure.py.')
    pool.open()
    pool.wait(timeout=15)
    with pool.connection() as conn:
        ensure_bootstrap_key(conn)
    yield
    pool.close()

app = FastAPI(title='PayGuard', version='1.0.0', description='Simulated INR transfers. Amounts are integer paise.', lifespan=lifespan)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'" if not request.url.path.startswith('/docs') else "default-src 'self' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' https://fastapi.tiangolo.com"
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(Exception)
async def unexpected(request, exc):
    log.exception('Request failed path=%s', request.url.path, exc_info=exc)
    return JSONResponse({'detail': 'Request interrupted. Outcome may be unknown. Query status or retry with the SAME idempotency key.'}, status_code=503)


@app.get('/api/health')
def health():
    try:
        with pool.connection() as c:
            c.execute('SELECT 1')
    except Exception:
        return JSONResponse({'database':'down', 'redis':'unknown'}, status_code=503)
    try:
        cache.ping()
        redis_status = 'up'
    except RedisError:
        redis_status = 'down (database fallback active)'
    return {'database':'up', 'redis':redis_status, 'demo_mode':DEMO_MODE, 'currency':'INR'}


@app.post('/api/payments')
async def create_payment(body: PaymentRequest,
                         idempotency_key: str = Header(default='', alias='Idempotency-Key'),
                         x_demo_fault: str | None = Header(default=None),
                         client: ClientIdentity = Depends(authenticate)):
    if not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}', idempotency_key):
        raise HTTPException(422, 'Idempotency-Key must be 8-128 ASCII letters, digits, dots, underscores, colons or hyphens')
    if x_demo_fault:
        if not DEMO_MODE:
            raise HTTPException(403, 'Fault injection disabled')
        allowed = {'rollback', 'delayed-response'}
        if ALLOW_CRASH_TESTS:
            allowed |= {'crash-before-commit','crash-after-commit'}
        if x_demo_fault not in allowed:
            raise HTTPException(422, 'Unknown or disabled fault injection')
    try:
        payment, replay, source = await run_in_threadpool(process, body.model_dump(), idempotency_key, client.id, x_demo_fault)
    except PaymentInterrupted:
        log.warning('Injected transaction interruption rolled back')
        raise HTTPException(503, 'Injected failure. Transaction rolled back. Retry with the SAME idempotency key.')
    except (OperationalError, PoolTimeout, errors.LockNotAvailable, errors.QueryCanceled):
        log.exception('Database unavailable or busy')
        raise HTTPException(503, 'Database busy or connection lost. Retry with the SAME idempotency key.')
    if x_demo_fault == 'delayed-response':
        # Commit has completed. A client timeout now models a lost success response.
        await asyncio.sleep(2)
    code = 200 if replay else 201
    if payment['status'] == 'FAILED':
        code = 422
    return JSONResponse(payment, status_code=code,
                        headers={'Idempotency-Replayed': str(replay).lower(), 'Idempotency-Source':source})


@app.get('/api/me')
def me(client: ClientIdentity = Depends(authenticate)):
    return {'id':client.id,'name':client.name,'is_admin':client.is_admin,'key_id':client.key_id}


@app.get('/api/accounts')
def accounts(client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        return c.execute('SELECT id,name,currency,opening_balance,balance FROM accounts WHERE client_id=%s ORDER BY id',(client.id,)).fetchall()


@app.get('/api/payments')
def payments(limit: int = 100, client: ClientIdentity = Depends(authenticate)):
    if not 1 <= limit <= 500:
        raise HTTPException(422, 'Limit must be between 1 and 500')
    with pool.connection() as c:
        rows = c.execute('SELECT * FROM payments WHERE client_id=%s ORDER BY created_at DESC,id DESC LIMIT %s', (client.id, limit)).fetchall()
        return [result(r) for r in rows]


@app.get('/api/payments/by-key/{key}')
def by_key(key: str, client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        row = c.execute('SELECT * FROM payments WHERE client_id=%s AND idempotency_key=%s', (client.id,key)).fetchone()
        if row is None:
            raise HTTPException(404, 'No committed payment for this key. An in-flight request may still finish. Retry the SAME key.')
        return result(row)


@app.get('/api/payments/{payment_id}')
def payment_by_id(payment_id: UUID, client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        row = c.execute('SELECT * FROM payments WHERE client_id=%s AND id=%s', (client.id,payment_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Payment not found')
        return result(row)


@app.get('/api/ledger')
def ledger(client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        return c.execute('''SELECT l.payment_id::text,l.account_id,l.delta FROM ledger_entries l
            JOIN payments p ON p.id=l.payment_id WHERE p.client_id=%s
            ORDER BY l.payment_id,l.account_id LIMIT 1000''',(client.id,)).fetchall()


@app.get('/api/audit')
def audit(client: ClientIdentity = Depends(authenticate)):
    # One consistent snapshot prevents a payment committing between audit queries.
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = c.execute('''SELECT a.id,a.name,a.opening_balance,a.balance,
                (a.opening_balance+COALESCE(sum(l.delta),0))::bigint AS expected_balance
                FROM accounts a LEFT JOIN ledger_entries l ON a.id=l.account_id
                WHERE a.client_id=%s GROUP BY a.id ORDER BY a.id''',(client.id,)).fetchall()
            bad = c.execute('''SELECT count(*) AS n FROM payments p LEFT JOIN
                (SELECT payment_id,count(*) n,sum(delta) total FROM ledger_entries GROUP BY payment_id) l ON l.payment_id=p.id
                WHERE p.client_id=%s AND (p.status='PROCESSING' OR
                (p.status='SUCCEEDED' AND (COALESCE(l.n,0)<>2 OR l.total<>0)) OR
                (p.status='FAILED' AND COALESCE(l.n,0)<>0))''',(client.id,)).fetchone()['n']
            stats = c.execute("SELECT count(*) total,count(*) FILTER (WHERE status='SUCCEEDED') succeeded,count(*) FILTER (WHERE status='FAILED') failed,COALESCE(sum(amount) FILTER (WHERE status='SUCCEEDED'),0)::bigint volume FROM payments WHERE client_id=%s",(client.id,)).fetchone()
    opening = sum(a['opening_balance'] for a in rows)
    current = sum(a['balance'] for a in rows)
    return {'consistent':bad == 0 and opening == current and all(a['balance']==a['expected_balance'] for a in rows),
            'opening_total':opening, 'current_total':current, 'invalid_payments':bad, 'accounts':rows, 'stats':stats}


@app.get('/api/api-keys')
def list_api_keys(client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        return c.execute('''SELECT id::text,client_id,prefix,label,expires_at,revoked_at,created_at,last_used_at,
            CASE WHEN revoked_at IS NOT NULL THEN 'REVOKED' WHEN expires_at IS NOT NULL AND expires_at<=now() THEN 'EXPIRED' ELSE 'ACTIVE' END status
            FROM api_keys WHERE client_id=%s ORDER BY created_at DESC''',(client.id,)).fetchall()


@app.post('/api/api-keys', status_code=201)
def add_api_key(body: KeyCreate, client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        return create_key(c,client.id,body.label,body.expires_in_days)


@app.post('/api/api-keys/{key_id}/rotate', status_code=201)
def rotate_api_key(key_id: UUID, body: KeyCreate, client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        with c.transaction():
            old=c.execute('SELECT id FROM api_keys WHERE id=%s AND client_id=%s AND revoked_at IS NULL',(key_id,client.id)).fetchone()
            if not old: raise HTTPException(404,'Active API key not found')
            c.execute('UPDATE api_keys SET revoked_at=now() WHERE id=%s',(key_id,))
            return create_key(c,client.id,body.label,body.expires_in_days)


@app.delete('/api/api-keys/{key_id}', status_code=204)
def revoke_api_key(key_id: UUID, client: ClientIdentity = Depends(authenticate)):
    with pool.connection() as c:
        row=c.execute('UPDATE api_keys SET revoked_at=COALESCE(revoked_at,now()) WHERE id=%s AND client_id=%s RETURNING id',(key_id,client.id)).fetchone()
        if not row: raise HTTPException(404,'API key not found')


@app.post('/api/clients', status_code=201)
def add_client(body: ClientCreate, client: ClientIdentity = Depends(authenticate)):
    if not client.is_admin: raise HTTPException(403,'Administrator client required')
    with pool.connection() as c:
        with c.transaction():
            try:
                c.execute('INSERT INTO clients(id,name) VALUES (%s,%s)',(body.client_id,body.name))
            except errors.UniqueViolation:
                raise HTTPException(409,'Client ID already exists')
            created=create_key(c,body.client_id,body.key_label,body.expires_in_days)
    return {'client':{'id':body.client_id,'name':body.name},'api_key':created}


@app.get('/')
def index():
    return FileResponse(ROOT / 'frontend/index.html')

app.mount('/static', StaticFiles(directory=ROOT/'frontend'), name='static')
