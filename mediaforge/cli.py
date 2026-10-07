import argparse
import json
import os
from pathlib import Path
import sys
from .client import Client,resource_id
from .errors import ForgeError

EXIT={'succeeded':0,'partial':3,'failed':4,'cancelled':5,'recoverable':6}


def parameters(args):
    try:
        value=json.loads(getattr(args,'params','{}'))
        if not isinstance(value,dict):raise ValueError()
        for pair in getattr(args,'param',[]) or []:
            k,sep,v=pair.partition('=')
            if not sep:raise ValueError()
            try:value[k]=json.loads(v)
            except ValueError:value[k]=v
        return value
    except (ValueError,TypeError):raise ForgeError('invalid_parameters','参数必须是 JSON 对象，或 key=value。')


class ArgumentParser(argparse.ArgumentParser):
    json_mode=False
    def error(self,message):
        if self.json_mode:
            print(json.dumps({'error':{'code':'invalid_arguments','message':'命令参数无效。','action':'运行 --help 查看用法。'}},ensure_ascii=False),file=sys.stderr)
            raise SystemExit(2)
        super().error(message)

def parser():
    p=ArgumentParser(prog='mediaforge',description='MediaForge · 有权限边界的媒体与文档工作台')
    p.add_argument('--server',help='服务地址（远程必须 HTTPS）')
    p.add_argument('--token-file',help='工作区令牌文件路径')
    p.add_argument('--json',action='store_true',help='结构化 JSON 输出')
    sub=p.add_subparsers(dest='resource',required=True)
    serve=sub.add_parser('serve',help='启动本地 Web/API 和 worker')
    serve.add_argument('--host',default=None);serve.add_argument('--port',type=int,default=None)
    sub.add_parser('doctor',help='诊断服务、依赖、模型与存储')
    sub.add_parser('mcp',help='启动标准 stdio MCP，连接同一服务')
    tools=sub.add_parser('tools',help='发现工具与参数');tools.add_argument('action',nargs='?',default='list',choices=['list'])
    files=sub.add_parser('files',help='上传、检查、下载文件').add_subparsers(dest='action',required=True)
    f=files.add_parser('upload');f.add_argument('paths',nargs='+')
    f=files.add_parser('get');f.add_argument('id')
    f=files.add_parser('list');f.add_argument('--limit',type=int,default=30)
    f=files.add_parser('download');f.add_argument('id');f.add_argument('--output',required=True)
    task=sub.add_parser('tasks',help='创建、查询、取消、恢复、导出任务').add_subparsers(dest='action',required=True)
    f=task.add_parser('create');f.add_argument('tool');f.add_argument('paths',nargs='*');f.add_argument('--file-id',action='append',default=[])
    f.add_argument('--params',default='{}');f.add_argument('--param',action='append',default=[])
    f.add_argument('--idempotency-key');f.add_argument('--group',default='');f.add_argument('--timeout',type=int,default=None);f.add_argument('--retries',type=int,default=0);f.add_argument('--wait',action='store_true')
    f=task.add_parser('list');f.add_argument('--status',default='');f.add_argument('--search',default='');f.add_argument('--group',default='');f.add_argument('--limit',type=int,default=30);f.add_argument('--offset',type=int,default=0)
    for name in ['get','logs','cancel','resume','wait']:
        f=task.add_parser(name);f.add_argument('id')
        if name=='resume':f.add_argument('--wait',action='store_true')
        if name=='wait':f.add_argument('--timeout',type=int,default=3600)
    f=task.add_parser('export');f.add_argument('ids',nargs='+');f.add_argument('--wait',action='store_true')
    templates=sub.add_parser('templates',help='参数模板').add_subparsers(dest='action',required=True)
    templates.add_parser('list')
    f=templates.add_parser('save');f.add_argument('name');f.add_argument('tool');f.add_argument('--params',default='{}');f.add_argument('--param',action='append',default=[])
    f=templates.add_parser('delete');f.add_argument('id')
    storage=sub.add_parser('storage',help='配额和保留期').add_subparsers(dest='action',required=True)
    storage.add_parser('status')
    f=storage.add_parser('cleanup');f.add_argument('--days',type=int,default=7);f.add_argument('--execute',action='store_true',help='执行清理；默认仅预览')
    f=sub.add_parser('workspaces',help='管理员创建隔离工作区').add_subparsers(dest='action',required=True).add_parser('create');f.add_argument('name')
    return p


