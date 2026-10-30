import asyncio
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
import psycopg
import pytest
from redis import Redis
from conftest import record, URL, ROOT
from backend.config import API_KEY,DATABASE_URL,REDIS_URL
from backend.payments import cache_key

BODY={'sender_id':1,'receiver_id':2,'amount':10000,'currency':'INR'}

def key():return 'test-'+str(uuid.uuid4())
def pay(c,k=None,body=None,fault=None):
    return c.post('/api/payments',json=body or BODY,headers={'Idempotency-Key':k or key(),**({'X-Demo-Fault':fault} if fault else {})})
def balances(c):return {str(a['id']):a['balance'] for a in c.get('/api/accounts').json()}
def audit(c):
    a=c.get('/api/audit').json();assert a['consistent'];assert a['current_total']==1750000;return a


def test_01_normal_payment(client):
    before=balances(client);r=pay(client);assert r.status_code==201
    p=r.json();assert p['status']=='SUCCEEDED'
    expected={'1':990000,'2':510000,'3':250000};assert balances(client)==expected
    assert client.get('/api/payments/'+p['id']).json()==p
    assert len(client.get('/api/ledger').json())==2
    record('1 Normal payment',{'balances':expected,'payments':1}, {'balances':balances(client),'payment':p,'audit':audit(client)})


def test_02_duplicate_payment(client):
    k=key();a=pay(client,k);b=pay(client,k)
    assert a.status_code==201 and b.status_code==200 and a.json()==b.json()
    assert b.headers['Idempotency-Replayed']=='true' and b.headers['Idempotency-Source']=='redis'
    assert Redis.from_url(REDIS_URL).ttl(cache_key('sandbox-operator',k))>0
    assert audit(client)['stats']['total']==1
    assert balances(client)['1']==990000
    record('2 Duplicate payment',{'payments':1,'sender_balance':990000,'same_result':True}, {'first_status':a.status_code,'repeat_status':b.status_code,'same_result':a.json()==b.json(),'source':b.headers['Idempotency-Source'],'audit':audit(client)})


async def parallel(n, body, same_key=None):
    async with httpx.AsyncClient(trust_env=False, base_url=URL,headers={'Authorization':'Bearer '+API_KEY},timeout=30,limits=httpx.Limits(max_connections=100,max_keepalive_connections=100)) as c:
        return await asyncio.gather(*[c.post('/api/payments',json=body,headers={'Idempotency-Key':same_key or key()}) for _ in range(n)])


def test_03_concurrent_payments(client):
    body={**BODY,'amount':1000};start=time.perf_counter();rs=asyncio.run(parallel(100,body));elapsed=time.perf_counter()-start
    assert all(r.status_code==201 for r in rs),[(r.status_code,r.text) for r in rs if r.status_code!=201]
    assert len({r.json()['id'] for r in rs})==100
    expected={'1':900000,'2':600000,'3':250000};assert balances(client)==expected
    assert audit(client)['stats']['succeeded']==100
    record('3 Concurrent transactions',{'parallel_requests':100,'balances':expected}, {'successful':len(rs),'balances':balances(client),'elapsed_seconds':round(elapsed,3),'audit':audit(client)})


def test_04_lost_response_and_retry(client):
    k=key()
    with pytest.raises(httpx.ReadTimeout):
        client.post('/api/payments',json=BODY,headers={'Idempotency-Key':k,'X-Demo-Fault':'delayed-response'},timeout=.25)
    stored=client.get('/api/payments/by-key/'+k);assert stored.status_code==200
    retry=pay(client,k);assert retry.status_code==200 and retry.json()==stored.json()
    assert audit(client)['stats']['total']==1;assert balances(client)['1']==990000
    record('4 Network timeout and retry',{'timeout':True,'payments':1,'sender_balance':990000},{'client_timeout':True,'retry_replayed':retry.headers['Idempotency-Replayed'],'same_id':retry.json()['id']==stored.json()['id'],'audit':audit(client)})


