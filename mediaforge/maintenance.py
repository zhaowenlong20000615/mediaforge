"""Bounded, per-workspace cleanup status. Never serialize exception text or tokens."""
from pathlib import Path
from copy import deepcopy
import errno
import json
import os
import sqlite3
import threading
import time
from .errors import safe_error


def cleanup_error(exc):
    error=safe_error(exc)
    if isinstance(exc,PermissionError):
        error.update(code='cleanup_permission',message='清理文件权限不足。',action='请管理员检查本项目数据目录权限。')
    elif isinstance(exc,sqlite3.OperationalError) and getattr(exc,'sqlite_errorcode',0) in {sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED}:
        error.update(code='cleanup_database_busy',message='清理时数据库忙。',action='稍后自动重试；活动任务继续。',retryable=True)
    elif error['code']=='processing_failed':
        error.update(code='cleanup_failed',message='后台清理未完成。',action='查看维护状态并检查存储和目录；稍后自动重试。')
    return error


class Maintenance:
    def __init__(self,store):
        self.store=store;self.path=store.root/'maintenance.json';self.lock=threading.RLock()
        self.running=False;self.persistence_error=None;self.discovery_error=None
        try:self.rows=json.loads(self.path.read_text())
        except FileNotFoundError:self.rows={}
        except (OSError,ValueError):
            self.rows={};self.persistence_error={'code':'maintenance_status_unreadable','message':'上次维护状态无法读取；本轮完成后重新保存。'}
        self.discovery_error=self.rows.get('_service',{}).get('error')

    def status(self,owner):
        with self.lock:
            row=deepcopy(self.rows.get(owner,{'state':'not_run','last_success':None,'last_failure':None,'backlog':None}))
            if row.get('state')=='running' and not self.running:row['state']='interrupted'
            return {**row,'interval_seconds':3600,'retention_days':self.store.settings.retention_days,
                    'persistence_error':self.persistence_error,'discovery_error':self.discovery_error}

    def _save(self):
        temp=self.path.with_suffix('.next')
        try:
            with temp.open('w') as stream:
                os.chmod(temp,0o600);json.dump(self.rows,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,self.path);self.persistence_error=None
        except OSError as exc:self.persistence_error=cleanup_error(exc)

    def run_once(self):
        with self.lock:
            if self.running:return
            self.running=True
        try:
            with self.store.connect() as con:owners=[r[0] for r in con.execute('SELECT DISTINCT owner FROM tokens')]
            self.discovery_error=None
            with self.lock:self.rows['_service']={'last_success':time.time(),'error':None};self._save()
            for owner in owners:
                with self.lock:
                    row=self.rows.setdefault(owner,{'last_success':None,'last_failure':None,'backlog':None})
                    row.update(state='running',last_attempt=time.time());self._save()
                try:
                    plan=self.store.cleanup(owner,dry_run=True)
                    with self.lock:row['backlog']={**plan,'measured_at':time.time()};self._save()
                    result=self.store.cleanup(owner,dry_run=False)
                    remaining=self.store.cleanup(owner,dry_run=True)
                    with self.lock:
                        row.update(state='ok',last_success=time.time(),error=None,last_result=result,
                                   backlog={**remaining,'measured_at':time.time()});self._save()
                except Exception as exc:
                    with self.lock:
                        row.update(state='failed',last_failure=time.time(),error=cleanup_error(exc));self._save()
                    print(json.dumps({'project_id':'local.mediaforge','event':'cleanup_failed','error':cleanup_error(exc)},ensure_ascii=False),flush=True)
        except Exception as exc:
            with self.lock:
                self.discovery_error=cleanup_error(exc)
                self.rows['_service']={**self.rows.get('_service',{}),'last_failure':time.time(),'error':self.discovery_error};self._save()
            print(json.dumps({'project_id':'local.mediaforge','event':'cleanup_discovery_failed','error':cleanup_error(exc)},ensure_ascii=False),flush=True)
        finally:
            with self.lock:self.running=False
