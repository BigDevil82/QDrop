import argparse
import hashlib
import secrets
import time
from .store import Store

def main():
    p = argparse.ArgumentParser(description='Private local QDrop administration')
    p.add_argument('command', choices=['enroll', 'devices', 'revoke', 'backup'])
    p.add_argument('value', nargs='?')
    a = p.parse_args()
    s = Store()
    with s.transaction() as db:
        if a.command == 'enroll':
            code = secrets.token_urlsafe(24)
            db.execute('INSERT INTO enrollments VALUES(?,?,NULL)', (hashlib.sha256(code.encode()).hexdigest(), time.time()+600))
            print(code)  # Only explicit local CLI prints this one-time secret.
        elif a.command == 'devices':
            for d in db.all('SELECT id,name,platform,revoked_at FROM devices'): print(d)
        elif a.command == 'revoke':
            if not a.value: p.error('device UUID required')
            db.execute('UPDATE devices SET revoked_at=? WHERE id=?', (time.time(), a.value))
            db.execute("UPDATE transfers SET state='CANCELLED' WHERE (sender_id=? OR recipient_id=?) AND state IN ('CREATED','UPLOADED','READY')", (a.value,a.value))
        elif a.command == 'backup':
            if not a.value: p.error('backup destination required')
    if a.command == 'backup':
        import sqlite3
        with sqlite3.connect(s.root/'app.db') as src, sqlite3.connect(a.value) as dst: src.backup(dst)

if __name__ == '__main__': main()
