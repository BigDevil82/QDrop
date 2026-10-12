"""Live HTTP + WebSocket two-device smoke, with actual process restart and disk.
Run from root: .venv/Scripts/python.exe scripts/smoke.py
No credentials or payload bodies are printed.
"""
import hashlib
import json
import os
import socket
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
import httpx
from websockets.sync.client import connect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from app.store import Store

def run():
    with tempfile.TemporaryDirectory(prefix='qdrop-smoke-') as folder:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}';env={**os.environ,'DATA_DIR':folder}
        def start():
            p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--app-dir',str(ROOT/'server'),'--host','127.0.0.1','--port',str(port),'--no-access-log','--no-proxy-headers'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
            for _ in range(100):
                try:
                    if httpx.get(base+'/readyz',timeout=1).status_code==200:return p
                except httpx.HTTPError:pass
                time.sleep(.1)
            stop(p);raise RuntimeError('Server startup failed')
        def stop(p):
            if p.poll() is None:
                p.send_signal(signal.CTRL_BREAK_EVENT) if os.name=='nt' else p.terminate()
                p.wait(10)
        p=start()
        try:
            store=Store(folder);devices=[]
            for platform in ['android','windows']:
                code=str(uuid.uuid4())
                with store.transaction() as db:db.execute('INSERT INTO enrollments VALUES(?,?,NULL)',(hashlib.sha256(code.encode()).hexdigest(),time.time()+600))
                r=httpx.post(base+'/v1/enroll',json=dict(code=code,device_name=platform,platform=platform,client_version='smoke'));r.raise_for_status();devices.append(r.json())
            def headers(d):return {'Authorization':'Bearer '+d['token']}
            a,b=devices;body='中文长文本 🌍 https://example.com'.encode();sha=hashlib.sha256(body).hexdigest()
            def send(source,target):
                metadata=dict(client_transfer_id=str(uuid.uuid4()),recipient_device_id=target['device_id'],kind='text',name=None,mime='text/plain;charset=utf-8',size=len(body),sha256=sha,origin_created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
                r=httpx.post(base+'/v1/transfers',json=metadata,headers=headers(source));r.raise_for_status();tid=r.json()['id']
                httpx.put(base+f'/v1/transfers/{tid}/content',content=body,headers=headers(source)).raise_for_status()
                httpx.post(base+f'/v1/transfers/{tid}/commit',headers=headers(source)).raise_for_status();return tid
            with connect(base.replace('http:','ws:')+'/v1/events',additional_headers=headers(b)) as ws:
                assert json.loads(ws.recv())['type']=='device.changed'
                tid=send(a,b)
                event=json.loads(ws.recv());assert event['type']=='transfer.ready' and event['transfer_id']==tid
                assert 'text' not in event and 'token' not in event
            # Receiver deliberately missed ACK, sender repeats create tested separately.
            assert httpx.get(base+f'/v1/transfers/{tid}/content',headers=headers(b)).content==body
            stop(p);p=start()
            inbox=httpx.get(base+'/v1/inbox',headers=headers(b)).json()['items'];assert inbox[0]['id']==tid
            for _ in range(2):httpx.post(base+f'/v1/transfers/{tid}/ack',json=dict(size=len(body),sha256=sha),headers=headers(b)).raise_for_status()
            reverse=send(b,a)
            assert httpx.get(base+f'/v1/transfers/{reverse}/content',headers=headers(a)).content==body
            print(json.dumps({'live_http':'passed','websocket_event':'passed','restart_lost_ack':'passed','bidirectional':'passed','utf8_sha256':'passed'}))
        finally:
            stop(p)
            store.engine.dispose()

if __name__=='__main__':run()
