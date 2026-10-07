"""Business/state regression cases found in the October whole-product review."""
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
import httpx
import pytest
from PIL import Image
from mediaforge.client import Client
from mediaforge.config import Settings
from mediaforge.store import Store, uid
from mediaforge.files import inspect
from mediaforge.errors import ForgeError
from tests.test_core import OWNER


def finished(store,inputs,outputs,age=0):
    """Persist a task graph without a fake processing claim; no adapters are exercised here."""
    tid=uid('task');now=time.time()-age
    with store.tx() as con:
        con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,OWNER,'image-process','succeeded','test-only',100,0,now,now,uid('key'),'test','{}','',json.dumps(inputs),'',1800,0,None))
        con.execute('INSERT INTO items(id,task_id,seq,inputs,status,outputs) VALUES(?,?,?,?,?,?)',(uid('item'),tid,0,json.dumps(inputs),'succeeded',json.dumps(outputs)))
    return tid


def test_cleanup_protects_active_outputs_and_transitive_reuse(store,samples):
    ids=[store.import_file(OWNER,samples/'图片 sample.png')['id'] for _ in range(4)]
    # A -> B -> C -> D, newest D retained. An earlier task must not lose any referenced file.
    tasks=[finished(store,[ids[i]],[ids[i+1]],age=10*86400) for i in range(3)]
    with store.tx() as con:
        con.execute('UPDATE files SET created=?',(time.time()-10*86400,))
        con.execute('UPDATE files SET created=? WHERE id=?',(time.time(),ids[-1]))
    plan=store.cleanup(OWNER,7,False)
    assert plan['files']==0 and plan['tasks']==0
    for task in tasks:assert store.task(OWNER,task)['outputs']
    # An already-produced output on a running task also remains protected.
    with store.tx() as con:
        con.execute('UPDATE files SET created=?',(time.time()-20*86400,))
        con.execute("UPDATE tasks SET status='running' WHERE id=?",(tasks[0],))
    plan=store.cleanup(OWNER,7,False)
    assert plan['files']==0 and plan['tasks']==0


def test_cleanup_preserves_recent_failed_task_with_old_inputs(store,samples):
    f=store.import_file(OWNER,samples/'图片 sample.png')
    tid=finished(store,[f['id']],[])
    with store.tx() as con:
        con.execute('UPDATE files SET created=?',(time.time()-10*86400,))
        con.execute("UPDATE tasks SET status='failed' WHERE id=?",(tid,))
    assert store.cleanup(OWNER,7,False)['tasks']==0
    assert store.task(OWNER,tid)['status']=='failed'


def test_resume_obeys_pending_quota(tmp_path,samples):
    store=Store(Settings(data=tmp_path/'store',max_pending=1))
    f=store.import_file(OWNER,samples/'图片 sample.png')
    first=store.submit(OWNER,'image-process',[f['id']]);store.cancel(OWNER,first['id'])
    store.submit(OWNER,'image-process',[f['id']])
    with pytest.raises(ForgeError) as err:store.resume(OWNER,first['id'])
    assert err.value.code=='queue_full'


def test_chinese_tool_and_literal_percent_search(store,samples):
    f=store.import_file(OWNER,samples/'图片 sample.png')
    store.submit(OWNER,'image-process',[f['id']],group='完成 50%')
    store.submit(OWNER,'image-process',[f['id']],group='完成 100')
    assert store.tasks(OWNER,search='图片转换')['total']==2
    assert store.tasks(OWNER,search='50%')['total']==1
    assert store.tasks(OWNER,search='%')['total']==1


def test_utf8_across_header_boundary_and_actual_mime(tmp_path):
    text=tmp_path/'long.txt';text.write_bytes(b'A'*4095+'世界'.encode())
    assert inspect(text)['kind']=='text'
    invalid=tmp_path/'invalid.txt';invalid.write_bytes(b'a'*4096+b'\xff')
    with pytest.raises(ForgeError):inspect(invalid)


def test_client_preserves_other_partial_and_verifies_content(tmp_path):
    payload=b'synthetic-result';digest=hashlib.sha256(payload).hexdigest()
    def handler(request):
        if request.url.path.endswith('/content'):return httpx.Response(200,content=payload)
        return httpx.Response(200,json={'id':'file_test','size':len(payload),'sha256':digest})
    client=object.__new__(Client);client.base='http://127.0.0.1';client.http=httpx.Client(transport=httpx.MockTransport(handler))
    dest=tmp_path/'output.txt';unrelated=tmp_path/'output.txt.mediaforge-part';unrelated.write_bytes(b'other download')
    result=client.download('file_test',dest)
    assert unrelated.read_bytes()==b'other download'
    assert dest.read_bytes()==payload and result['sha256']==digest
    bad=object.__new__(Client);bad.base=client.base
    bad.http=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'bad') if r.url.path.endswith('/content') else httpx.Response(200,json={'size':len(payload),'sha256':digest})))
    with pytest.raises(ForgeError) as err:bad.download('file_test',tmp_path/'bad.txt')
    assert err.value.code=='download_integrity' and not (tmp_path/'bad.txt').exists()


