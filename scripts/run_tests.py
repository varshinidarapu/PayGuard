"""Run integration suite against an isolated payguard_test database, never review data."""
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import DATABASE_URL,ROOT
(ROOT/'evidence').mkdir(parents=True, exist_ok=True)
parts=conninfo_to_dict(DATABASE_URL)
parts['dbname']=parts['dbname']+'_test' if not parts['dbname'].endswith('_test') else parts['dbname']
test_url=make_conninfo(**parts)
# Role needs CREATEDB for this command. Docker's initial role has it.
with psycopg.connect(DATABASE_URL,autocommit=True) as c:
    found=c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(parts['dbname'],)).fetchone()
    if not found:c.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(parts['dbname'])))
env={**os.environ,'DATABASE_URL':test_url,'DEMO_MODE':'true','TEST_API_URL':'http://127.0.0.1:8001'}
subprocess.run([sys.executable,'scripts/init_db.py'],cwd=ROOT,env=env,check=True)
with open(ROOT/'evidence/test-server.log','w') as log:
    server=subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8001'],cwd=ROOT,env=env,stdout=log,stderr=log)
    try:
        for _ in range(100):
            try:
                if httpx.get(trust_env=False, url='http://127.0.0.1:8001/api/health',timeout=.5).status_code==200:break
            except httpx.HTTPError:pass
            if server.poll() is not None:raise RuntimeError('Test API exited. See evidence/test-server.log')
            time.sleep(.1)
        else:raise RuntimeError('Test API startup timed out')
        completed=subprocess.run([sys.executable,'-m','pytest','tests','-v','--junitxml=evidence/junit.xml'],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (ROOT/'evidence/pytest-output.txt').write_text(completed.stdout)
        print(completed.stdout)
        code=completed.returncode
    finally:
        server.terminate();server.wait(timeout=10)
sys.exit(code)
