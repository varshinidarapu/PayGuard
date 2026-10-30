"""Create a local secret once. Never overwrite an existing environment file."""
import secrets
from pathlib import Path
root = Path(__file__).resolve().parents[1]
p = root / '.env'
if not p.exists():
    text = (root / '.env.example').read_text().replace('replace-with-a-long-random-secret', secrets.token_urlsafe(32))
    p.write_text(text)
    p.chmod(0o600)
    print('Created .env with a random API_KEY. Keep it private.')
else:
    print('Using existing .env.')
