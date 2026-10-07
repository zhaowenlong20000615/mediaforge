"""Authenticated HTTP transport shared by CLI and MCP."""
from pathlib import Path
from urllib.parse import urlsplit,quote
import json
import logging
import hashlib
import tempfile
import re
import os
import time
import httpx
from .errors import ForgeError


def resource_id(value,prefix):
    if not isinstance(value,str) or not re.fullmatch(prefix+r'_[A-Za-z0-9]+',value):
        raise ForgeError('invalid_id','资源编号无效。','使用文件或任务查询返回的 ID。')
    return value


class Client:
    def __init__(self,server=None,token_file=None):
        # MCP SDK enables INFO logging globally; URLs can contain user filenames.
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)
        self.base=(server or os.getenv('MEDIAFORGE_URL','http://127.0.0.1:18081')).rstrip('/')
        parsed=urlsplit(self.base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ForgeError('invalid_server','服务地址不能包含凭证、查询参数或片段。')
        if parsed.scheme not in {'http','https'} or not parsed.hostname:
            raise ForgeError('invalid_server','请输入完整的 HTTP 或 HTTPS 服务地址。')
        if parsed.scheme!='https' and parsed.hostname not in {'127.0.0.1','localhost','::1'}:
            raise ForgeError('https_required','远程服务必须使用 HTTPS。','使用部署的 HTTPS 地址。')
        configured=token_file or os.getenv('MEDIAFORGE_TOKEN_FILE')
        if not configured and parsed.hostname not in {'127.0.0.1','localhost','::1'}:
            raise ForgeError('token_required','远程访问需要工作区令牌文件。','配置 MEDIAFORGE_TOKEN_FILE。',401)
        path=Path(configured or str(Path(os.getenv('MEDIAFORGE_DATA','~/.mediaforge')).expanduser()/'admin.token')).expanduser()
        try:token=path.read_text().strip()
        except OSError:raise ForgeError('token_required','无法读取访问令牌文件。','启动本地服务，或配置 MEDIAFORGE_TOKEN_FILE。',401)
        self.http=httpx.Client(base_url=self.base,headers={'Authorization':'Bearer '+token},timeout=httpx.Timeout(60,read=120,write=600),trust_env=False)

    def request(self,method,path,**kwargs):
        body=kwargs.get('json')
        safe_retry=method.upper()=='GET' or (method.upper()=='POST' and path.strip('/') in {'api/tasks','api/exports'} and isinstance(body,dict) and bool(body.get('idempotency_key')))
        for attempt in range(2 if safe_retry else 1):
            try:
                r=self.http.request(method,self.base+'/'+path.lstrip('/'),**kwargs)
                break
            except httpx.HTTPError:
                if safe_retry and attempt==0:time.sleep(.25);continue
                raise ForgeError('connection_failed','无法连接服务。','检查服务地址、HTTPS 证书和服务状态。',503,True)
        if r.status_code>=400:
            try:e=r.json().get('error',{})
            except ValueError:e={}
            raise ForgeError(e.get('code','request_failed'),e.get('message','服务拒绝了请求。'),e.get('action','检查权限和参数。'),r.status_code,e.get('retryable',False))
        try:return r.json()
        except ValueError:raise ForgeError('invalid_response','服务返回了无效响应。','检查服务版本与网络状态。',502)

    def upload(self,path):
        p=Path(path).expanduser()
        if not p.is_file() or p.is_symlink():raise ForgeError('invalid_local_file','本地文件不存在或是符号链接。')
        with p.open('rb') as f:
            return self.request('POST','api/files?name='+quote(p.name,safe=''),content=f,headers={'Content-Length':str(p.stat().st_size),'Content-Type':'application/octet-stream'})

    def wait(self,tid,timeout=3600):
        tid=resource_id(tid,'task')
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            task=self.request('GET','api/tasks/'+tid)
            if task['status'] in {'succeeded','partial','failed','cancelled','recoverable'}:return task
            time.sleep(.5)
        raise ForgeError('wait_timeout','等待超时，任务仍可能在服务器继续执行。','查询任务状态；需要停止时显式取消。',408)

    def download(self,id,target):
        id=resource_id(id,'file')
        path=Path(target).expanduser();path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() or path.is_symlink():raise ForgeError('output_exists','目标文件已经存在。','换一个输出路径，避免覆盖现有文件。',409)
        meta=self.request('GET','api/files/'+id)
        temp=None;digest=hashlib.sha256();size=0
        try:
            with self.http.stream('GET',self.base+'/api/files/'+id+'/content') as response:
                if response.status_code!=200:raise ForgeError('download_failed','下载请求未获批准。','检查文件权限或保留期。',response.status_code)
                with tempfile.NamedTemporaryFile(mode='wb',prefix='.mediaforge-',suffix='.part',dir=path.parent,delete=False) as out:
                    temp=Path(out.name)
                    for chunk in response.iter_bytes():
                        size+=len(chunk);digest.update(chunk);out.write(chunk)
                        if size>meta['size']:raise ForgeError('download_integrity','下载内容大小不一致。','重新下载；原文件不会被覆盖。',502)
            if size!=meta['size'] or digest.hexdigest()!=meta['sha256']:
                raise ForgeError('download_integrity','下载校验失败。','重新下载；原文件不会被覆盖。',502)
            # An atomic hard link avoids overwriting a concurrently created destination.
            os.link(temp,path);temp.unlink()
        except httpx.HTTPError:
            raise ForgeError('download_interrupted','下载中断。','检查网络后重新下载。',503,True)
        except FileExistsError:
            raise ForgeError('output_exists','目标文件已经存在。','换一个输出路径。',409)
        finally:
            if temp is not None:temp.unlink(missing_ok=True)
        return {'file_id':id,'output':str(path.resolve()),'size':size,'sha256':digest.hexdigest()}