def main(argv=None):
    argv=list(argv if argv is not None else sys.argv[1:])
    as_json='--json' in argv;argv=[x for x in argv if x!='--json']
    ArgumentParser.json_mode=as_json
    p=parser()
    try:
        a=p.parse_args(argv)
        if a.resource=='serve':
            if a.host:os.environ['MEDIAFORGE_HOST']=a.host
            if a.port:os.environ['MEDIAFORGE_PORT']=str(a.port)
            from .server import main as serve
            serve();return 0
        if a.resource=='mcp':
            from .mcp import main as mcp
            mcp(server=a.server,token_file=a.token_file);return 0
        c=Client(a.server,a.token_file);r=a.resource;act=getattr(a,'action','')
        code=0
        if hasattr(a,'id'):resource_id(a.id,{'tasks':'task','files':'file','templates':'template'}[r])
        if r=='tools':result=c.request('GET','api/tools')
        elif r=='doctor':result=c.request('GET','api/doctor')
        elif r=='files':
            if act=='upload':result={'files':[c.upload(f) for f in a.paths]}
            elif act=='download':result=c.download(a.id,a.output)
            elif act=='get':result=c.request('GET','api/files/'+a.id)
            else:result=c.request('GET','api/files',params={'limit':a.limit})
        elif r=='tasks':
            if act=='create':
                values=parameters(a)
                ids=a.file_id+[c.upload(f)['id'] for f in a.paths]
                result=c.request('POST','api/tasks',json={'tool':a.tool,'file_ids':ids,'params':values,'group':a.group,'timeout':a.timeout,'retries':a.retries,'idempotency_key':a.idempotency_key})
            elif act=='list':result=c.request('GET','api/tasks',params={k:getattr(a,k) for k in ['status','search','group','limit','offset']})
            elif act=='get':result=c.request('GET','api/tasks/'+a.id)
            elif act=='logs':result=c.request('GET','api/tasks/'+a.id+'/logs')
            elif act in {'cancel','resume'}:result=c.request('POST','api/tasks/'+a.id+'/'+act)
            elif act=='export':result=c.request('POST','api/exports',json={'task_ids':a.ids})
            elif act=='wait':result=c.wait(a.id,a.timeout);code=EXIT[result['status']]
            if getattr(a,'wait',False):result=c.wait(result['id']);code=EXIT[result['status']]
        elif r=='templates':
            if act=='list':result=c.request('GET','api/templates')
            elif act=='save':result=c.request('POST','api/templates',json={'name':a.name,'tool':a.tool,'params':parameters(a)})
            else:result=c.request('DELETE','api/templates/'+a.id)
        elif r=='storage':
            result=c.request('GET','api/me')['storage'] if act=='status' else c.request('POST','api/cleanup',json={'days':a.days,'dry_run':not a.execute})
        else:result=c.request('POST','api/workspaces',json={'name':a.name})
        print(json.dumps(result,ensure_ascii=False,indent=2 if not as_json else None))
        return code
    except ForgeError as e:
        print(json.dumps({'error':e.payload()},ensure_ascii=False),file=sys.stderr)
        return 7 if e.code=='wait_timeout' else 2
    except (OSError,ValueError,KeyError):
        print(json.dumps({'error':{'code':'client_error','message':'客户端参数或本地文件操作失败。','action':'检查输入参数、输出路径和文件权限。'}},ensure_ascii=False),file=sys.stderr)
        return 2
    except KeyboardInterrupt:return 130

if __name__=='__main__':sys.exit(main())