def test_cli_mcp_uses_explicit_connection(monkeypatch,tmp_path):
    from mediaforge import cli,mcp
    calls=[]
    monkeypatch.setattr(mcp,'main',lambda server=None,token_file=None:calls.append((server,token_file)))
    assert cli.main(['--server','https://service.invalid','--token-file',str(tmp_path/'token'),'mcp'])==0
    assert calls==[('https://service.invalid',str(tmp_path/'token'))]


def test_templates_and_json_nan_are_structured_errors(tmp_path):
    from mediaforge.server import create_app
    from fastapi.testclient import TestClient
    app=create_app(Settings(data=tmp_path/'data'),start_worker=False)
    with TestClient(app,raise_server_exceptions=False) as c:
        c.headers['Authorization']='Bearer '+(app.state.store.root/'admin.token').read_text()
        for body in [{'name':'test','tool':[],'params':{}},{'name':'test','tool':'image-process','params':None},{'name':'test','tool':'image-process','params':[]}]:
            r=c.post('/api/templates',json=body)
            assert r.status_code in {400,422},r.text
        r=c.post('/api/templates',content='{"name":"test","tool":"media-trim","params":{"duration":NaN}}')
        assert r.status_code==400
        assert c.post('/api/cleanup',json={'days':True}).status_code==400
        assert c.get('/api/tasks?status=imaginary').status_code in {400,422}


def test_doctor_does_not_call_crashing_binary_available(tmp_path,monkeypatch):
    from mediaforge import dependencies as deps
    path=tmp_path/'ffmpeg';path.write_text('#!/bin/sh\nexit 23\n');path.chmod(0o755)
    monkeypatch.setattr(deps,'binary',lambda name:str(path) if name in {'ffmpeg','ffprobe'} else None)
    monkeypatch.setattr(deps,'installed',lambda name:False)
    result={x['id']:x for x in deps.checks()}
    assert not result['ffmpeg']['available'] and result['ffmpeg']['status']=='broken'
    assert 'stderr' not in result['ffmpeg']['details']


def test_ocrmypdf_keeps_vector_text_and_scan_readable(running,samples,tmp_path):
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader,PdfWriter
    from PIL import ImageDraw,ImageFont
    from tests.test_core import job,output_path
    text_page=tmp_path/'vector.pdf';c=canvas.Canvas(str(text_page));c.drawString(50,700,'ORIGINAL VECTOR CONTENT');c.save()
    image=Image.new('RGB',(1000,230),'white');font=ImageFont.load_default(size=55)
    ImageDraw.Draw(image).text((30,60),'SCANNED MEDIAFORGE 12345',font=font,fill='black')
    image.save(tmp_path/'scan.pdf','PDF')
    writer=PdfWriter();writer.append(text_page);writer.append(tmp_path/'scan.pdf')
    combined=tmp_path/'mixed.pdf'
    with combined.open('wb') as out:writer.write(out)
    store,_=running;result=job(store,'pdf-ocr',[combined],{'language':'eng'})
    assert result['status']=='succeeded',result['error']
    text=output_path(store,result).read_text()
    assert 'ORIGINAL VECTOR CONTENT' in text and '12345' in text
    pdf=PdfReader(output_path(store,result,1))
    assert len(pdf.pages)==2 and len(pdf.pages[0].images)==0
    assert result['outputs'][1]['verification']['engine']=='ocrmypdf'


def test_media_mime_uses_bytes_not_extension(samples,tmp_path):
    import shutil
    path=tmp_path/'movie.html';shutil.copyfile(samples/'video.mp4',path)
    result=inspect(path)
    assert result['kind']=='video' and result['mime']=='video/mp4'


def test_crashed_cleanup_restores_only_still_registered_files(store,samples):
    keep=store.import_file(OWNER,samples/'图片 sample.png')
    remove=store.import_file(OWNER,samples/'mask.png')
    rows=[]
    with store.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT id,path FROM files')]
    staged=store.root/'staging'/uid('cleanup');staged.mkdir()
    (staged/'moves.json').write_text(json.dumps(rows))
    for row in rows:(store.root/row['path']).replace(staged/row['id'])
    with store.tx() as c:c.execute('DELETE FROM files WHERE id=?',(remove['id'],))
    recovered=Store(store.settings)
    assert Path(recovered.file(OWNER,keep['id'],True)['path']).exists()
    assert not staged.exists()
    with pytest.raises(ForgeError):recovered.file(OWNER,remove['id'])


def test_giant_page_range_rejected_before_expanding():
    from mediaforge.runner import page_indices
    with pytest.raises(ForgeError):page_indices('1-999999999999',3)