def test_05_insufficient_balance(client):
    before=balances(client);k=key();r=pay(client,k,{**BODY,'amount':1000001});assert r.status_code==422
    assert r.json()['status']=='FAILED' and r.json()['failure_code']=='INSUFFICIENT_FUNDS'
    again=pay(client,k,{**BODY,'amount':1000001});assert again.json()==r.json() and again.headers['Idempotency-Replayed']=='true'
    assert balances(client)==before and not client.get('/api/ledger').json()
    record('5 Insufficient balance',{'balances_unchanged':True,'status':'FAILED'}, {'balances':balances(client),'response':r.json(),'audit':audit(client)})


def test_06_rollback_consistency(client):
    before=balances(client);k=key();r=pay(client,k,fault='rollback');assert r.status_code==503
    assert balances(client)==before
    assert client.get('/api/payments/by-key/'+k).status_code==404
    assert audit(client)['stats']['total']==0
    after_failure=balances(client);retry=pay(client,k);assert retry.status_code==201
    assert audit(client)['stats']['total']==1
    record('6 Transaction rollback and retry',{'rollback_no_changes':True,'retry_payments':1},{'injected_status':r.status_code,'balances_after_rollback':after_failure,'retry_status':retry.status_code,'audit':audit(client)})


def test_07_concurrent_overspending(client):
    rs=asyncio.run(parallel(20,{**BODY,'amount':100000}))
    assert sum(r.status_code==201 for r in rs)==10
    assert sum(r.status_code==422 for r in rs)==10
    assert balances(client)['1']==0 and balances(client)['2']==1500000
    record('Concurrent overspending',{'succeeded':10,'failed':10,'sender_balance':0},{'succeeded':10,'failed':10,'balances':balances(client),'audit':audit(client)})


def test_08_simultaneous_same_key(client):
    k=key();rs=asyncio.run(parallel(100,BODY,k))
    assert all(r.status_code in (200,201) for r in rs)
    assert len({r.json()['id'] for r in rs})==1
    assert sum(r.status_code==201 for r in rs)==1
    assert balances(client)['1']==990000
    record('100 simultaneous duplicates',{'settlements':1,'replays':99},{'settlements':sum(r.status_code==201 for r in rs),'replays':sum(r.headers['Idempotency-Replayed']=='true' for r in rs),'audit':audit(client)})


def test_09_conflicting_payload(client):
    k=key();assert pay(client,k).status_code==201
    r=pay(client,k,{**BODY,'amount':10001});assert r.status_code==409
    Redis.from_url(REDIS_URL).delete(cache_key('sandbox-operator',k))
    r2=pay(client,k,{**BODY,'amount':10001});assert r2.status_code==409
    assert audit(client)['stats']['total']==1
    record('Key payload mismatch',{'redis_conflict':409,'database_conflict':409},{'redis_conflict':r.status_code,'database_conflict':r2.status_code,'audit':audit(client)})


def test_10_redis_expiry(client):
    k=key();first=pay(client,k);redis=Redis.from_url(REDIS_URL);redis.pexpire(cache_key('sandbox-operator',k),20);time.sleep(.05)
    assert not redis.exists(cache_key('sandbox-operator',k))
    r=pay(client,k);assert r.status_code==200 and r.headers['Idempotency-Source']=='postgresql'
    assert r.json()==first.json() and audit(client)['stats']['total']==1
    record('Redis TTL expiry',{'settlements':1,'fallback':'postgresql'},{'source':r.headers['Idempotency-Source'],'same_result':r.json()==first.json(),'audit':audit(client)})


def test_11_validation_and_auth(client):
    assert httpx.get(trust_env=False, url=URL+'/api/accounts').status_code==401
    tests=[({},BODY),({'Idempotency-Key':'short'},BODY),({'Idempotency-Key':key()},{**BODY,'amount':-1}),({'Idempotency-Key':key()},{**BODY,'amount':1.5}),({'Idempotency-Key':key()},{**BODY,'sender_id':2}),({'Idempotency-Key':key()},{**BODY,'currency':'USD'}),({'Idempotency-Key':key()},{**BODY,'amount':True})]
    codes=[client.post('/api/payments',json=b,headers=h).status_code for h,b in tests];assert codes==[422]*len(tests)
    assert pay(client,body={**BODY,'receiver_id':999}).status_code==403
    assert audit(client)['stats']['total']==0
    record('Authentication and input validation',{'unauthorized':401,'invalid':422,'unauthorized_account':403},{'unauthorized':401,'invalid_statuses':codes,'unauthorized_account':403})


