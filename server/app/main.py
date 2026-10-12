import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import ClientDisconnect
from .store import Store

def now(): return time.time()
def stamp(t): return datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00','Z') if t is not None else None
def digest(b): return hashlib.sha256(b).hexdigest()

class Fault(Exception):
    def __init__(self, status, code, retryable=False): self.status,self.code,self.retryable=status,code,retryable

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Enrollment(Strict):
    code: str = Field(min_length=20,max_length=128)
    device_name: str = Field(min_length=1,max_length=80)
    platform: Literal['android','windows']
    client_version: str = Field(max_length=32)
class Draft(Strict):
    client_transfer_id: uuid.UUID
    recipient_device_id: uuid.UUID
    kind: Literal['text','file']
    name: str | None = Field(default=None,max_length=255)
    mime: str = Field(max_length=128)
    size: int = Field(ge=0)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    sensitivity: Literal['normal','sensitive'] = 'normal'
    requested_ttl_seconds: int = Field(default=86400,gt=0,le=86400)
    origin_created_at: datetime
    batch_id: uuid.UUID | None = None
class Ack(Strict):
    size: int = Field(ge=0)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')

def create_app(root=None):
    store = Store(root)
    sockets = {}
    locks = defaultdict(asyncio.Lock)
    leases = defaultdict(int)
    rates = defaultdict(deque)
    uploads = defaultdict(int)
    limits = dict(max_file_bytes=int(os.getenv('MAX_FILE_BYTES',52428800)),max_text_bytes=int(os.getenv('MAX_TEXT_BYTES',65536)),storage_quota_bytes=int(os.getenv('STORAGE_QUOTA_BYTES',1073741824)))
    async def notify(device, kind, tid=None):
        ws = sockets.get(device)
        if ws:
            try: await ws.send_json(dict(event_id=str(uuid.uuid4()),type=kind,transfer_id=tid,server_time=stamp(now())))
            except Exception: sockets.pop(device,None)
    async def cleanup():
        t = now()
        with store.transaction() as db:
            db.execute("UPDATE transfers SET state='EXPIRED' WHERE (state IN ('CREATED','UPLOADED') AND upload_deadline<=?) OR (state='READY' AND expires_at<=?)", (t,t))
            dead = db.all("SELECT * FROM transfers WHERE payload_deleted_at IS NULL AND (state IN ('CANCELLED','EXPIRED') OR (state='RECEIVED' AND received_at+?<=?))",(int(os.getenv('ACK_GRACE_SECONDS',300)),t))
            for r in dead:
                if leases[r['id']] or locks[r['id']].locked(): continue
                try:
                    store.path(r['id']).unlink(missing_ok=True)
                    (store.root/'tmp'/f"{r['id']}.part").unlink(missing_ok=True)
                    db.execute('UPDATE transfers SET payload_deleted_at=?,name=NULL WHERE id=?',(t,r['id']))
                except OSError: pass
            db.execute('DELETE FROM receipts WHERE transfer_id IN (SELECT id FROM transfers WHERE created_at<? AND payload_deleted_at IS NOT NULL)',(t-604800,))
            db.execute('DELETE FROM transfers WHERE created_at<? AND payload_deleted_at IS NOT NULL',(t-604800,))
            db.execute('DELETE FROM enrollments WHERE expires_at<?',(t-604800,))
            valid = {r['id'] for r in db.all('SELECT id FROM transfers WHERE payload_deleted_at IS NULL')}
            revoked = {r['id'] for r in db.all('SELECT id FROM devices WHERE revoked_at IS NOT NULL')}
        for directory in ('payloads','tmp'):
            for p in (store.root/directory).iterdir():
                if p.name.removesuffix('.part') not in valid:
                    try: p.unlink()
                    except OSError: pass
        for did in revoked:
            ws = sockets.pop(did,None)
            if ws:
                try: await ws.close(code=4401)
                except Exception: pass
        for r in dead: await notify(r['recipient_id'],'transfer.'+r['state'].lower(),r['id'])
    async def maintenance():
        while True:
            await asyncio.sleep(2)  # Prompt credential revocation; disk cleanup every 60 s.
            with store.transaction() as db: revoked = db.all('SELECT id FROM devices WHERE revoked_at IS NOT NULL')
            for r in revoked:
                ws=sockets.pop(r['id'],None)
                if ws:
                    try: await ws.close(code=4401)
                    except Exception: pass
            if int(now()) // 60 != maintenance.minute:
                maintenance.minute=int(now())//60
                await cleanup()
    maintenance.minute=0
    @asynccontextmanager
    async def lifespan(app):
        app.state.loop=asyncio.get_running_loop()
        # No live uploads at startup: partial uploads are never considered committed.
        for p in (store.root/'tmp').glob('*.part'): p.unlink(missing_ok=True)
        with store.transaction() as db:
            for r in db.all("SELECT id FROM transfers WHERE state='UPLOADED'"):
                if not store.path(r['id']).exists():db.execute("UPDATE transfers SET state='CREATED' WHERE id=?",(r['id'],))
        await cleanup()
        task=asyncio.create_task(maintenance())
        yield
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        store.engine.dispose()
    app=FastAPI(title='QDrop',version='0.1.0',lifespan=lifespan)
    app.state.store=store
    app.state.cleanup=cleanup
    app.state.leases=leases
    @app.exception_handler(Fault)
    async def fault(req, e):
        return JSONResponse(dict(code=e.code,message=e.code,retryable=e.retryable,request_id=str(uuid.uuid4())),status_code=e.status,headers={'Retry-After':'60'} if e.status==429 else {})
    from fastapi.exceptions import RequestValidationError
    @app.exception_handler(RequestValidationError)
    async def invalid(req,e): return await fault(req,Fault(422,'INVALID_METADATA'))
    @app.exception_handler(SQLAlchemyError)
    async def database_failure(req,e):
        full=getattr(getattr(e,'orig',None),'sqlite_errorcode',None)==13
        return await fault(req,Fault(507 if full else 503,'DISK_FULL' if full else 'DATABASE_UNAVAILABLE',True))
    @app.middleware('http')
    async def metadata_limit(request, call_next):
        enrollment_key='enroll:'+request.client.host if request.url.path=='/v1/enroll' else None
        if enrollment_key:
            q=rates[enrollment_key]
            while q and q[0]<now()-60:q.popleft()
            if len(q)>=5:return await fault(request,Fault(429,'RATE_LIMITED',True))
        if request.method=='POST':
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>16384:
                    if enrollment_key:rates[enrollment_key].append(now())
                    return await fault(request,Fault(413,'METADATA_TOO_LARGE'))
            request._body=bytes(body)
        try: response=await call_next(request)
        except OSError: response=await fault(request,Fault(507,'STORAGE_UNAVAILABLE',True))
        if enrollment_key and response.status_code>=400:rates[enrollment_key].append(now())
        return response
    def rate(key, maximum):
        q=rates[key]; t=now()
        while q and q[0]<t-60: q.popleft()
        if len(q)>=maximum: raise Fault(429,'RATE_LIMITED',True)
        q.append(t)
    def authenticate(header):
        if not header or not header.startswith('Bearer '): raise Fault(401,'UNAUTHORIZED')
        with store.transaction() as db:
            d=db.one('SELECT * FROM devices WHERE token_hash=? AND revoked_at IS NULL',(digest(header[7:].encode()),))
            if not d: raise Fault(401,'UNAUTHORIZED')
            db.execute('UPDATE devices SET last_seen_at=? WHERE id=?',(now(),d['id']))
        return d
    async def auth(request: Request):
        d=authenticate(request.headers.get('authorization')); rate(d['id'],600); return d
    def transfer(db,tid,d,role=None):
        r=db.one('SELECT * FROM transfers WHERE id=?',(str(tid),))
        if not r: raise Fault(404,'NOT_FOUND')
        allowed=[r['sender_id'],r['recipient_id']] if not role else [r[role+'_id']]
        if d['id'] not in allowed or d['group_id']!=r['group_id']: raise Fault(403,'FORBIDDEN')
        return r
    def public(r):
        out={k:v for k,v in r.items() if k not in ('digest','group_id','requested_ttl')}
        for k in ('created_at','upload_deadline','committed_at','expires_at','auto_action_until','received_at','payload_deleted_at','origin_created_at'): out[k]=stamp(r[k])
        out['server_time']=stamp(now()); return out
    def live(r):
        if r['state'] in ('EXPIRED','CANCELLED') or (r['expires_at'] is not None and r['expires_at']<=now()): raise Fault(410,'TRANSFER_EXPIRED')
        if r['state'] in ('CREATED','UPLOADED') and r['upload_deadline']<=now(): raise Fault(410,'UPLOAD_EXPIRED')
    @app.get('/healthz')
    async def health(): return {'ready':True}
    @app.get('/readyz')
    async def ready():
        with store.transaction() as db: db.one('SELECT 1')
        probe=store.root/'tmp'/'.probe'; probe.write_bytes(b''); probe.unlink(); return {'ready':True}
    @app.post('/v1/enroll')
    async def enroll(a:Enrollment, request:Request):
        key='enroll:'+request.client.host
        q=rates[key]
        while q and q[0]<now()-60:q.popleft()
        if len(q)>=5: raise Fault(429,'RATE_LIMITED',True)
        token=secrets.token_urlsafe(32); did=str(uuid.uuid4())
        with store.transaction() as db:
            result=db.execute('UPDATE enrollments SET consumed_at=? WHERE code_hash=? AND consumed_at IS NULL AND expires_at>?',(now(),digest(a.code.encode()),now()))
            if result.rowcount!=1:
                raise Fault(401,'INVALID_ENROLLMENT')
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?,?,?,NULL)',(did,'private',a.device_name,a.platform,a.client_version,digest(token.encode()),now()))
        return dict(device_id=did,token=token,group_id='private',protocol_version=1)
    @app.get('/v1/me')
    async def me(d=Depends(auth)): return dict(device_id=d['id'],name=d['name'],protocol_version=1,client_version='0.1.0',server_time=stamp(now()),limits=limits)
    @app.get('/v1/devices')
    async def devices(d=Depends(auth)):
        with store.transaction() as db: rows=db.all('SELECT id,name,platform,last_seen_at FROM devices WHERE group_id=? AND revoked_at IS NULL AND id!=?',(d['group_id'],d['id']))
        return {'devices':[dict(**r,online=r['id'] in sockets,capabilities=['send','receive']) for r in rows]}
    @app.post('/v1/transfers')
    async def create(a:Draft,d=Depends(auth)):
        normalized=a.model_dump(mode='json'); fingerprint=digest(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()); t=now()
        if a.origin_created_at.tzinfo is None: raise Fault(422,'UTC_REQUIRED')
        origin=a.origin_created_at.timestamp()
        if a.size>limits['max_text_bytes' if a.kind=='text' else 'max_file_bytes']: raise Fault(413,'PAYLOAD_TOO_LARGE')
        if a.sensitivity=='sensitive' and origin+300<=t: raise Fault(410,'SENSITIVE_EXPIRED')
        with store.transaction() as db:
            old=db.one('SELECT * FROM transfers WHERE sender_id=? AND client_transfer_id=?',(d['id'],str(a.client_transfer_id)))
            if old:
                if old['digest']!=fingerprint: raise Fault(409,'IDEMPOTENCY_CONFLICT')
                return public(old)
            target=db.one('SELECT * FROM devices WHERE id=? AND group_id=? AND revoked_at IS NULL',(str(a.recipient_device_id),d['group_id']))
            if not target or target['id']==d['id']: raise Fault(403,'INVALID_RECIPIENT')
            pending=db.one("SELECT COUNT(*) n FROM transfers WHERE recipient_id=? AND state IN ('CREATED','UPLOADED','READY')",(target['id'],))['n']
            if pending>=200: raise Fault(429,'INBOX_FULL',True)
            reserved=db.one('SELECT COALESCE(SUM(size),0) n FROM transfers WHERE payload_deleted_at IS NULL')['n']
            if reserved+a.size>limits['storage_quota_bytes']: raise Fault(507,'QUOTA_EXCEEDED',True)
            if shutil.disk_usage(store.root).free<a.size+16*1024*1024: raise Fault(507,'DISK_FULL',True)
            tid=str(uuid.uuid4())
            deadline=t+int(os.getenv('UPLOAD_DEADLINE_SECONDS',1800))
            if a.sensitivity=='sensitive':deadline=min(deadline,t+300,origin+300)
            db.execute('INSERT INTO transfers(id,group_id,sender_id,recipient_id,client_transfer_id,digest,kind,name,mime,size,sha256,sensitivity,batch_id,origin_device_id,origin_created_at,requested_ttl,state,created_at,upload_deadline) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,d['group_id'],d['id'],target['id'],str(a.client_transfer_id),fingerprint,a.kind,a.name,a.mime,a.size,a.sha256,a.sensitivity,str(a.batch_id) if a.batch_id else None,d['id'],origin,a.requested_ttl_seconds,'CREATED',t,deadline))
            return public(db.one('SELECT * FROM transfers WHERE id=?',(tid,)))
    @app.get('/v1/transfers/{tid}')
    async def status(tid:uuid.UUID,d=Depends(auth)):
        with store.transaction() as db:return public(transfer(db,tid,d))
    @app.put('/v1/transfers/{tid}/content')
    async def upload(tid:uuid.UUID,request:Request,d=Depends(auth)):
        tid=str(tid)
        if locks[tid].locked(): raise Fault(409,'UPLOAD_BUSY',True)
        if uploads[d['id']]>=2:raise Fault(429,'UPLOAD_LIMIT',True)
        async with locks[tid]:
            with store.transaction() as db:
                r=transfer(db,tid,d,'sender');live(r)
                if r['state'] in ('UPLOADED','READY','RECEIVED'):return public(r)
            uploads[d['id']]+=1
            part=store.root/'tmp'/f'{tid}.part'; h=hashlib.sha256(); size=0
            try:
                async with asyncio.timeout(300):
                    with part.open('wb') as f:
                        iterator=request.stream().__aiter__()
                        while True:
                            try:chunk=await asyncio.wait_for(anext(iterator),120)
                            except StopAsyncIteration:break
                            size+=len(chunk)
                            if size>r['size']:raise Fault(413,'PAYLOAD_TOO_LARGE')
                            h.update(chunk);f.write(chunk)
                        f.flush();os.fsync(f.fileno())
                if size!=r['size'] or h.hexdigest()!=r['sha256']:raise Fault(422,'CHECKSUM_MISMATCH',True)
                if r['kind']=='text':
                    try:part.read_bytes().decode('utf-8')
                    except UnicodeDecodeError:raise Fault(422,'INVALID_UTF8')
                with store.transaction() as db:
                    # Reauthenticate and recheck terminal state after streaming.
                    if not db.one('SELECT id FROM devices WHERE id=? AND revoked_at IS NULL',(d['id'],)):raise Fault(401,'UNAUTHORIZED')
                    r=transfer(db,tid,d,'sender');live(r)
                    os.replace(part,store.path(tid))
                    db.execute("UPDATE transfers SET state='UPLOADED' WHERE id=? AND state='CREATED'",(tid,))
                    return public(transfer(db,tid,d))
            except OSError:raise Fault(507,'DISK_FULL',True)
            except TimeoutError:raise Fault(408,'UPLOAD_TIMEOUT',True)
            except ClientDisconnect:raise Fault(408,'UPLOAD_INTERRUPTED',True)
            finally:part.unlink(missing_ok=True);uploads[d['id']]-=1
    @app.post('/v1/transfers/{tid}/commit')
    async def commit(tid:uuid.UUID,d=Depends(auth)):
        with store.transaction() as db:
            r=transfer(db,tid,d,'sender');live(r)
            if r['state'] in ('READY','RECEIVED'):return public(r)
            if r['state']!='UPLOADED' or not store.path(str(tid)).exists():raise Fault(409,'NOT_UPLOADED')
            t=now();expiry=t+min(r['requested_ttl'],int(os.getenv('DEFAULT_TTL_SECONDS',86400)))
            if r['sensitivity']=='sensitive':expiry=min(expiry,t+300,r['created_at']+300,r['origin_created_at']+300)
            if expiry<=t:raise Fault(410,'SENSITIVE_EXPIRED')
            action=min(t+120,r['origin_created_at']+120)
            if abs(t-r['origin_created_at'])>300:action=t-1
            db.execute("UPDATE transfers SET state='READY',committed_at=?,expires_at=?,auto_action_until=? WHERE id=? AND state='UPLOADED'",(t,expiry,action,str(tid)))
            out=public(transfer(db,tid,d))
        await notify(r['recipient_id'],'transfer.ready',str(tid));return out
    @app.get('/v1/inbox')
    async def inbox(cursor:str|None=None,d=Depends(auth)):
        after=(0,'')
        if cursor:
            try:after=tuple(json.loads(base64.urlsafe_b64decode(cursor)));assert len(after)==2;float(after[0]);uuid.UUID(after[1])
            except Exception:raise Fault(422,'INVALID_CURSOR')
        with store.transaction() as db:rows=db.all("SELECT * FROM transfers WHERE recipient_id=? AND state='READY' AND expires_at>? AND (created_at>? OR (created_at=? AND id>?)) ORDER BY created_at,id LIMIT 51",(d['id'],now(),after[0],after[0],after[1]))
        more=len(rows)>50;rows=rows[:50]
        return dict(items=[public(r) for r in rows],next_cursor=base64.urlsafe_b64encode(json.dumps([rows[-1]['created_at'],rows[-1]['id']]).encode()).decode() if more else None)
    @app.get('/v1/transfers/{tid}/content')
    async def download(tid:uuid.UUID,d=Depends(auth)):
        tid=str(tid)
        with store.transaction() as db:
            r=transfer(db,tid,d,'recipient');live(r)
            if r['state'] not in ('READY','RECEIVED'):raise Fault(409,'NOT_READY')
            if r['payload_deleted_at'] is not None:raise Fault(410,'PAYLOAD_DELETED')
            try:f=store.path(tid).open('rb')
            except FileNotFoundError:raise Fault(507,'PAYLOAD_UNAVAILABLE',True)
            leases[tid]+=1
        async def stream():
            try:
                async with asyncio.timeout(300):
                    while chunk:=await asyncio.to_thread(f.read,65536):yield chunk
            finally:f.close();leases[tid]-=1
        return StreamingResponse(stream(),media_type='application/octet-stream',headers={'Content-Length':str(r['size']),'Cache-Control':'no-store'})
    @app.post('/v1/transfers/{tid}/ack')
    async def ack(tid:uuid.UUID,a:Ack,d=Depends(auth)):
        with store.transaction() as db:
            r=transfer(db,tid,d,'recipient')
            if a.size!=r['size'] or a.sha256!=r['sha256']:raise Fault(422,'CHECKSUM_MISMATCH')
            if r['state']=='RECEIVED':return public(r)
            live(r)
            if r['state']!='READY':raise Fault(409,'NOT_READY')
            t=now();db.execute("UPDATE transfers SET state='RECEIVED',received_at=? WHERE id=? AND state='READY'",(t,str(tid)))
            db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?)',(str(tid),d['id'],t));out=public(transfer(db,tid,d))
        await notify(r['sender_id'],'transfer.received',str(tid));return out
    @app.post('/v1/transfers/{tid}/cancel')
    async def cancel(tid:uuid.UUID,d=Depends(auth)):
        with store.transaction() as db:
            r=transfer(db,tid,d,'sender')
            if r['state']=='CANCELLED':return public(r)
            live(r)
            if r['state']=='RECEIVED':raise Fault(409,'ALREADY_RECEIVED')
            db.execute("UPDATE transfers SET state='CANCELLED' WHERE id=? AND state IN ('CREATED','UPLOADED','READY')",(str(tid),));out=public(transfer(db,tid,d))
        await notify(r['recipient_id'],'transfer.cancelled',str(tid));return out
    @app.websocket('/v1/events')
    async def events(ws:WebSocket):
        try:d=authenticate(ws.headers.get('authorization'))
        except Fault:await ws.close(code=4401);return
        await ws.accept();old=sockets.get(d['id'])
        if old:
            try:await old.close(code=4001)
            except Exception:pass
        sockets[d['id']]=ws
        try:
            await notify(d['id'],'device.changed')
            while True:
                try:
                    data=await asyncio.wait_for(ws.receive_text(),90)
                    if len(data)>1024:await ws.close(code=1009);break
                    authenticate(ws.headers.get('authorization'))
                    await ws.send_json(dict(type='heartbeat',server_time=stamp(now())))
                except TimeoutError:await ws.close(code=4000);break
        except (WebSocketDisconnect,Fault):pass
        finally:
            if sockets.get(d['id']) is ws:sockets.pop(d['id'],None)
    return app

app=create_app()
