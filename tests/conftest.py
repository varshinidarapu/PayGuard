"""Integration tests require a dedicated *_test database and running test API."""
import json
import os
import sys
from pathlib import Path
import pytest
import psycopg
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import API_KEY, DATABASE_URL

URL=os.getenv('TEST_API_URL','http://127.0.0.1:8001')
RESULTS=[]

def record(name, expected, actual):
    RESULTS.append({'test':name,'status':'PASS','expected':expected,'actual':actual})

@pytest.fixture(autouse=True)
def clean_test_database():
    # An explicit database name guard prevents accidental deletion of review data.
    from psycopg.conninfo import conninfo_to_dict
    assert conninfo_to_dict(DATABASE_URL)['dbname'].endswith('_test'), 'Tests require a dedicated *_test database'
    with psycopg.connect(DATABASE_URL) as c:
        c.execute('TRUNCATE ledger_entries,payments,accounts CASCADE')
        c.execute((ROOT/'db/schema.sql').read_text())
    yield

@pytest.fixture
def client():
    with httpx.Client(trust_env=False, base_url=URL,headers={'Authorization':'Bearer '+API_KEY},timeout=20) as c:
        yield c

@pytest.fixture(scope='session',autouse=True)
def save_results():
    yield
    (ROOT/'evidence/integration-results.json').write_text(json.dumps(RESULTS,indent=2))
