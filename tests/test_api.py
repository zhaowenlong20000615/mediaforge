from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from mediaforge.server import create_app
from mediaforge.config import Settings
from mediaforge.errors import ForgeError
from .test_core import wait,OWNER


@pytest.fixture
def api(tmp_path):
    app=create_app(Settings(data=tmp_path/'data'))
    token=(app.state.store.root/'admin.token').read_text()
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+token
        yield client,app.state.store


def upload(client,path,name=None):
    return client.post('/api/files',params={'name':name or path.name},content=path.read_bytes(),headers={'Content-Type':'application/octet-stream'})


def test_authorization_ownership_and_traversal(api,samples):
    client,s=api;f=upload(client,samples/'图片 sample.png').json()
    original=client.headers.pop('Authorization')
    for method,path in [('GET','/api/files/'+f['id']+'/content'),('GET','/api/tasks'),('POST','/api/tasks'),('GET','/api/doctor')]:
        assert client.request(method,path,json={}).status_code==401
    for path in ['/assets/../README.md','/static/../README.md','/assets/%2e%2e%2fREADME.md']:
        assert client.get(path).status_code==404
    client.headers['Authorization']=original
    other=s.create_workspace(OWNER,'other')
    client.headers['Authorization']='Bearer '+other['token']
    assert client.get('/api/files/'+f['id']).status_code==404
    assert client.post('/api/tasks',json={'tool':'image-process','file_ids':[f['id']]}).status_code==404
    client.headers['Authorization']=original
    assert client.post('/api/tasks',json={'tool':'image-process','files':['/etc/passwd']}).status_code==422
    assert client.post('/api/tasks',json={'tool':'image-process','file_ids':[f['id']]},headers={'Origin':'https://evil.invalid'}).status_code==403


def test_upload_types_download_and_range(api,samples):
    client,s=api
    assert upload(client,samples/'plain.txt',name='fake.png').status_code==400
    f=upload(client,samples/'图片 sample.png',name='中文 空格.png').json()
    t=client.post('/api/tasks',json={'tool':'image-process','file_ids':[f['id']],'params':{'width':100},'idempotency_key':'repeat'}).json()
    t=wait(s,t['id']);assert t['status']=='succeeded',t['error']
    out=t['outputs'][0];r=client.get('/api/files/'+out['id']+'/content')
    assert r.status_code==200 and r.content
    assert 'filename*=' in r.headers['Content-Disposition'] or 'filename=' in r.headers['Content-Disposition']
    assert client.get('/api/files/'+out['id']+'/content',headers={'Range':'bytes=0-9'}).status_code==206
    assert client.get('/api/files/'+out['id']+'/thumbnail').status_code==200
    assert 'path' not in client.get('/api/files/'+out['id']).json()
    assert client.get('/api/tasks?status=failed').json()['total']==0
    assert client.get('/api/tasks?status=succeeded').json()['total']==1


def test_invalid_json_limits_and_session(api,samples):
    client,s=api
    assert client.post('/api/tasks',content='not-json').status_code==400
    assert client.post('/api/files?name=empty.png',content=b'').status_code==413
    r=client.post('/api/templates',json={'name':'normal','tool':'image-process','params':{'width':200}});assert r.status_code==201
    assert client.get('/api/templates').json()['templates'][0]['params']['width']==200
    plan=client.post('/api/cleanup',json={'days':0,'dry_run':True}).json();assert plan['dry_run']
    original=client.headers.pop('Authorization');token=original[7:]
    r=client.post('/api/session',json={'token':token});assert r.status_code==200
    assert 'httponly' in r.headers['set-cookie'].lower()
    assert client.get('/api/me').status_code==200
    assert client.delete('/api/session').status_code==200
    assert client.get('/api/me').status_code==401


def test_stream_limits_and_tampered_payload(tmp_path):
    app=create_app(Settings(data=tmp_path/'limited',max_file_bytes=32,quota_bytes=48),start_worker=False)
    token=(app.state.store.root/'admin.token').read_text()
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+token
        assert c.post('/api/files?name=large.txt',content=b'x'*33).status_code==413
        assert c.post('/api/tasks',content=b'x'*70000).status_code==413
        assert c.post('/api/cleanup',json=[]).status_code==400
        assert c.post('/api/tasks',json={'tool':'image-process','file_ids':[],'params':{'unexpected':'bad'}}).status_code==400
        assert c.post('/api/files?name=note.txt',content=b'a'*30).status_code==201
        assert c.post('/api/files?name=note2.txt',content=b'b'*30).status_code==413


