"""Run the built debug WPF receiver against the live local server. Close QDrop first.
Uses separate debug identities and an ignored private test directory. No tokens printed.
"""
import hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'server'))
from app.store import Store
from datetime import datetime,timezone,timedelta

def run():
    store=Store(ROOT/'data');base='http://127.0.0.1:8000'
    def enroll(platform):
        code=str(uuid.uuid4())
        with store.transaction() as db:db.execute('INSERT INTO enrollments VALUES(?,?,NULL)',(hashlib.sha256(code.encode()).hexdigest(),time.time()+600))
        r=httpx.post(base+'/v1/enroll',json=dict(code=code,device_name='recovery '+platform,platform=platform,client_version='test'));r.raise_for_status();return r.json()
    a=enroll('android');b=enroll('windows');h={'Authorization':'Bearer '+a['token']}
    target=ROOT/'.tools/windows-recovery';target.mkdir(exist_ok=True)
    conf=target/'config.json';conf.write_text(json.dumps(dict(BaseUrl=base,Token=b['token'],DeviceId=b['device_id'],Directory=str(target/'received'),AutoCopy=True,AutoOpen=True)),encoding='utf-8')
    env={**os.environ,'QDROP_TEST_ROOT':str(target),'QDROP_TEST_CONFIG':str(conf),'DOTNET_ROOT':str(ROOT/'.tools/dotnet')}
    exe=ROOT/'windows/QDrop.App/bin/Debug/net10.0-windows10.0.19041.0/win-x64/QDrop.App.exe'
    def receive(marker=False):
        p=subprocess.Popen([str(exe),'--integration-test']+(['--recovery-marker'] if marker else []),env=env)
        assert p.wait(30)==0
        return json.loads((target/'integration.json').read_text(encoding='utf-8'))
    def send(body,kind='text',name=None,age=0):
        j=dict(client_transfer_id=str(uuid.uuid4()),recipient_device_id=b['device_id'],kind=kind,name=name,mime='text/plain',size=len(body),sha256=hashlib.sha256(body).hexdigest(),origin_created_at=(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat())
        r=httpx.post(base+'/v1/transfers',json=j,headers=h);r.raise_for_status();tid=r.json()['id']
        httpx.put(base+f'/v1/transfers/{tid}/content',content=body,headers=h).raise_for_status();httpx.post(base+f'/v1/transfers/{tid}/commit',headers=h).raise_for_status();return tid,j
    text='\ufeffQDrop 中文长文本 🌍 https://example.com '+('逐字一致。'*100)
    tid,j=send(text.encode());assert receive()['clipboard']==text
    with sqlite3.connect(target/'tasks.db') as db:
        assert db.execute('SELECT ack,action FROM received WHERE id=?',(tid,)).fetchone()==(1,'succeeded')
        db.execute("UPDATE received SET ack=0,action='attempted' WHERE id=?",(tid,))
    assert receive(True)['clipboard']=='QDrop local recovery marker'
    with sqlite3.connect(target/'tasks.db') as db:assert db.execute('SELECT ack,action FROM received WHERE id=?',(tid,)).fetchone()==(1,'attempted')
    file_id,file_meta=send(b'never execute this','file','../../中文.PS1');receive(True)
    with sqlite3.connect(target/'tasks.db') as db:
        path,ack,action=db.execute('SELECT path,ack,action FROM received WHERE id=?',(file_id,)).fetchone()
        assert Path(path).is_relative_to(target/'received') and ack==1 and action=='skipped'
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==file_meta['sha256']
    old,_=send(b'old text',age=360);assert receive(True)['clipboard']=='QDrop local recovery marker'
    with sqlite3.connect(target/'tasks.db') as db:assert db.execute('SELECT action FROM received WHERE id=?',(old,)).fetchone()[0]=='skipped'
    store.engine.dispose()
    print(json.dumps(dict(sta_utf8_clipboard='passed',lost_ack_retry='passed',attempted_not_replayed='passed',unsafe_file_saved_only='passed',old_text_not_copied='passed')))

if __name__=='__main__':run()
