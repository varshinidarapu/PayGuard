import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://payguard:payguard_local_only@127.0.0.1:5432/payguard')
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
API_KEY = os.getenv('API_KEY', '')
DEMO_MODE = os.getenv('DEMO_MODE', 'false').lower() == 'true'
ALLOW_CRASH_TESTS = os.getenv('ALLOW_CRASH_TESTS', 'false').lower() == 'true'
TTL = int(os.getenv('IDEMPOTENCY_TTL_SECONDS', '86400'))
POOL_MAX = int(os.getenv('POOL_MAX_SIZE', '32'))
