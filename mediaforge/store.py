"""Transactional state and ownership. Only the service writes this database."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from cryptography.fernet import Fernet
from .catalog import validate
from .config import Settings
from .errors import ForgeError
from .files import inspect

TERMINAL={'succeeded','partial','failed','cancelled','recoverable'}
ACTIVE={'accepted','running'}


def uid(prefix): return prefix+'_'+uuid.uuid4().hex

def clean_name(value):
    value=Path(value.replace('\\','/')).name.strip()
    value=''.join(c for c in value if ord(c)>=32 and ord(c)!=127)
    if not value or value in {'.','..'} or len(value.encode('utf-8'))>220:
        raise ForgeError('invalid_filename','文件名为空或过长。','请将文件名缩短至 220 字节以内。')
    return value


class Connection(sqlite3.Connection):
    def __exit__(self,exc_type,exc,tb):
        try:return super().__exit__(exc_type,exc,tb)
        finally:self.close()


class Store:
    def __init__(self, settings: Settings):
        self.settings=settings
        self.root=settings.data.expanduser().resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.root.chmod(0o700)
        for name in ['files','staging','jobs','exports']:
            (self.root/name).mkdir(exist_ok=True,mode=0o700)
        self.db_path=self.root/'state.sqlite3'
        self._setup()
        keyfile=self.root/'secret.key'
        self._exclusive_file(keyfile,Fernet.generate_key())
        self.cipher=Fernet(keyfile.read_bytes().strip())
        tokenfile=self.root/'admin.token'
        self._exclusive_file(tokenfile,secrets.token_urlsafe(40).encode())
        token=tokenfile.read_text().strip()
        with self.tx() as con:
            con.execute('INSERT OR IGNORE INTO tokens(hash,owner,label,admin) VALUES (?,?,?,1)',
                        (self.hash_token(token),'workspace_default','管理员'))

    @staticmethod
    def _exclusive_file(path,content):
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as f: f.write(content)
        except FileExistsError: pass

    def connect(self):
        con=sqlite3.connect(self.db_path,timeout=30,factory=Connection)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=30000')
        return con

    @contextmanager
    def tx(self):
        con=self.connect()
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback(); raise
        finally: con.close()

    def _setup(self):
        with self.connect() as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.executescript('''
            CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,owner TEXT,label TEXT,admin INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,owner TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,owner TEXT,bytes INTEGER,created REAL);
            CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,owner TEXT,name TEXT,path TEXT,size INTEGER,meta TEXT,created REAL,task_id TEXT);
            CREATE INDEX IF NOT EXISTS files_owner ON files(owner);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT,tool TEXT,status TEXT,stage TEXT,progress REAL DEFAULT 0,cancel INTEGER DEFAULT 0,created REAL,updated REAL,idem TEXT,fingerprint TEXT,params TEXT,secret TEXT,inputs TEXT,group_name TEXT,timeout INTEGER,retries INTEGER,error TEXT,UNIQUE(owner,idem));
            CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner,created DESC);
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,task_id TEXT REFERENCES tasks(id),seq INTEGER,inputs TEXT,status TEXT,attempt INTEGER DEFAULT 0,outputs TEXT DEFAULT '[]',error TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT REFERENCES tasks(id),time REAL,code TEXT,message TEXT);
            CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY,owner TEXT,name TEXT,tool TEXT,params TEXT,created REAL);
            ''')
        self.db_path.chmod(0o600)

    @staticmethod
    def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, token):
        if not token: return None
        with self.connect() as con:
            row=con.execute('SELECT owner FROM tokens WHERE hash=?',(self.hash_token(token),)).fetchone()
            if row: return row['owner']
            row=con.execute('SELECT owner FROM sessions WHERE hash=? AND expires>?',(self.hash_token(token),time.time())).fetchone()
            return row['owner'] if row else None

    def session(self,token):
        with self.connect() as con:
            row=con.execute('SELECT owner FROM tokens WHERE hash=?',(self.hash_token(token),)).fetchone()
        if not row: raise ForgeError('unauthorized','访问令牌不正确。','请使用管理员提供的工作区令牌。',401)
        value=secrets.token_urlsafe(40)
        with self.tx() as con:
            con.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            con.execute('INSERT INTO sessions VALUES(?,?,?)',(self.hash_token(value),row['owner'],time.time()+43200))
        return value,row['owner']

    def revoke(self,value):
        with self.tx() as con: con.execute('DELETE FROM sessions WHERE hash=?',(self.hash_token(value),))

    def create_workspace(self,actor,label):
        with self.tx() as con:
            if not con.execute('SELECT 1 FROM tokens WHERE owner=? AND admin=1',(actor,)).fetchone():
                raise ForgeError('forbidden','只有管理员能创建工作区。','联系管理员。',403)
            owner=uid('workspace'); token=secrets.token_urlsafe(40)
            con.execute('INSERT INTO tokens VALUES(?,?,?,0)',(self.hash_token(token),owner,label[:80]))
        return {'owner':owner,'token':token,'label':label[:80]}

    def reserve(self,owner,size):
        if size<=0 or size>self.settings.max_file_bytes:
            raise ForgeError('file_too_large','文件为空或超过单文件大小限制。','在设置页查看大小限制。',413)
        id=uid('upload')
        with self.tx() as con:
            con.execute('DELETE FROM reservations WHERE created<?',(time.time()-3600,))
            used=con.execute('SELECT COALESCE(SUM(size),0) FROM files WHERE owner=?',(owner,)).fetchone()[0]
            reserved=con.execute('SELECT COALESCE(SUM(bytes),0) FROM reservations WHERE owner=?',(owner,)).fetchone()[0]
            if used+reserved+size>self.settings.quota_bytes:
                raise ForgeError('quota_exceeded','工作区存储空间不足。','清理历史文件或提高工作区配额。',413)
            con.execute('INSERT INTO reservations VALUES(?,?,?,?)',(id,owner,size,time.time()))
        return id

    def release_reservation(self,id):
        with self.tx() as con: con.execute('DELETE FROM reservations WHERE id=?',(id,))

    def register_upload(self,owner,name,path,reservation):
        name=clean_name(name)
        meta=inspect(path,name)
        id=uid('file'); rel='files/'+id+Path(name).suffix.lower()
        dest=self.root/rel
        try:
            with self.tx() as con:
                limit=con.execute('SELECT bytes FROM reservations WHERE id=? AND owner=?',(reservation,owner)).fetchone()
                if not limit or meta['size']>limit[0]:
                    raise ForgeError('upload_mismatch','上传大小与声明不符。','重新上传文件。')
                Path(path).replace(dest); dest.chmod(0o600)
                con.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,NULL)',(id,owner,name,rel,meta['size'],json.dumps(meta),time.time()))
                con.execute('DELETE FROM reservations WHERE id=?',(reservation,))
        except BaseException:
            dest.unlink(missing_ok=True); raise
        return self.file(owner,id)

    def import_file(self,owner,path,name=None):
        # Internal test/administrative helper; never exposed as a server API.
        import shutil
        path=Path(path); reservation=self.reserve(owner,path.stat().st_size)
        temp=self.root/'staging'/reservation
        try:
            shutil.copyfile(path,temp)
            return self.register_upload(owner,name or path.name,temp,reservation)
        finally:
            temp.unlink(missing_ok=True); self.release_reservation(reservation)

    def file(self,owner,id,internal=False):
        with self.connect() as con:
            row=con.execute('SELECT * FROM files WHERE owner=? AND id=?',(owner,id)).fetchone()
        if not row: raise ForgeError('file_not_found','文件不存在或无访问权限。','重新上传文件。',404)
        data={'id':row['id'],'name':row['name'],'created_at':row['created'],'task_id':row['task_id'],**json.loads(row['meta'])}
        if internal: data['path']=str(self.safe_path(row['path']))
        return data

    def safe_path(self,relative):
        path=(self.root/relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ForgeError('file_not_found','文件已清理或不可访问。','重新上传源文件。',404)
        return path

    def file_list(self,owner,limit=50,offset=0):
        with self.connect() as con:
            ids=con.execute('SELECT id FROM files WHERE owner=? ORDER BY created DESC LIMIT ? OFFSET ?',(owner,limit,offset)).fetchall()
        return [self.file(owner,r['id']) for r in ids]

    def submit(self,owner,operation,file_ids,params=None,idem=None,group='',timeout=None,retries=0):
        if not isinstance(params or {},dict): raise ForgeError('invalid_parameters','参数必须是对象。')
        tool,values=validate(operation,params or {})
        if not isinstance(file_ids,list) or not tool['min_files']<=len(file_ids)<=tool['max_files'] or len(set(file_ids))!=len(file_ids):
            raise ForgeError('invalid_inputs',f'此工具需要 {tool["min_files"]}–{tool["max_files"]} 个不重复文件。','在文件列表调整输入。')
        files=[self.file(owner,i,True) for i in file_ids]
        if any(f['kind'] not in tool['accept'] for f in files):
            raise ForgeError('unsupported_input','输入文件类型不适合当前工具。','根据文件类型选择工具。')
        if operation=='image-repair' and (files[0]['width'],files[0]['height'])!=(files[1]['width'],files[1]['height']):
            raise ForgeError('mask_size','修复遮罩必须与原图尺寸一致。')
        timeout=int(timeout or self.settings.timeout)
        if not 1<=timeout<=7200 or not 0<=retries<=3: raise ForgeError('invalid_limits','超时或重试次数超出允许范围。')
        fingerprint=hashlib.sha256(json.dumps([operation,[(f['sha256'],f['name']) for f in files],values,group,timeout,retries],sort_keys=True).encode()).hexdigest()
        id=uid('task'); now=time.time(); idem=idem or uid('key')
        if len(idem)>200: raise ForgeError('invalid_idempotency_key','幂等键过长。')
        secret={k:values.pop(k) for k,s in tool['schema']['properties'].items() if s.get('sensitive') and k in values}
        sealed=self.cipher.encrypt(json.dumps(secret).encode()).decode()
        with self.tx() as con:
            old=con.execute('SELECT id,fingerprint FROM tasks WHERE owner=? AND idem=?',(owner,idem)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint: raise ForgeError('idempotency_conflict','同一幂等键已用于不同请求。','为不同请求使用新的幂等键。',409)
                id=old['id']
            else:
                # Recheck ownership/existence under the write transaction: cleanup may
                # have removed an upload after the earlier metadata read.
                marks=','.join('?' for _ in file_ids)
                present=con.execute('SELECT COUNT(*) FROM files WHERE owner=? AND id IN ('+marks+')',[owner,*file_ids]).fetchone()[0]
                if present!=len(file_ids):raise ForgeError('file_not_found','输入文件已被清理。','重新上传文件后再提交。',404)
                count=con.execute("SELECT COUNT(*) FROM tasks WHERE owner=? AND status IN ('accepted','running')",(owner,)).fetchone()[0]
                if count>=self.settings.max_pending: raise ForgeError('queue_full','工作区队列已满。','等待任务完成后重试。',429)
                con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (id,owner,operation,'accepted','排队中',0,0,now,now,idem,fingerprint,json.dumps(values),sealed,json.dumps(file_ids),group[:100],timeout,retries,None))
                groups=[file_ids] if tool['combine'] else [[f] for f in file_ids]
                for seq,ids in enumerate(groups):
                    con.execute("INSERT INTO items(id,task_id,seq,inputs,status) VALUES(?,?,?,?, 'accepted')",(uid('item'),id,seq,json.dumps(ids)))
                self.event(con,id,'accepted','任务已受理，等待执行。')
        return self.task(owner,id)

    def event(self,con,tid,code,message):
        con.execute('INSERT INTO events(task_id,time,code,message) VALUES(?,?,?,?)',(tid,time.time(),code,message))

    def task(self,owner,id,detail=True):
        with self.connect() as con:
            t=con.execute('SELECT * FROM tasks WHERE id=? AND owner=?',(id,owner)).fetchone()
            if not t: raise ForgeError('task_not_found','任务不存在或无访问权限。','刷新任务列表。',404)
            items=con.execute('SELECT * FROM items WHERE task_id=? ORDER BY seq',(id,)).fetchall()
        result={k:t[k] for k in ['id','tool','status','stage','progress','created','updated','group_name','timeout','retries']}
        result['created_at']=result.pop('created'); result['updated_at']=result.pop('updated')
        result.update(cancel_requested=bool(t['cancel']),params=json.loads(t['params']),input_ids=json.loads(t['inputs']),error=json.loads(t['error']) if t['error'] else None)
        result['counts']={s:sum(i['status']==s for i in items) for s in ['accepted','running','succeeded','failed','cancelled','recoverable']}
        result['item_count']=len(items)
        result['output_ids']=[fid for i in items for fid in json.loads(i['outputs'])]
        if detail:
            result['items']=[{'id':i['id'],'seq':i['seq'],'status':i['status'],'attempt':i['attempt'],'input_ids':json.loads(i['inputs']),'output_ids':json.loads(i['outputs']),'error':json.loads(i['error']) if i['error'] else None} for i in items]
            result['inputs']=[self.file(owner,f) for f in result['input_ids']]
            result['outputs']=[self.file(owner,f) for f in result['output_ids']]
        return result

    def tasks(self,owner,status='',search='',limit=30,offset=0,group=''):
        terms=['owner=?']; args=[owner]
        if status: terms.append('status=?'); args.append(status)
        if group: terms.append('group_name=?'); args.append(group)
        if search:
            terms.append('(id LIKE ? OR tool LIKE ? OR group_name LIKE ?)'); args.extend(['%'+search+'%']*3)
        where=' AND '.join(terms)
        with self.connect() as con:
            count=con.execute('SELECT COUNT(*) FROM tasks WHERE '+where,args).fetchone()[0]
            rows=con.execute('SELECT id FROM tasks WHERE '+where+' ORDER BY created DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        return {'tasks':[self.task(owner,r['id'],False) for r in rows],'total':count,'offset':offset,'limit':limit}

    def logs(self,owner,tid):
        self.task(owner,tid,False)
        with self.connect() as con:
            return [dict(x) for x in con.execute('SELECT time,code,message FROM events WHERE task_id=? ORDER BY id DESC LIMIT 100',(tid,))][::-1]

    def cancel(self,owner,tid):
        self.task(owner,tid,False)
        with self.tx() as con:
            row=con.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()
            if row['status'] in ACTIVE:
                if row['status']=='accepted':
                    con.execute("UPDATE tasks SET status='cancelled',cancel=1,stage='已取消',updated=? WHERE id=?",(time.time(),tid))
                    con.execute("UPDATE items SET status='cancelled' WHERE task_id=? AND status='accepted'",(tid,))
                else: con.execute("UPDATE tasks SET cancel=1,stage='正在停止',updated=? WHERE id=?",(time.time(),tid))
                self.event(con,tid,'cancel_requested','已请求取消；正在执行的进程停止后确认。')
        return self.task(owner,tid)

    def resume(self,owner,tid):
        self.task(owner,tid,False)
        with self.tx() as con:
            row=con.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()
            if row['status'] not in {'failed','partial','cancelled','recoverable'}:
                raise ForgeError('cannot_resume','任务仍在执行或已经成功。','等待取消完成后重试；成功结果可直接使用。',409)
            con.execute("UPDATE tasks SET status='accepted',stage='等待恢复',cancel=0,error=NULL,updated=? WHERE id=?",(time.time(),tid))
            con.execute("UPDATE items SET status='accepted',error=NULL WHERE task_id=? AND status!='succeeded'",(tid,))
            self.event(con,tid,'resumed','保留成功项，重新执行其余项目。')
        return self.task(owner,tid)

    def storage(self,owner):
        with self.connect() as con:
            n,b=con.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM files WHERE owner=?',(owner,)).fetchone()
        return {'files':n,'used_bytes':b,'quota_bytes':self.settings.quota_bytes,'max_file_bytes':self.settings.max_file_bytes,'retention_days':self.settings.retention_days,
                'concurrency':self.settings.concurrency,'timeout':self.settings.timeout,'max_pending':self.settings.max_pending,'location':'service_workspace','content_quality':'处理完成不代表内容质量审核通过。'}

    def templates(self,owner):
        with self.connect() as con:
            rows=con.execute('SELECT * FROM templates WHERE owner=? ORDER BY created DESC',(owner,)).fetchall()
        return [{'id':r['id'],'name':r['name'],'tool':r['tool'],'params':json.loads(r['params'])} for r in rows]

    def save_template(self,owner,name,tool,params):
        operation,values=validate(tool,params)
        values={k:v for k,v in values.items() if not operation['schema']['properties'].get(k,{}).get('sensitive')}
        with self.tx() as con:
            if con.execute('SELECT COUNT(*) FROM templates WHERE owner=?',(owner,)).fetchone()[0]>=100: raise ForgeError('template_limit','最多保存 100 个模板。')
            id=uid('template')
            con.execute('INSERT INTO templates VALUES(?,?,?,?,?,?)',(id,owner,name[:100],tool,json.dumps(values),time.time()))
        return {'id':id,'name':name,'tool':tool,'params':values}

    def cleanup(self,owner,days=None,dry_run=True):
        import shutil
        cutoff=time.time()-86400*(self.settings.retention_days if days is None else days)
        with self.tx() as con:
            active=set()
            for t in con.execute("SELECT inputs FROM tasks WHERE owner=? AND status IN ('accepted','running')",(owner,)):
                active.update(json.loads(t['inputs']))
            rows=[r for r in con.execute('SELECT * FROM files WHERE owner=? AND created<?',(owner,cutoff)) if r['id'] not in active]
            ids={r['id'] for r in rows}
            # Delete a terminal task only when its inputs/outputs are all eligible.
            eligible=[]
            for t in con.execute("SELECT * FROM tasks WHERE owner=? AND status NOT IN ('accepted','running')",(owner,)):
                outputs=[f for r in con.execute('SELECT outputs FROM items WHERE task_id=?',(t['id'],)) for f in json.loads(r['outputs'])]
                related=set(json.loads(t['inputs'])+outputs)
                if related<=ids: eligible.append(t['id'])
                else: ids-=related
            rows=[r for r in rows if r['id'] in ids]
            result={'dry_run':dry_run,'files':len(rows),'bytes':sum(r['size'] for r in rows),'tasks':len(eligible)}
            if not dry_run:
                for tid in eligible:
                    con.execute('DELETE FROM events WHERE task_id=?',(tid,)); con.execute('DELETE FROM items WHERE task_id=?',(tid,)); con.execute('DELETE FROM tasks WHERE id=?',(tid,))
                for r in rows:
                    (self.root/r['path']).unlink(missing_ok=True); con.execute('DELETE FROM files WHERE id=?',(r['id'],))
        return result
