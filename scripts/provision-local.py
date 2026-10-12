"""Explicit local-only debug provisioning. Writes ephemeral secrets only to ignored .tools.
Android enrollment is consumed by the on-device instrumentation test.
"""
import hashlib, json, sys, time, uuid
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from app.store import Store
s=Store(ROOT/'data')
codes=[str(uuid.uuid4()),str(uuid.uuid4())]
with s.transaction() as db:
    for code in codes:db.execute('INSERT INTO enrollments VALUES(?,?,NULL)',(hashlib.sha256(code.encode()).hexdigest(),time.time()+600))
with httpx.Client(base_url='http://127.0.0.1:8000') as c:
    r=c.post('/v1/enroll',json=dict(code=codes[0],device_name='Windows 本地联调',platform='windows',client_version='0.1.0'));r.raise_for_status();j=r.json()
(ROOT/'.tools/windows-local-config.json').write_text(json.dumps(dict(BaseUrl='http://127.0.0.1:8000',Token=j['token'],DeviceId=j['device_id'],Directory=str(ROOT/'artifacts/received'),AutoCopy=True,AutoOpen=True)),encoding='utf-8')
(ROOT/'.tools/android-code.txt').write_text(codes[1],encoding='utf-8')
s.engine.dispose()
print('Local debug enrollment/config files prepared (credentials omitted).')
