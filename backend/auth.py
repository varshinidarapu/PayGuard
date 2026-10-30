"""Database-backed client API keys. Raw secrets are never stored."""
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException
from .config import API_KEY
from .database import pool

@dataclass(frozen=True)
class ClientIdentity:
    id: str
    name: str
    is_admin: bool
    key_id: str

def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

def key_prefix(secret: str) -> str:
    return secret[:14]

def new_secret() -> str:
    return 'pg_live_' + secrets.token_urlsafe(32)

def expiry(days: int | None):
    return datetime.now(timezone.utc) + timedelta(days=days) if days else None

def ensure_bootstrap_key(conn) -> None:
    """Make the configured legacy key the initial admin key without exposing it."""
    conn.execute("INSERT INTO clients(id,name,is_admin) VALUES ('sandbox-operator','PayGuard Sandbox',true) ON CONFLICT(id) DO NOTHING")
    if API_KEY:
        conn.execute('''INSERT INTO api_keys(id,client_id,key_hash,prefix,label)
            VALUES (%s,'sandbox-operator',%s,%s,'Environment bootstrap key')
            ON CONFLICT(key_hash) DO NOTHING''', (uuid.uuid4(), hash_secret(API_KEY), key_prefix(API_KEY)))

def authenticate(authorization: str = Header(default='')) -> ClientIdentity:
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Valid client API key required', headers={'WWW-Authenticate':'Bearer'})
    digest = hash_secret(authorization[7:])
    with pool.connection() as conn:
        row = conn.execute('''SELECT k.id key_id,c.id,c.name,c.is_admin
            FROM api_keys k JOIN clients c ON c.id=k.client_id
            WHERE k.key_hash=%s AND k.revoked_at IS NULL
              AND (k.expires_at IS NULL OR k.expires_at>now())''', (digest,)).fetchone()
        if row:
            conn.execute('UPDATE api_keys SET last_used_at=now() WHERE id=%s', (row['key_id'],))
    if not row:
        raise HTTPException(401, 'API key is invalid, expired or revoked', headers={'WWW-Authenticate':'Bearer'})
    return ClientIdentity(str(row['id']), row['name'], row['is_admin'], str(row['key_id']))

def create_key(conn, client_id: str, label: str, expires_in_days: int | None):
    secret = new_secret()
    row = conn.execute('''INSERT INTO api_keys(id,client_id,key_hash,prefix,label,expires_at)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,client_id,prefix,label,expires_at,created_at''',
        (uuid.uuid4(),client_id,hash_secret(secret),key_prefix(secret),label,expiry(expires_in_days))).fetchone()
    return {**row, 'id':str(row['id']), 'secret':secret}
