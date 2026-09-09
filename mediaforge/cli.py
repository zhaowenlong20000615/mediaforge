import argparse,json,sys
from .core import TaskStore,TOOLS,doctor

def out(v,args): print(json.dumps(v,ensure_ascii=False,indent=2) if args.json else (v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2)))
def main(argv=None):
 argv=list(argv) if argv is not None else sys.argv[1:]
 json_after='--json' in argv
 argv=[x for x in argv if x!='--json']
 p=argparse.ArgumentParser(prog='mediaforge',description='MediaForge 本地媒体与文档工作台')
 p.add_argument('--json',action='store_true',help='输出 JSON'); sub=p.add_subparsers(dest='cmd',required=True)
 sub.add_parser('tools',help='列出工具'); sub.add_parser('doctor',help='检查 FFmpeg/Poppler/LibreOffice/OCR/ASR')
 q=sub.add_parser('inspect',help='检查文件');q.add_argument('file')
 s=sub.add_parser('submit',help='创建处理任务');s.add_argument('tool');s.add_argument('files',nargs='+');s.add_argument('--param',action='append',default=[]);s.add_argument('--idempotency-key')
 l=sub.add_parser('tasks',help='查询任务');l.add_argument('--status');l.add_argument('--limit',type=int,default=50)
 for name,help_ in [('cancel','取消任务'),('resume','恢复任务'),('preview','查看结果')]: x=sub.add_parser(name,help=help_);x.add_argument('task_id')
 a=p.parse_args(argv); a.json = bool(getattr(a,'json',False) or json_after); store=TaskStore()
 try:
  if a.cmd=='tools':v={'tools':TOOLS,'count':len(TOOLS)}
  elif a.cmd=='doctor':v={'checks':doctor()}
  elif a.cmd=='inspect':v=store.inspect(a.file)
  elif a.cmd=='submit':
   params={}
   for item in a.param:
    k,_,val=item.partition('=');params[k]=val
   v=store.submit(a.tool,a.files,params,a.idempotency_key)
  elif a.cmd=='tasks':v={'tasks':store.list(a.limit,a.status)}
  elif a.cmd=='cancel':v=store.cancel(a.task_id)
  elif a.cmd=='resume':v=store.resume(a.task_id)
  else:v=store.preview(a.task_id)
  out(v,a);return 0
 except (FileNotFoundError,ValueError,KeyError) as e:
  payload={'error':type(e).__name__,'message':str(e),'next':'检查路径、工具 ID 与 doctor 输出'}; print(json.dumps(payload,ensure_ascii=False) if a.json else payload['message'],file=sys.stderr);return 2
 except Exception as e: print(json.dumps({'error':'internal','message':str(e)},ensure_ascii=False),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
