import asyncio
import hmac
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
from .models import PaymentRequest
from .payments import process, cache, result, CLIENT_ID, PaymentInterrupted

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('payguard')

@asynccontextmanager
async def lifespan(app):
    if len(API_KEY) < 24:
        raise RuntimeError('Set API_KEY to at least 24 characters in .env. Run scripts/configure.py.')
    pool.open()
    pool.wait(timeout=15)
    yield
    pool.close()

app = FastAPI(title='PayGuard', version='1.0.0', description='Simulated INR transfers. Amounts are integer paise.', lifespan=lifespan)


def authorize(authorization: str = Header(default='')):
    if not hmac.compare_digest(authorization, 'Bearer ' + API_KEY):
        raise HTTPException(401, 'Valid sandbox operator Bearer token required', headers={'WWW-Authenticate': 'Bearer'})


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


@app.post('/api/payments', dependencies=[Depends(authorize)])
async def create_payment(body: PaymentRequest,
                         idempotency_key: str = Header(default='', alias='Idempotency-Key'),
                         x_demo_fault: str | None = Header(default=None)):
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
        payment, replay, source = await run_in_threadpool(process, body.model_dump(), idempotency_key, x_demo_fault)
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


@app.get('/api/accounts', dependencies=[Depends(authorize)])
def accounts():
    with pool.connection() as c:
        return c.execute('SELECT * FROM accounts ORDER BY id').fetchall()


@app.get('/api/payments', dependencies=[Depends(authorize)])
def payments(limit: int = 100):
    if not 1 <= limit <= 500:
        raise HTTPException(422, 'Limit must be between 1 and 500')
    with pool.connection() as c:
        rows = c.execute('SELECT * FROM payments WHERE client_id=%s ORDER BY created_at DESC,id DESC LIMIT %s', (CLIENT_ID, limit)).fetchall()
        return [result(r) for r in rows]


@app.get('/api/payments/by-key/{key}', dependencies=[Depends(authorize)])
def by_key(key: str):
    with pool.connection() as c:
        row = c.execute('SELECT * FROM payments WHERE client_id=%s AND idempotency_key=%s', (CLIENT_ID,key)).fetchone()
        if row is None:
            raise HTTPException(404, 'No committed payment for this key. An in-flight request may still finish. Retry the SAME key.')
        return result(row)


@app.get('/api/payments/{payment_id}', dependencies=[Depends(authorize)])
def payment_by_id(payment_id: UUID):
    with pool.connection() as c:
        row = c.execute('SELECT * FROM payments WHERE client_id=%s AND id=%s', (CLIENT_ID,payment_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Payment not found')
        return result(row)


@app.get('/api/ledger', dependencies=[Depends(authorize)])
def ledger():
    with pool.connection() as c:
        return c.execute('SELECT payment_id::text,account_id,delta FROM ledger_entries ORDER BY payment_id,account_id LIMIT 1000').fetchall()


@app.get('/api/audit', dependencies=[Depends(authorize)])
def audit():
    # One consistent snapshot prevents a payment committing between audit queries.
    with pool.connection() as c:
        with c.transaction():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = c.execute('''SELECT a.id,a.name,a.opening_balance,a.balance,
                (a.opening_balance+COALESCE(sum(l.delta),0))::bigint AS expected_balance
                FROM accounts a LEFT JOIN ledger_entries l ON a.id=l.account_id
                GROUP BY a.id ORDER BY a.id''').fetchall()
            bad = c.execute('''SELECT count(*) AS n FROM payments p LEFT JOIN
                (SELECT payment_id,count(*) n,sum(delta) total FROM ledger_entries GROUP BY payment_id) l ON l.payment_id=p.id
                WHERE p.status='PROCESSING' OR
                (p.status='SUCCEEDED' AND (COALESCE(l.n,0)<>2 OR l.total<>0)) OR
                (p.status='FAILED' AND COALESCE(l.n,0)<>0)''').fetchone()['n']
            stats = c.execute("SELECT count(*) total,count(*) FILTER (WHERE status='SUCCEEDED') succeeded,count(*) FILTER (WHERE status='FAILED') failed,COALESCE(sum(amount) FILTER (WHERE status='SUCCEEDED'),0)::bigint volume FROM payments").fetchone()
    opening = sum(a['opening_balance'] for a in rows)
    current = sum(a['balance'] for a in rows)
    return {'consistent':bad == 0 and opening == current and all(a['balance']==a['expected_balance'] for a in rows),
            'opening_total':opening, 'current_total':current, 'invalid_payments':bad, 'accounts':rows, 'stats':stats}


@app.get('/')
def index():
    return FileResponse(ROOT / 'frontend/index.html')

app.mount('/static', StaticFiles(directory=ROOT/'frontend'), name='static')
