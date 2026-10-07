import asyncio
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import threading
import time
import pytest
import uvicorn
from mediaforge.config import Settings
from mediaforge.server import create_app
from mediaforge.client import Client
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.fixture
def live(tmp_path):
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    app=create_app(Settings(data=tmp_path/'service'))
    config=uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False)
    server=uvicorn.Server(config);thread=threading.Thread(target=server.run,daemon=True);thread.start()
    deadline=time.monotonic()+10
    while not server.started and time.monotonic()<deadline:time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{port}',str(app.state.store.root/'admin.token'),app.state.store
    server.should_exit=True;thread.join(10)
    assert not thread.is_alive()


def test_cli_shared_service_and_exit(live,samples,tmp_path):
    url,token,store=live
    def run(*args):
        return subprocess.run([sys.executable,'-m','mediaforge','--server',url,'--token-file',token,'--json',*args],capture_output=True,text=True,timeout=30)
    r=run('tasks','create','image-process',str(samples/'图片 sample.png'),'--param','width=64','--wait')
    assert r.returncode==0,r.stderr
    task=json.loads(r.stdout);assert task['status']=='succeeded' and task['outputs'][0]['width']==64
    r=run('tasks','list');assert task['id'] in r.stdout
    r=run('files','download',task['outputs'][0]['id'],'--output',str(tmp_path/'out.png'));assert r.returncode==0,r.stderr
    r=run('files','download',task['outputs'][0]['id'],'--output',str(tmp_path/'out.png'));assert r.returncode==2
    r=run('tasks','create','audio-extract',str(samples/'silent.mp4'),'--wait');assert r.returncode==4 and json.loads(r.stdout)['status']=='failed'
    r=run('files','get','not-found');assert r.returncode==2


def test_standard_mcp_end_to_end(live,samples):
    url,token,store=live
    async def exercise():
        params=StdioServerParameters(command=sys.executable,args=['-m','mediaforge.mcp'],env={**os.environ,'MEDIAFORGE_URL':url,'MEDIAFORGE_TOKEN_FILE':token,'MEDIAFORGE_LOCAL_ROOTS':str(samples)})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                initialized=await session.initialize();assert initialized.serverInfo.name=='MediaForge'
                listing=await session.list_tools();assert 'create_processing_task' in {x.name for x in listing.tools}
                upload=await session.call_tool('upload_file',{'path':str(samples/'图片 sample.png')})
                assert not upload.isError
                data=upload.structuredContent or json.loads(upload.content[0].text)
                accepted=await session.call_tool('create_processing_task',{'operation':'image-process','file_ids':[data['id']],'params':{'width':55},'idempotency_key':'mcp-e2e'})
                assert not accepted.isError
                job=accepted.structuredContent or json.loads(accepted.content[0].text)
                client=Client(url,token);finished=await asyncio.to_thread(client.wait,job['id'],20)
                assert finished['status']=='succeeded' and finished['outputs'][0]['width']==55
                details=await session.call_tool('get_task_details',{'task_id':job['id']});assert not details.isError
                rejected=await session.call_tool('upload_file',{'path':'/etc/passwd'});assert rejected.isError
    asyncio.run(exercise())


def test_mcp_rejects_credentials_even_inside_allowed_root(tmp_path,monkeypatch):
    from mediaforge.mcp import scoped_path
    monkeypatch.setenv('MEDIAFORGE_LOCAL_ROOTS',str(tmp_path))
    for name in ['server.token','private.pem','.env.local']:
        p=tmp_path/name;p.write_text('SYNTHETIC SECRET TEST ONLY')
        with pytest.raises(ValueError):scoped_path(str(p))


def test_http_transport_redacts_filenames_from_info_logs(live,samples,caplog):
    import logging
    url,token,_=live
    caplog.set_level(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.NOTSET)
    c=Client(url,token)
    result=c.upload(samples/'图片 sample.png')
    assert result['id']
    assert 'sample.png' not in caplog.text and '%E5%9B%BE' not in caplog.text


@pytest.mark.parametrize('idempotent',[True,False])
def test_dropped_submission_response_never_creates_duplicate_task(live,samples,idempotent):
    import httpx
    from mediaforge.errors import ForgeError
    url,token,store=live;client=Client(url,token);file=client.upload(samples/'图片 sample.png')
    class DropFirstResponse(httpx.BaseTransport):
        def __init__(self):self.transport=httpx.HTTPTransport();self.submissions=0
        def handle_request(self,request):
            response=self.transport.handle_request(request)
            if request.method=='POST' and request.url.path=='/api/tasks':
                self.submissions+=1
                if self.submissions==1:
                    response.read();response.close()
                    raise httpx.RemoteProtocolError('Injected disconnect after the real server accepted the task')
            return response
        def close(self):self.transport.close()
    transport=DropFirstResponse();headers=dict(client.http.headers);client.http.close()
    client.http=httpx.Client(headers=headers,transport=transport,timeout=20)
    payload={'tool':'image-process','file_ids':[file['id']],'params':{'width':48}}
    if idempotent:payload['idempotency_key']='dropped-response-regression'
    try:
        if idempotent:
            accepted=client.request('POST','api/tasks',json=payload)
            result=client.wait(accepted['id'],20)
            assert result['status']=='succeeded' and result['outputs'][0]['width']==48
            assert transport.submissions==2
        else:
            with pytest.raises(ForgeError,match='无法连接'):client.request('POST','api/tasks',json=payload)
            assert transport.submissions==1
        assert store.tasks('workspace_default')['total']==1
    finally:client.http.close()