def test_filename_markup_and_html_attachment(api,tmp_path):
    c,s=api
    src=tmp_path/'name.txt';src.write_text('<script>example only</script>')
    f=upload(c,src,name='<img src=x>.html').json()
    assert c.get('/api/files/'+f['id']).json()['name']=='<img src=x>.html'
    response=c.get('/api/files/'+f['id']+'/content?inline=true')
    assert response.headers['content-disposition'].startswith('attachment')
    assert c.get('/api/files/'+f['id']+'/preview').json()['text']=='<script>example only</script>'


def test_pdf_page_preview_and_password_boundary(api,samples):
    from PIL import Image
    from io import BytesIO
    c,s=api
    f=upload(c,samples/'document.pdf').json()
    t=c.post('/api/tasks',json={'tool':'pdf-rotate','file_ids':[f['id']],'params':{'pages':'2','angle':'90'}}).json()
    result=wait(s,t['id']);assert result['status']=='succeeded'
    response=c.get('/api/files/'+result['outputs'][0]['id']+'/page?page=2')
    assert response.status_code==200
    with Image.open(BytesIO(response.content)) as page:assert page.width>page.height
    assert c.get('/api/files/'+f['id']+'/page?page=4').status_code==400
    protected=upload(c,samples/'protected.pdf').json()
    assert c.get('/api/files/'+protected['id']+'/page').status_code==409


def test_private_preview_cache_revalidation_and_source_retirement(api,samples,monkeypatch,capsys):
    c,s=api;f=upload(c,samples/'图片 sample.png').json();url='/api/files/'+f['id']+'/thumbnail?profile=screen'
    first=c.get(url);assert first.status_code==200 and first.headers['x-preview-cache']=='miss'
    assert first.headers['x-parent-sha256']==f['sha256'] and first.headers['x-preview-id'].startswith('preview_')
    assert first.headers['cache-control']=='private, no-cache' and int(first.headers['x-preview-width'])<=1280
    second=c.get(url,headers={'If-None-Match':first.headers['etag']});assert second.status_code==304 and not second.content and second.headers['x-preview-cache']=='hit'
    logs=[json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith('{')]
    assert logs[-1]['response_body_bytes']==0 and logs[-1]['preview_cache']=='hit'
    token=c.headers['Authorization'];other=c.post('/api/workspaces',json={'name':'other'}).json();c.headers['Authorization']='Bearer '+other['token']
    assert c.get(url,headers={'If-None-Match':first.headers['etag']}).status_code==404
    c.headers.pop('Authorization');assert c.get(url,headers={'If-None-Match':first.headers['etag']}).status_code==401
    c.headers['Authorization']=token
    # Content identity changes cannot silently reuse an old parent SHA.
    path=Path(s.file(OWNER,f['id'],True)['path']);path.write_bytes(path.read_bytes()+b'changed')
    assert c.get(url).status_code==409
    c.post('/api/cleanup',json={'days':0,'dry_run':False})
    assert c.get(url,headers={'If-None-Match':first.headers['etag']}).status_code==404


def test_pdf_cache_renders_once_and_is_bounded(api,samples,monkeypatch):
    import mediaforge.previews as previews
    c,s=api;f=upload(c,samples/'document.pdf').json();url='/api/files/'+f['id']+'/page?page=1'
    real=previews.subprocess.run;count=[]
    def counted(*args,**kw):
        if '-singlefile' in args[0]:count.append(1)
        return real(*args,**kw)
    monkeypatch.setattr(previews.subprocess,'run',counted)
    first=c.get(url);assert first.status_code==200
    repeat=c.get(url);assert repeat.content==first.content and repeat.headers['x-preview-cache']=='hit' and len(count)==1
    assert c.get(url,headers={'If-None-Match':first.headers['etag']}).status_code==304 and len(count)==1
    cache=c.app.state.preview_cache;cache.max_entries=1
    page2=c.get('/api/files/'+f['id']+'/page?page=2');assert page2.status_code==200
    assert len([p for p in cache.root.iterdir() if p.is_dir()])==1
    cache.ttl=-1;cache.clean();assert not [p for p in cache.root.iterdir() if p.is_dir()]
