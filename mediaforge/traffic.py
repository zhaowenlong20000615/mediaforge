"""Count application body bytes without buffering, query strings or credentials."""
import json,time,secrets


class TrafficLog:
    def __init__(self,app):self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        request_id=secrets.token_hex(8);scope.setdefault('state',{})['request_id']=request_id
        received=sent=0;status=500;cache=None;complete=False
        async def read():
            nonlocal received
            message=await receive()
            if message['type']=='http.request':received+=len(message.get('body',b''))
            return message
        async def write(message):
            nonlocal sent,status,cache,complete
            if message['type']=='http.response.start':
                status=message['status'];headers=list(message.get('headers',[]));headers=[(k,v) for k,v in headers if k.lower()!=b'x-request-id'];headers.append((b'x-request-id',request_id.encode()));message={**message,'headers':headers}
                cache=next((v.decode() for k,v in headers if k.lower()==b'x-preview-cache'),None)
            elif message['type']=='http.response.body':
                sent+=len(message.get('body',b''));complete=not message.get('more_body',False)
            await send(message)
        try:await self.app(scope,read,write)
        finally:
            route=getattr(scope.get('route'),'path','unmatched')
            print(json.dumps({'time':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'project_id':'local.mediaforge',
                  'request_id':request_id,'task_id':scope.get('path_params',{}).get('id') if route.startswith('/api/tasks/{id}') else None,
                  'method':scope['method'],'route':route,'status':status,'request_body_bytes':received,
                  'response_body_bytes':sent,'body_complete':complete,'preview_cache':cache}),flush=True)