class Worker:
    def __init__(self,**overrides):
        self.env={**os.environ,'DATABASE_URL':DATABASE_URL,'API_KEY':API_KEY,'REDIS_URL':REDIS_URL,'DEMO_MODE':'true',**overrides}
    def __enter__(self):
        self.log=open(ROOT/'evidence/worker.log','a')
        self.p=subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8002'],cwd=ROOT,env=self.env,stdout=self.log,stderr=self.log)
        for _ in range(100):
            try:
                if httpx.get(trust_env=False, url='http://127.0.0.1:8002/api/health',timeout=.5).status_code==200:break
            except httpx.HTTPError:pass
            if self.p.poll() is not None:raise RuntimeError('Test worker failed. See evidence/worker.log')
            time.sleep(.05)
        else:raise RuntimeError('Worker startup timed out')
        self.c=httpx.Client(trust_env=False, base_url='http://127.0.0.1:8002',headers={'Authorization':'Bearer '+API_KEY},timeout=10)
        return self
    def __exit__(self,*args):
        self.c.close()
        if self.p.poll() is None:self.p.terminate()
        self.p.wait(timeout=10);self.log.close()


def test_12_redis_unavailable(client):
    k=key()
    with Worker(REDIS_URL='redis://127.0.0.1:6399/0') as w:
        first=pay(w.c,k);repeat=pay(w.c,k)
        assert first.status_code==201 and repeat.status_code==200 and first.json()==repeat.json()
        assert repeat.headers['Idempotency-Source']=='postgresql'
    record('Redis unavailable',{'settlements':1,'database_fallback':True},{'same_result':True,'audit':audit(client)})


@pytest.mark.parametrize('fault,exit_code,committed',[('crash-before-commit',71,False),('crash-after-commit',72,True)])
def test_13_process_crash(client,fault,exit_code,committed):
    k=key();before=balances(client)
    with Worker(ALLOW_CRASH_TESTS='true') as w:
        with pytest.raises(httpx.HTTPError):pay(w.c,k,fault=fault)
        w.p.wait(timeout=10);assert w.p.returncode==exit_code
    status=client.get('/api/payments/by-key/'+k)
    assert status.status_code==(200 if committed else 404)
    if not committed:assert balances(client)==before
    retry=pay(client,k);assert retry.status_code==(200 if committed else 201)
    assert audit(client)['stats']['total']==1 and balances(client)['1']==990000
    record(f'Actual process {fault}',{'worker_exit':exit_code,'committed_before_retry':committed,'final_settlements':1},{'worker_exit':exit_code,'lookup_status':status.status_code,'retry_status':retry.status_code,'audit':audit(client)})


def test_14_opposite_direction_lock_order(client):
    with ThreadPoolExecutor(max_workers=20) as executor:
        def transfer(i):
            with httpx.Client(trust_env=False, base_url=URL,headers={'Authorization':'Bearer '+API_KEY},timeout=20) as c:
                return pay(c,body={**BODY,'sender_id':1 if i%2==0 else 2,'receiver_id':2 if i%2==0 else 1,'amount':100})
        rs=list(executor.map(transfer,range(40)))
    assert all(r.status_code==201 for r in rs)
    assert balances(client)=={'1':1000000,'2':500000,'3':250000}
    record('Opposite-direction transfers',{'successful':40,'no_deadlock':True,'net_change':0},{'successful':len(rs),'balances':balances(client),'audit':audit(client)})


def test_15_database_constraints(client):
    with psycopg.connect(DATABASE_URL) as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():c.execute('UPDATE accounts SET balance=-1 WHERE id=1')
        with pytest.raises(psycopg.errors.RaiseException):
            with c.transaction():
                c.execute("INSERT INTO payments(id,client_id,idempotency_key,request_hash,sender_id,receiver_id,amount,currency,status) VALUES (%s,'sandbox-operator','unfinished',%s,1,2,100,'INR','PROCESSING')",(uuid.uuid4(),'0'*64))
    record('Database commit guards',{'negative_balance_blocked':True,'unfinished_payment_blocked':True},{'negative_balance_blocked':True,'unfinished_payment_blocked':True,'audit':audit(client)})


