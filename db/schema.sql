CREATE TABLE IF NOT EXISTS accounts (
 id integer PRIMARY KEY,
 name varchar(60) NOT NULL,
 currency char(3) NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
 opening_balance bigint NOT NULL CHECK (opening_balance >= 0),
 balance bigint NOT NULL CHECK (balance >= 0)
);
CREATE TABLE IF NOT EXISTS payments (
 id uuid PRIMARY KEY,
 client_id text NOT NULL,
 idempotency_key varchar(128) NOT NULL,
 request_hash char(64) NOT NULL,
 sender_id integer NOT NULL REFERENCES accounts(id),
 receiver_id integer NOT NULL REFERENCES accounts(id),
 amount bigint NOT NULL CHECK (amount > 0 AND amount <= 100000000),
 currency char(3) NOT NULL CHECK (currency = 'INR'),
 status varchar(12) NOT NULL CHECK (status IN ('PROCESSING','SUCCEEDED','FAILED')),
 failure_code text,
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 UNIQUE (client_id,idempotency_key),
 CHECK (sender_id <> receiver_id),
 CHECK ((status='PROCESSING' AND completed_at IS NULL AND failure_code IS NULL)
 OR (status='SUCCEEDED' AND completed_at IS NOT NULL AND failure_code IS NULL)
 OR (status='FAILED' AND completed_at IS NOT NULL AND failure_code='INSUFFICIENT_FUNDS'))
);
CREATE INDEX IF NOT EXISTS payments_created_idx ON payments (created_at DESC);
CREATE TABLE IF NOT EXISTS ledger_entries (
 payment_id uuid NOT NULL REFERENCES payments(id),
 account_id integer NOT NULL REFERENCES accounts(id),
 delta bigint NOT NULL CHECK (delta <> 0),
 PRIMARY KEY(payment_id,account_id)
);
-- At commit, terminal status and exact debit/credit entries must agree.
CREATE OR REPLACE FUNCTION validate_payment_commit() RETURNS trigger AS $$
DECLARE p payments%ROWTYPE; n integer; total numeric; good integer;
BEGIN
 SELECT * INTO p FROM payments WHERE id=NEW.id;
 SELECT count(*),COALESCE(sum(delta),0),count(*) FILTER (WHERE
   (account_id=p.sender_id AND delta=-p.amount) OR
   (account_id=p.receiver_id AND delta=p.amount))
 INTO n,total,good FROM ledger_entries WHERE payment_id=p.id;
 IF p.status='PROCESSING' OR (p.status='SUCCEEDED' AND (n<>2 OR total<>0 OR good<>2))
 OR (p.status='FAILED' AND n<>0) THEN
   RAISE EXCEPTION 'Payment and ledger invariant violation';
 END IF;
 RETURN NULL;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payment_commit_guard ON payments;
CREATE CONSTRAINT TRIGGER payment_commit_guard AFTER INSERT OR UPDATE ON payments
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_payment_commit();
CREATE OR REPLACE FUNCTION forbid_terminal_change() RETURNS trigger AS $$
BEGIN
 IF OLD.status IN ('SUCCEEDED','FAILED') THEN
   RAISE EXCEPTION 'Terminal payments are immutable';
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS payment_terminal_guard ON payments;
CREATE TRIGGER payment_terminal_guard BEFORE UPDATE OR DELETE ON payments
 FOR EACH ROW EXECUTE FUNCTION forbid_terminal_change();
-- Seed amounts are integer paise: INR 10,000 / 5,000 / 2,500.
INSERT INTO accounts(id,name,opening_balance,balance) VALUES
 (1,'Sandbox Wallet',1000000,1000000),
 (2,'Demo Merchant',500000,500000),
 (3,'Reserve Wallet',250000,250000)
ON CONFLICT(id) DO NOTHING;
