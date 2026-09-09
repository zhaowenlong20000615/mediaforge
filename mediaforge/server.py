from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse
import json,os,base64,uuid,mimetypes
from .core import TaskStore,TOOLS,doctor
store=TaskStore()
class H(BaseHTTPRequestHandler):
 def _send(self,code,payload,ctype='application/json'):
  b=payload if isinstance(payload,bytes) else json.dumps(payload,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):
  path=urlparse(self.path).path
  try:
   if path=='/healthz':return self._send(200,{'status':'ok'})
   if path=='/readyz':return self._send(200,{'status':'ready','data_dir':str(store.root)})
   if path=='/version':return self._send(200,{'name':'mediaforge','version':'0.1.0'})
   if path=='/api/tools':return self._send(200,{'tools':TOOLS})
   if path=='/api/doctor':return self._send(200,{'checks':doctor()})
   if path=='/api/tasks':return self._send(200,{'tasks':store.list()})
   if path.startswith('/api/tasks/') and path.endswith('/download'):
    tid=path.split('/')[3]; name=urlparse(self.path).query.replace('file=',''); t=store.get(tid); matches=[o for o in t.get('outputs',[]) if o.get('name')==name];
    if not matches:return self._send(404,{'error':'output_not_found'})
    fp=matches[0]['path']; return self._send(200,open(fp,'rb').read(),mimetypes.guess_type(fp)[0] or 'application/octet-stream')
   if path.startswith('/api/tasks/'):
    tid=path.split('/')[3];return self._send(200,store.preview(tid))
   if path=='/' or path=='/index.html':return self._send(200,open(os.path.join(os.path.dirname(__file__),'../static/index.html'),'rb').read(),'text/html; charset=utf-8')
   if path.startswith('/static/'):
    fp=os.path.join(os.path.dirname(__file__),'..',path[1:]);return self._send(200,open(fp,'rb').read(),'text/css' if fp.endswith('.css') else 'application/javascript')
   return self._send(404,{'error':'not_found'})
  except (KeyError,FileNotFoundError) as e:return self._send(404,{'error':str(e)})
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(n) or '{}');path=urlparse(self.path).path
   if path=='/api/upload':
    name=os.path.basename(body.get('name','upload.bin')); data=base64.b64decode(body.get('data','')); dest=store.inputs/(uuid.uuid4().hex+'_'+name); dest.write_bytes(data); return self._send(201,store.inspect(dest))
   if path=='/api/tasks':return self._send(202,store.submit(body['tool'],body.get('files',[]),body.get('params'),body.get('idempotency_key')))
   if path.endswith('/cancel'):return self._send(200,store.cancel(path.split('/')[3]))
   if path.endswith('/resume'):return self._send(200,store.resume(path.split('/')[3]))
   return self._send(404,{'error':'not_found'})
  except Exception as e:return self._send(400,{'error':type(e).__name__,'message':str(e)})
def main():
 port=int(os.getenv('MEDIAFORGE_PORT','18081'));ThreadingHTTPServer(('0.0.0.0',port),H).serve_forever()
if __name__=='__main__':main()
