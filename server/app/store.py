import os
from pathlib import Path
from sqlalchemy import create_engine, event

DDL = '''
CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, group_id TEXT NOT NULL, name TEXT NOT NULL, platform TEXT NOT NULL, client_version TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, last_seen_at REAL, revoked_at REAL);
CREATE TABLE IF NOT EXISTS enrollments (code_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL, consumed_at REAL);
CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, group_id TEXT NOT NULL, sender_id TEXT NOT NULL, recipient_id TEXT NOT NULL, client_transfer_id TEXT NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL, name TEXT, mime TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, sensitivity TEXT NOT NULL, batch_id TEXT, origin_device_id TEXT NOT NULL, origin_created_at REAL NOT NULL, requested_ttl INTEGER NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL, upload_deadline REAL NOT NULL, committed_at REAL, expires_at REAL, auto_action_until REAL, received_at REAL, payload_deleted_at REAL, retry_count INTEGER NOT NULL DEFAULT 0, UNIQUE(sender_id, client_transfer_id));
CREATE INDEX IF NOT EXISTS ix_inbox ON transfers(recipient_id,state,created_at,id);
CREATE TABLE IF NOT EXISTS receipts (transfer_id TEXT PRIMARY KEY, recipient_id TEXT NOT NULL, received_at REAL NOT NULL);
'''

class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('DATA_DIR', 'data')).resolve()
        for d in ('payloads', 'tmp'):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.engine = create_engine('sqlite:///' + str(self.root / 'app.db'), connect_args={'timeout': 10})
        @event.listens_for(self.engine, 'connect')
        def pragmas(db, _):
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=10000')
        with self.engine.begin() as c:
            for sql in DDL.split(';'):
                if sql.strip(): c.exec_driver_sql(sql)

    def transaction(self):
        return Transaction(self.engine)

    def path(self, tid): return self.root / 'payloads' / tid

class Transaction:
    def __init__(self, engine): self.engine = engine
    def __enter__(self):
        self.c = self.engine.connect()
        self.c.exec_driver_sql('BEGIN IMMEDIATE')
        return self
    def execute(self, sql, params=()): return self.c.exec_driver_sql(sql, params)
    def one(self, sql, params=()):
        r = self.execute(sql, params).mappings().first()
        return dict(r) if r else None
    def all(self, sql, params=()): return [dict(r) for r in self.execute(sql, params).mappings()]
    def __exit__(self, typ, value, tb):
        try: self.c.rollback() if typ else self.c.commit()
        finally: self.c.close()
