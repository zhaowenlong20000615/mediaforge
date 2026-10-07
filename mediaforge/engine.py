"""One scheduler per data directory; item execution is isolated in process groups."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from filelock import FileLock, Timeout
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from .errors import ForgeError, safe_error
from .files import inspect
from .store import uid


class Engine:
    def __init__(self,store):
        self.store=store; self.stop_event=threading.Event(); self.thread=None
        self.lock=FileLock(str(store.root/'worker.lock'))
        self.pool=ThreadPoolExecutor(max_workers=store.settings.concurrency,thread_name_prefix='mediaforge-worker')
        self.futures={}

    def start(self):
        try: self.lock.acquire(timeout=0)
        except Timeout: raise RuntimeError('A MediaForge worker already owns this data directory.')
        with self.store.tx() as con:
            rows=con.execute("SELECT id FROM tasks WHERE status='running'").fetchall()
            for row in rows:
                con.execute("UPDATE tasks SET status='recoverable',stage='服务重启，可恢复',updated=? WHERE id=?",(time.time(),row['id']))
                con.execute("UPDATE items SET status='recoverable' WHERE task_id=? AND status='running'",(row['id'],))
                self.store.event(con,row['id'],'restart_recovery','服务上次中断；成功结果已保留，可恢复剩余项目。')
        # The exclusive worker lease ensures these are abandoned private job
        # directories; all published outputs live under files/, never jobs/.
        for path in (self.store.root/'jobs').iterdir():
            if path.is_dir() and not path.is_symlink() and path.name.startswith('task_'):
                shutil.rmtree(path)
        self.thread=threading.Thread(target=self._loop,daemon=True,name='mediaforge-scheduler')
        self.thread.start()

    @property
    def ready(self): return self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set()

    def _loop(self):
        next_cleanup=time.monotonic()+60
        while not self.stop_event.is_set():
            self.futures={k:f for k,f in self.futures.items() if not f.done()}
            while len(self.futures)<self.store.settings.concurrency and not self.stop_event.is_set():
                with self.store.tx() as con:
                    row=con.execute("SELECT id FROM tasks WHERE status='accepted' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
                    if not row: break
                    con.execute("UPDATE tasks SET status='running',stage='准备处理',updated=? WHERE id=? AND status='accepted'",(time.time(),row['id']))
                self.futures[row['id']]=self.pool.submit(self._task,row['id'])
            if time.monotonic()>next_cleanup:
                try:
                    with self.store.connect() as con: owners=[r[0] for r in con.execute('SELECT DISTINCT owner FROM tokens')]
                    for owner in owners: self.store.cleanup(owner,dry_run=False)
                except Exception: pass  # Never stops active processing; explicit cleanup exposes errors.
                next_cleanup=time.monotonic()+3600
            self.stop_event.wait(.15)

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(3)
        self.pool.shutdown(wait=True,cancel_futures=False)
        self.lock.release()

    def _row(self,tid):
        with self.store.connect() as con: return con.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()

    def _cancelled(self,tid): return bool(self._row(tid)['cancel'])

    def _task(self,tid):
        t=self._row(tid)
        try:
            with self.store.connect() as con: items=con.execute("SELECT * FROM items WHERE task_id=? AND status!='succeeded' ORDER BY seq",(tid,)).fetchall()
            for item in items:
                if self.stop_event.is_set() or self._cancelled(tid): break
                for retry in range(t['retries']+1):
                    with self.store.tx() as con:
                        con.execute("UPDATE items SET status='running',attempt=attempt+1,error=NULL WHERE id=?",(item['id'],))
                        self.store.event(con,tid,'item_started',f'正在处理第 {item["seq"]+1} 项。')
                    try:
                        self._item(t,item)
                        break
                    except ForgeError as e:
                        error=e.payload()
                        with self.store.tx() as con:
                            state='recoverable' if self.stop_event.is_set() else 'cancelled' if self._cancelled(tid) else 'failed'
                            con.execute('UPDATE items SET status=?,error=? WHERE id=?',(state,json.dumps(error),item['id']))
                            self.store.event(con,tid,error['code'],error['message'])
                        if state!='failed' or not e.retryable or retry>=t['retries']: break
                        until=time.monotonic()+min(8,2**retry)
                        while time.monotonic()<until and not self.stop_event.is_set() and not self._cancelled(tid): time.sleep(.1)
                        if self.stop_event.is_set() or self._cancelled(tid): break
            self._finalize(tid)
        except BaseException as e:
            with self.store.tx() as con:
                con.execute("UPDATE tasks SET status='recoverable',stage='执行中断，可恢复',error=?,updated=? WHERE id=?",(json.dumps(safe_error(e)),time.time(),tid))
                con.execute("UPDATE items SET status='recoverable' WHERE task_id=? AND status='running'",(tid,))
                self.store.event(con,tid,'worker_interrupted','任务中断，成功项目已保留。')

    def _finalize(self,tid):
        with self.store.tx() as con:
            t=con.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            rows=con.execute('SELECT status,error FROM items WHERE task_id=?',(tid,)).fetchall()
            succeeded=sum(x['status']=='succeeded' for x in rows)
            if t['cancel']:
                state='cancelled'; stage='已取消；已完成结果保留'
                con.execute("UPDATE items SET status='cancelled' WHERE task_id=? AND status IN ('accepted','running')",(tid,))
            elif self.stop_event.is_set(): state='recoverable'; stage='服务中断，可恢复'
            elif succeeded==len(rows) and rows: state='succeeded'; stage='处理完成，请检查结果'
            elif succeeded: state='partial'; stage='部分完成，可重试失败项'
            else: state='failed'; stage='处理失败'
            error=next((r['error'] for r in rows if r['error']),None)
            progress=100 if state in {'succeeded','partial','failed'} else 100*succeeded/max(1,len(rows))
            con.execute('UPDATE tasks SET status=?,stage=?,progress=?,error=?,updated=? WHERE id=?',(state,stage,progress,error,time.time(),tid))
            self.store.event(con,tid,state,stage)

    @staticmethod
    def terminate(proc):
        if proc.poll() is not None: return
        try:
            if os.name=='posix': os.killpg(proc.pid,signal.SIGTERM)
            else: proc.terminate()
            try: proc.wait(2)
            except subprocess.TimeoutExpired:
                if os.name=='posix': os.killpg(proc.pid,signal.SIGKILL)
                else: subprocess.run(['taskkill','/F','/T','/PID',str(proc.pid)],capture_output=True)
                proc.wait(3)
        except ProcessLookupError: pass

    def _item(self,t,item):
        from .catalog import CATALOG
        from .dependencies import ensure
        params=json.loads(t['params'])
        params.update(json.loads(self.store.cipher.decrypt(t['secret'].encode())))
        inputs=[self.store.file(t['owner'],id,True) for id in json.loads(item['inputs'])]
        ensure(CATALOG[t['tool']],params,[f['kind'] for f in inputs])
        work=self.store.root/'jobs'/t['id']/item['id']/uid('attempt')
        work.mkdir(parents=True,mode=0o700)
        request={'operation':t['tool'],'params':params,'inputs':inputs,'work':str(work),'seq':item['seq'],
                 'max_outputs':self.store.settings.max_outputs,'max_file_bytes':self.store.settings.max_file_bytes}
        req=work/'request.json'; req.write_text(json.dumps(request)); req.chmod(0o600)
        env=os.environ.copy()
        # Each runner has an independent document profile and temporary files.
        env['TMPDIR']=str(work); env['TEMP']=str(work); env['TMP']=str(work)
        for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:env[name]='2'
        proc=None
        try:
            with (work/'runner.log').open('wb') as log:
                proc=subprocess.Popen([sys.executable,'-m','mediaforge.runner',str(req)],stdout=log,stderr=log,env=env,start_new_session=os.name=='posix')
                end=time.monotonic()+t['timeout']; last=0
                while proc.poll() is None:
                    if self.stop_event.is_set() or self._cancelled(t['id']):
                        self.terminate(proc)
                        raise ForgeError('cancelled','处理已停止。','可以恢复尚未完成的项目。')
                    if time.monotonic()>end:
                        self.terminate(proc)
                        raise ForgeError('timeout','任务超过设置的处理时限。','缩小文件或提高处理时限后重试。',408,True)
                    if time.monotonic()-last>.3:
                        last=time.monotonic()
                        try:
                            progress=json.loads((work/'progress.json').read_text())
                            fraction=max(0,min(99,float(progress['percent'])))
                            stage=str(progress['stage'])[:80]
                            with self.store.tx() as con:
                                done=con.execute("SELECT COUNT(*) FROM items WHERE task_id=? AND status='succeeded'",(t['id'],)).fetchone()[0]
                                total=con.execute('SELECT COUNT(*) FROM items WHERE task_id=?',(t['id'],)).fetchone()[0]
                                con.execute("UPDATE tasks SET progress=?,stage=?,updated=? WHERE id=? AND cancel=0 AND status='running'",((done+fraction/100)*100/total,stage,time.time(),t['id']))
                        except (OSError,ValueError,KeyError): pass
                    time.sleep(.1)
            if self.stop_event.is_set() or self._cancelled(t['id']): raise ForgeError('cancelled','处理已停止。')
            result_path=work/'result.json'
            if not result_path.exists(): raise ForgeError('runner_failed','处理进程意外退出。','检查文件是否过大或损坏；可重试该项。')
            result=json.loads(result_path.read_text())
            if not result.get('ok'):
                e=result.get('error',{})
                raise ForgeError(e.get('code','processing_failed'),e.get('message','处理失败。'),e.get('action',''),retryable=e.get('retryable',False))
            outputs=result.get('outputs',[])
            if not outputs or len(outputs)>self.store.settings.max_outputs: raise ForgeError('invalid_outputs','没有有效结果或输出数量过多。')
            prepared=[]
            for out in outputs:
                path=Path(out['path']).resolve()
                if not path.is_relative_to(work) or not path.is_file(): raise ForgeError('invalid_output_path','处理结果路径不合法。')
                if path.stat().st_size>self.store.settings.max_file_bytes: raise ForgeError('output_too_large','输出超过单文件限制。','降低分辨率或拆分任务。',413)
                name=out['name']
                if not CATALOG[t['tool']]['combine'] and t['tool']!='image-rename':
                    stem=Path(inputs[0]['name']).stem.encode('utf-8')[:140].decode('utf-8','ignore')
                    name=stem+'__'+name
                meta=inspect(path,name); meta['verification']=out.get('verification',{'decoded':True})
                meta['source_file_ids']=[f['id'] for f in inputs]
                meta['quality_review']='required'
                prepared.append((path,name,meta))
            moved=[]
            try:
                with self.store.tx() as con:
                    if con.execute('SELECT cancel FROM tasks WHERE id=?',(t['id'],)).fetchone()[0]: raise ForgeError('cancelled','处理已停止。')
                    used=con.execute('SELECT COALESCE(SUM(size),0) FROM files WHERE owner=?',(t['owner'],)).fetchone()[0]
                    reserved=con.execute('SELECT COALESCE(SUM(bytes),0) FROM reservations WHERE owner=?',(t['owner'],)).fetchone()[0]
                    if used+reserved+sum(x[2]['size'] for x in prepared)>self.store.settings.quota_bytes: raise ForgeError('quota_exceeded','输出需要的空间超过工作区配额。','清理历史结果后恢复任务。',413)
                    ids=[]
                    for path,name,meta in prepared:
                        id=uid('file'); rel='files/'+id+Path(name).suffix.lower(); target=self.store.root/rel
                        path.replace(target); target.chmod(0o600); moved.append(target)
                        con.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)',(id,t['owner'],name,rel,meta['size'],json.dumps(meta),time.time(),t['id']))
                        ids.append(id)
                    con.execute("UPDATE items SET status='succeeded',outputs=?,error=NULL WHERE id=?",(json.dumps(ids),item['id']))
                    self.store.event(con,t['id'],'item_succeeded',f'第 {item["seq"]+1} 项完成；结果可读取，需人工确认质量。')
            except BaseException:
                for path in moved: path.unlink(missing_ok=True)
                raise
        finally:
            if proc and proc.poll() is None: self.terminate(proc)
            shutil.rmtree(work,ignore_errors=True)
