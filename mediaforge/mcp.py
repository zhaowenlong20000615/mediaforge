import json,sys
from .core import TaskStore,TOOLS,doctor
store=TaskStore()
def call(name,args):
 if name=='list_tools':return {'tools':TOOLS}
 if name=='doctor':return {'checks':doctor()}
 if name=='inspect_file':return store.inspect(args['path'])
 if name=='create_task':return store.submit(args['tool'],args['files'],args.get('params'),args.get('idempotency_key'))
 if name=='get_task_status':return store.get(args['task_id'])
 if name=='cancel_task':return store.cancel(args['task_id'])
 if name=='resume_task':return store.resume(args['task_id'])
 if name=='get_task_preview':return store.preview(args['task_id'])
 if name=='list_tasks':return {'tasks':store.list(args.get('limit',50),args.get('status'))}
 raise ValueError('unknown tool')
def main():
 for line in sys.stdin:
  try:
   req=json.loads(line); mid=req.get('id'); result=call(req.get('method',''),req.get('params',{})); print(json.dumps({'jsonrpc':'2.0','id':mid,'result':result},ensure_ascii=False),flush=True)
  except Exception as e: print(json.dumps({'jsonrpc':'2.0','id':req.get('id') if 'req' in locals() else None,'error':{'code':-32000,'message':str(e)}},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
