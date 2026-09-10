"""Authenticated HTTP transport shared by CLI and MCP."""
from pathlib import Path
from urllib.parse import urlsplit,quote
import json
import os
import time
import httpx
from .errors import ForgeError


class Client:
    def __init__(self,server=None,token_file=None):
        self.base=(server or os.getenv('MEDIAFORGE_URL','http://127.0.0.1:18081')).rstrip('/')
        parsed=urlsplit(self.base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ForgeError('invalid_server','服务地址不能包含凭证、查询参数或片段。')
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
        try:r=self.http.request(method,self.base+'/'+path.lstrip('/'),**kwargs)
        except httpx.HTTPError:raise ForgeError('connection_failed','无法连接服务。','检查服务地址、HTTPS 证书和服务状态。',503,True)
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
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            task=self.request('GET','api/tasks/'+tid)
            if task['status'] in {'succeeded','partial','failed','cancelled','recoverable'}:return task
            time.sleep(.5)
        raise ForgeError('wait_timeout','等待超时，任务仍可能在服务器继续执行。','查询任务状态；需要停止时显式取消。',408)

    def download(self,id,target):
        path=Path(target).expanduser();path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():raise ForgeError('output_exists','目标文件已经存在。','换一个输出路径，避免覆盖现有文件。',409)
        temp=path.with_name(path.name+'.mediaforge-part')
        try:
            with self.http.stream('GET',self.base+'/api/files/'+id+'/content') as response:
                if response.status_code!=200:raise ForgeError('download_failed','下载请求未获批准。','检查文件权限或保留期。',response.status_code)
                with temp.open('xb') as out:
                    for chunk in response.iter_bytes():out.write(chunk)
            # An atomic hard link avoids overwriting a concurrently created destination.
            os.link(temp,path);temp.unlink()
        except BaseException:
            temp.unlink(missing_ok=True);raise
        return {'file_id':id,'output':str(path.resolve()),'size':path.stat().st_size}
