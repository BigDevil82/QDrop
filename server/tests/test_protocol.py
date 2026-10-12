import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app.main import create_app, digest, stamp

@pytest.fixture
def pair(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        devices=[]
        for name,platform in [('phone','android'),('pc','windows'),('other','android')]:
            code=str(uuid.uuid4())
            with app.state.store.transaction() as db:db.execute('INSERT INTO enrollments VALUES(?,?,NULL)',(digest(code.encode()),time.time()+600))
            response=client.post('/v1/enroll',json=dict(code=code,device_name=name,platform=platform,client_version='test'))
            assert response.status_code==200,response.text
            devices.append(response.json())
        yield app,client,devices

def header(d): return {'Authorization':'Bearer '+d['token']}
def draft(target,body=b'hello',**kwargs):
    return dict(client_transfer_id=str(uuid.uuid4()),recipient_device_id=target['device_id'],kind='file',name='../../中文.txt',mime='text/plain',size=len(body),sha256=hashlib.sha256(body).hexdigest(),origin_created_at=stamp(time.time()),**kwargs)
def send(client,sender,receiver,body=b'hello',**kwargs):
    data=draft(receiver,body,**kwargs);h=header(sender)
    r=client.post('/v1/transfers',json=data,headers=h);assert r.status_code==200,r.text
    tid=r.json()['id']
    assert client.put(f'/v1/transfers/{tid}/content',content=body,headers=h).status_code==200
    r=client.post(f'/v1/transfers/{tid}/commit',headers=h);assert r.status_code==200,r.text
    return tid,data

def test_bidirectional_idempotency_and_authorization(pair):
    app,c,(a,b,other)=pair
    for sender,receiver in [(a,b),(b,a)]:
        tid,data=send(c,sender,receiver)
        assert c.post('/v1/transfers',json=data,headers=header(sender)).json()['id']==tid
        changed={**data,'name':'different'}
        assert c.post('/v1/transfers',json=changed,headers=header(sender)).status_code==409
        assert c.get(f'/v1/transfers/{tid}/content',headers=header(sender)).status_code==403
        assert c.get(f'/v1/transfers/{tid}/content',headers=header(other)).status_code==403
        assert c.post(f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(other)).status_code==403
        assert c.get(f'/v1/transfers/{tid}/content',headers=header(receiver)).content==b'hello'
        for _ in range(2):assert c.post(f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(receiver)).json()['state']=='RECEIVED'
        assert c.post(f'/v1/transfers/{tid}/cancel',headers=header(sender)).status_code==409

def test_zero_bytes_unknown_mismatch_retry(pair):
    _,c,(a,b,_)=pair
    tid,data=send(c,a,b,b'')
    assert c.get(f'/v1/transfers/{tid}/content',headers=header(b)).content==b''
    data=draft(b)
    tid=c.post('/v1/transfers',json=data,headers=header(a)).json()['id']
    assert c.put(f'/v1/transfers/{tid}/content',content=b'bad',headers=header(a)).status_code==422
    assert c.put(f'/v1/transfers/{tid}/content',content=b'123456',headers=header(a)).status_code==413
    assert c.put(f'/v1/transfers/{tid}/content',content=b'hello',headers=header(a)).status_code==200
    assert c.post(f'/v1/transfers/{tid}/commit',headers=header(a)).status_code==200
    assert c.put(f'/v1/transfers/{tid}/content',content=b'changed',headers=header(a)).status_code==200
    assert c.get(f'/v1/transfers/{tid}/content',headers=header(b)).content==b'hello'

def test_restart_offline_lost_events_and_lost_ack(pair):
    app,c,(a,b,_)=pair
    tid,data=send(c,a,b)
    assert c.get('/v1/inbox',headers=header(b)).json()['items'][0]['id']==tid
    assert c.get(f'/v1/transfers/{tid}/content',headers=header(b)).content==b'hello'
    # No ACK and no event consumption, new app instance reads actual persisted SQLite.
    reboot=create_app(app.state.store.root)
    with TestClient(reboot) as r:
        assert r.get('/v1/inbox',headers=header(b)).json()['items'][0]['id']==tid
        assert r.post(f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(b)).status_code==200
        assert r.get('/v1/inbox',headers=header(b)).json()['items']==[]

def test_cleanup_lease_late_ack_and_ack_after_deletion(pair):
    app,c,(a,b,_)=pair
    tid,data=send(c,a,b)
    with app.state.store.transaction() as db:db.execute('UPDATE transfers SET expires_at=? WHERE id=?',(time.time()-1,tid))
    app.state.leases[tid]=1
    asyncio.run(app.state.cleanup())
    assert app.state.store.path(tid).exists()
    assert c.get(f'/v1/transfers/{tid}/content',headers=header(b)).status_code==410
    assert c.post(f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(b)).status_code==410
    app.state.leases[tid]=0;asyncio.run(app.state.cleanup());assert not app.state.store.path(tid).exists()
    tid,data=send(c,a,b)
    assert c.post(f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(b)).status_code==200
    with app.state.store.transaction() as db:db.execute('UPDATE transfers SET received_at=? WHERE id=?',(time.time()-600,tid))
    asyncio.run(app.state.cleanup());assert not app.state.store.path(tid).exists()
    assert c.post(f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(b)).status_code==200

def test_quota_and_cancel_release(pair,monkeypatch):
    app,c,(a,b,_)=pair
    from app import main
    small=create_app(app.state.store.root)
    # Oversize and inbox quota are separate from stream size checking.
    data=draft(b);data['size']=52428801
    assert c.post('/v1/transfers',json=data,headers=header(a)).status_code==413
    data=draft(b);data['size']=52428800
    ids=[]
    for _ in range(20):
        data['client_transfer_id']=str(uuid.uuid4());r=c.post('/v1/transfers',json=data,headers=header(a));assert r.status_code==200,r.text;ids.append(r.json()['id'])
    data['size']=30*1024*1024;data['client_transfer_id']=str(uuid.uuid4())
    assert c.post('/v1/transfers',json=data,headers=header(a)).status_code==507
    for tid in ids:assert c.post(f'/v1/transfers/{tid}/cancel',headers=header(a)).status_code==200
    asyncio.run(app.state.cleanup())
    assert c.post('/v1/transfers',json=data,headers=header(a)).status_code==200

def test_enrollment_one_use_rate_and_revocation(pair):
    app,c,(a,b,_)=pair
    code=str(uuid.uuid4())
    with app.state.store.transaction() as db:db.execute('INSERT INTO enrollments VALUES(?,?,NULL)',(digest(code.encode()),time.time()+600))
    j=dict(code=code,device_name='a',platform='windows',client_version='test')
    assert c.post('/v1/enroll',json=j).status_code==200
    for _ in range(5):assert c.post('/v1/enroll',json=j).status_code==401
    assert c.post('/v1/enroll',json=j).status_code==429
    with c.websocket_connect('/v1/events',headers=header(a)) as ws:
        assert ws.receive_json()['type']=='device.changed'
        with app.state.store.transaction() as db:db.execute('UPDATE devices SET revoked_at=? WHERE id=?',(time.time(),a['device_id']))
        assert c.get('/v1/me',headers=header(a)).status_code==401
        asyncio.run(app.state.cleanup())
        assert ws.receive()['type']=='websocket.close'

def test_sensitive_old_action_and_invalid_metadata(pair):
    _,c,(a,b,_)=pair
    data=draft(b);data['origin_created_at']=stamp(time.time()-600);data['sensitivity']='sensitive'
    assert c.post('/v1/transfers',json=data,headers=header(a)).status_code==410
    data['sensitivity']='normal'
    tid=c.post('/v1/transfers',json=data,headers=header(a)).json()['id']
    c.put(f'/v1/transfers/{tid}/content',content=b'hello',headers=header(a))
    committed=c.post(f'/v1/transfers/{tid}/commit',headers=header(a)).json()
    assert committed['auto_action_until']<committed['committed_at']
    assert c.post('/v1/transfers',content=b'x'*16385,headers=header(a)).status_code==413
    assert c.get('/v1/inbox?cursor=invalid',headers=header(b)).status_code==422
    data['sender_device_id']=a['device_id']
    assert c.post('/v1/transfers',json=data,headers=header(a)).status_code==422

def test_shared_fixture():
    from jsonschema import validate
    root=Path(__file__).resolve().parents[2]/'protocol'
    validate(json.loads((root/'fixtures/transfer.json').read_text(encoding='utf-8')),json.loads((root/'transfer.schema.json').read_text(encoding='utf-8')))
    validate(json.loads((root/'fixtures/error.json').read_text(encoding='utf-8')),json.loads((root/'error.schema.json').read_text(encoding='utf-8')))

def test_ack_cancel_race(pair):
    from concurrent.futures import ThreadPoolExecutor
    _,c,(a,b,_)=pair
    tid,data=send(c,a,b)
    with ThreadPoolExecutor(2) as pool:
        ack=pool.submit(c.post,f'/v1/transfers/{tid}/ack',json={'size':5,'sha256':data['sha256']},headers=header(b))
        cancel=pool.submit(c.post,f'/v1/transfers/{tid}/cancel',headers=header(a))
        results=[ack.result(),cancel.result()]
    assert sum(r.status_code==200 for r in results)==1
    state=c.get(f'/v1/transfers/{tid}',headers=header(a)).json()['state']
    assert state in ['RECEIVED','CANCELLED']

def test_disk_failure_no_success_and_cross_group(pair,monkeypatch):
    app,c,(a,b,other)=pair
    data=draft(b);tid=c.post('/v1/transfers',json=data,headers=header(a)).json()['id']
    original=Path.open
    def fail(path,*args,**kwargs):
        if path.suffix=='.part':raise OSError('simulated ENOSPC')
        return original(path,*args,**kwargs)
    with monkeypatch.context() as m:
        m.setattr(Path,'open',fail)
        assert c.put(f'/v1/transfers/{tid}/content',content=b'hello',headers=header(a)).status_code==507
    assert c.get(f'/v1/transfers/{tid}',headers=header(a)).json()['state']=='CREATED'
    assert not (app.state.store.root/'tmp'/f'{tid}.part').exists()
    with app.state.store.transaction() as db:db.execute("UPDATE devices SET group_id='other' WHERE id=?",(other['device_id'],))
    assert c.post('/v1/transfers',json=draft(other),headers=header(a)).status_code==403

def test_inbox_pagination_and_durable_schema(pair):
    app,c,(a,b,_)=pair
    for _ in range(51):send(c,a,b,b'')
    page=c.get('/v1/inbox',headers=header(b)).json();assert len(page['items'])==50
    second=c.get('/v1/inbox?cursor='+page['next_cursor'],headers=header(b)).json();assert len(second['items'])==1
    assert second['items'][0]['id'] not in {r['id'] for r in page['items']}