def create_tenant(client, suffix=None):
    tenant='tenant-'+(suffix or uuid.uuid4().hex[:12])
    r=client.post('/api/clients',json={'name':'Second Client','client_id':tenant,'key_label':'Test key','expires_in_days':30})
    assert r.status_code==201,r.text
    secret=r.json()['api_key']['secret']
    with psycopg.connect(DATABASE_URL) as c:
        c.execute('INSERT INTO accounts(id,client_id,name,opening_balance,balance) VALUES (%s,%s,%s,50000,50000),(%s,%s,%s,25000,25000)',
                  (101,tenant,'Tenant Wallet',102,tenant,'Tenant Reserve'))
    return tenant,secret


def authed(secret):
    return httpx.Client(trust_env=False,base_url=URL,headers={'Authorization':'Bearer '+secret},timeout=20)


def test_16_multiple_clients_and_ownership(client):
    tenant,secret=create_tenant(client)
    with authed(secret) as other:
        assert {a['id'] for a in other.get('/api/accounts').json()}=={101,102}
        assert pay(other,body={**BODY,'sender_id':1,'receiver_id':2}).status_code==403
        r=pay(other,body={**BODY,'sender_id':101,'receiver_id':102,'amount':1000})
        assert r.status_code==201
        assert client.get('/api/payments/'+r.json()['id']).status_code==404
        assert len(other.get('/api/payments').json())==1
    record('Client isolation',{'owned_accounts_only':True,'foreign_debit':403,'records_private':True},{'client':tenant,'passed':True})


def test_17_api_key_safe_listing_and_revocation(client):
    made=client.post('/api/api-keys',json={'label':'Revocable key','expires_in_days':30}).json()
    assert 'secret' in made
    listed=client.get('/api/api-keys').json(); item=next(k for k in listed if k['id']==made['id'])
    assert 'secret' not in item and item['prefix']==made['prefix'] and item['status']=='ACTIVE'
    assert client.delete('/api/api-keys/'+made['id']).status_code==204
    with authed(made['secret']) as revoked: assert revoked.get('/api/me').status_code==401
    record('Safe key listing and revocation',{'secret_once':True,'revoked_rejected':True},{'passed':True})


def test_18_api_key_expiry(client):
    made=client.post('/api/api-keys',json={'label':'Expiry key','expires_in_days':1}).json()
    with psycopg.connect(DATABASE_URL) as c:c.execute("UPDATE api_keys SET created_at=now()-interval '2 days',expires_at=now()-interval '1 day' WHERE id=%s",(made['id'],))
    with authed(made['secret']) as expired: assert expired.get('/api/me').status_code==401
    item=next(k for k in client.get('/api/api-keys').json() if k['id']==made['id']);assert item['status']=='EXPIRED'
    record('API key expiry',{'expired_rejected':True},{'status':item['status']})


def test_19_rotation_preserves_client_idempotency(client):
    made=client.post('/api/api-keys',json={'label':'Old rotation key','expires_in_days':30}).json(); k=key()
    with authed(made['secret']) as old:
        first=pay(old,k); assert first.status_code==201
        rotated=old.post('/api/api-keys/'+made['id']+'/rotate',json={'label':'Rotated key','expires_in_days':30})
        assert rotated.status_code==201
    with authed(made['secret']) as old: assert old.get('/api/me').status_code==401
    with authed(rotated.json()['secret']) as new:
        retry=pay(new,k);assert retry.status_code==200 and retry.json()['id']==first.json()['id']
        assert retry.headers['Idempotency-Replayed']=='true'
    assert audit(client)['stats']['total']==1
    record('Rotation and idempotency',{'old_rejected':True,'same_settlement':True},{'same_id':True})


def test_20_non_admin_cannot_create_client(client):
    _,secret=create_tenant(client)
    with authed(secret) as other:
        r=other.post('/api/clients',json={'name':'Forbidden','client_id':'forbidden-client','key_label':'Initial key','expires_in_days':30})
        assert r.status_code==403
    record('Client administration authorization',{'non_admin':403},{'status':r.status_code})
