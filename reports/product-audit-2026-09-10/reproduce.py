"""Bounded audit reproductions; all inputs/data are synthetic and temporary.

Run from project root: python3 reports/product-audit-2026-09-10/reproduce.py
This script observes existing defects; it does not modify application code.
"""
import contextlib
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import threading
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mediaforge.core import TaskStore

results = {}

def finish(store, tid):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        task = store.get(tid)
        if task['status'] in {'succeeded', 'failed', 'partial', 'cancelled'} and store.running == 0:
            return task
        time.sleep(.01)
    raise RuntimeError('audit timed out')

with tempfile.TemporaryDirectory(prefix='mediaforge-audit-') as tmp:
    base = Path(tmp)
    plain = base / 'ordinary.txt'
    plain.write_text('SYNTHETIC AUDIT ONLY; no user data\n')
    store = TaskStore(base / 'state')
    for tool, params in [('asr', {}), ('subtitle-extract', {}),
                         ('pdf-tools', {'operation': 'rotate', 'angle': 90}),
                         ('image-process', {'format': 'png'})]:
        task = finish(store, store.submit(tool, [str(plain)], params)['id'])
        output = task['outputs'][0] if task['outputs'] else None
        results[tool] = {'status': task['status'], 'error': task.get('error'),
                         'output_mime': output['mime'] if output else None,
                         'bytes_identical': Path(output['path']).read_bytes() == plain.read_bytes() if output else None}

    subtitle = base / 'subtitle.vtt'
    subtitle.write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nAUDIT\n')
    task = finish(store, store.submit('subtitle-convert', [str(subtitle)], {'format':'srt'})['id'])
    results['vtt_to_srt'] = {'status': task['status'], 'still_starts_WEBVTT': Path(task['outputs'][0]['path']).read_text().startswith('WEBVTT')}
    if shutil.which('ffmpeg'):
        wav = base/'valid-audit.wav'
        video = base/'valid-no-subtitle.mp4'
        for command in [
            ['ffmpeg','-y','-f','lavfi','-i','sine=frequency=440:duration=0.3',str(wav)],
            ['ffmpeg','-y','-f','lavfi','-i','color=c=blue:s=64x64:d=0.3','-c:v','libx264',str(video)]]:
            subprocess.run(command,check=True,capture_output=True,timeout=15)
        for tool, source in [('asr',wav),('subtitle-extract',video)]:
            task = finish(store,store.submit(tool,[str(source)])['id'])
            out = task['outputs'][0]
            results['valid_media_'+tool] = {'status':task['status'],'identical_bytes':Path(out['path']).read_bytes()==source.read_bytes(),'output_mime':out['mime']}
        task = finish(store,store.submit('audio-extract',[str(wav)],{'format':'flac'})['id'])
        results['advertised_flac'] = {'status':task['status']}
    try:
        from PIL import Image
        pdf = base/'valid-audit.pdf'
        Image.new('RGB',(64,32),(20,40,60)).save(pdf,'PDF')
        task = finish(store,store.submit('pdf-tools',[str(pdf)],{'operation':'rotate','angle':90})['id'])
        results['valid_pdf_rotate'] = {'status':task['status'],'identical_bytes':Path(task['outputs'][0]['path']).read_bytes()==pdf.read_bytes()}
    except ImportError:
        results['valid_pdf_rotate'] = {'not_tested':'Pillow unavailable'}
    task = finish(store, store.submit('batch', [])['id'])
    results['empty_task'] = {'status':task['status'], 'outputs':len(task['outputs'])}
    a = finish(store, store.submit('batch', [str(plain)], idem='same-key')['id'])
    b = store.submit('asr', [str(subtitle)], idem='same-key')
    results['idempotency_conflict'] = {'same_id':a['id']==b['id'], 'requested':'asr', 'returned':b['tool']}

    for folder, content in [('one', 'FIRST'), ('two', 'SECOND')]:
        (base/folder).mkdir()
        (base/folder/'same.txt').write_text(content)
    task = finish(store, store.submit('batch', [str(base/'one'/'same.txt'), str(base/'two'/'same.txt')])['id'])
    results['same_filename_collision'] = {
        'status': task['status'],
        'same_output_path': task['outputs'][0]['path']==task['outputs'][1]['path'],
        'first_hash_matches_download': task['outputs'][0]['sha256']==hashlib.sha256(Path(task['outputs'][0]['path']).read_bytes()).hexdigest()}

    class PausedStore(TaskStore):
        def __init__(self, root):
            self.started = threading.Event()
            self.release = threading.Event()
            super().__init__(root)
        def _process_one(self, task, info):
            self.started.set()
            if not self.release.wait(4): raise RuntimeError('bounded audit release timeout')
            return super()._process_one(task, info)

    s = PausedStore(base/'cancel-state')
    s.max_concurrency = 1
    first = s.submit('batch', [str(plain)])
    assert s.started.wait(2)
    running_cancel = s.cancel(first['id'])['status']
    queued = s.submit('batch', [str(plain)])
    queued_cancel = s.cancel(queued['id'])['status']
    s.release.set()
    deadline = time.monotonic()+5
    while time.monotonic()<deadline and (s.get(first['id'])['status']=='cancelled' or s.get(queued['id'])['status']=='cancelled' or s.running): time.sleep(.02)
    results['cancel_race_controlled'] = {'running_immediate':running_cancel, 'running_final':s.get(first['id'])['status'], 'queued_immediate':queued_cancel, 'queued_final':s.get(queued['id'])['status']}

    s = PausedStore(base/'shared-state')
    task = s.submit('batch', [str(plain)])
    assert s.started.wait(2)
    other = TaskStore(base/'shared-state')
    results['reader_rewrites_running'] = {'actual_worker':s.get(task['id'])['status'], 'second_reader':other.get(task['id'])['status'], 'persisted':json.loads(s.db.read_text())[task['id']]['status']}
    s.release.set()
    finish(s, task['id'])

    x = TaskStore(base/'lost-state')
    y = TaskStore(base/'lost-state')
    tx = finish(x, x.submit('batch', [str(plain)])['id'])
    ty = finish(y, y.submit('batch', [str(plain)])['id'])
    results['two_store_lost_update'] = {'first_task_remains':tx['id'] in json.loads(x.db.read_text()), 'tasks_on_disk':len(json.loads(x.db.read_text()))}

    class FailingSecond(TaskStore):
        def _process_one(self, task, info):
            if info['name']=='subtitle.vtt': raise ValueError('controlled second-item failure')
            return super()._process_one(task, info)
    partial = FailingSecond(base/'partial-state')
    task = finish(partial, partial.submit('batch', [str(plain),str(subtitle)])['id'])
    results['partial_lost'] = {'status':task['status'], 'reported_outputs':len(task['outputs']), 'actual_output_files':len(list(partial.outputs.iterdir()))}

    env = os.environ | {'MEDIAFORGE_DATA':str(base/'cli-state'), 'PYTHONPATH':str(ROOT)}
    r = subprocess.run([sys.executable,'-m','mediaforge.cli','submit','audio-extract',str(plain),'--json'],cwd=ROOT,env=env,text=True,capture_output=True,timeout=10)
    recorded = json.loads((base/'cli-state'/'tasks.json').read_text())
    results['cli_failed_job_exit'] = {'exit_code':r.returncode,'printed_status':json.loads(r.stdout)['status'],'final_status':next(iter(recorded.values()))['status']}
    r = subprocess.run([sys.executable,'-m','mediaforge','inspect',str(base/'missing'),'--json'],cwd=ROOT,env=env,text=True,capture_output=True,timeout=5)
    results['python_m_entry_exit'] = {'exit_code':r.returncode,'stderr_contains_error':bool(r.stderr)}
    requests = [
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'audit','version':'1'}}},
        {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}]
    r = subprocess.run([sys.executable,'-m','mediaforge.mcp'],input='\n'.join(map(json.dumps,requests))+'\n',cwd=ROOT,env=env,text=True,capture_output=True,timeout=5)
    results['mcp_standard_messages'] = [json.loads(line) for line in r.stdout.splitlines()]

    os.environ['MEDIAFORGE_DATA'] = str(base/'http-state')
    from mediaforge import server
    from http.server import ThreadingHTTPServer
    class QuietHandler(server.H):
        def log_message(self,*args): pass
    httpd = ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
    worker = threading.Thread(target=httpd.serve_forever,daemon=True)
    worker.start()
    def request(method, path, data=None):
        conn = http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=5)
        body = json.dumps(data).encode() if data is not None else None
        conn.request(method,path,body,{'Content-Type':'application/json'} if body else {})
        res = conn.getresponse(); status = res.status; body = res.read(); conn.close()
        return status, body
    try:
        status, body = request('GET','/static/../README.md')
        results['static_traversal_safe_readme'] = {'status':status, 'readme_returned':body== (ROOT/'README.md').read_bytes()}
        status, body = request('POST','/api/tasks',{'tool':'batch','files':[str(plain)]})
        task = finish(server.store,json.loads(body)['id'])
        download = '/api/tasks/'+task['id']+'/download?file='+task['outputs'][0]['name']
        status2, data = request('GET',download)
        results['unauth_outside_workspace_canary'] = {'submit_status':status,'download_status':status2,'outside_data_dir':not plain.is_relative_to(server.store.root),'canary_returned':data==plain.read_bytes()}
        unicode_file = base/'中文 空格.txt'; unicode_file.write_text('UNICODE AUDIT')
        _,body = request('POST','/api/tasks',{'tool':'batch','files':[str(unicode_file)]})
        task = finish(server.store,json.loads(body)['id'])
        status,_ = request('GET','/api/tasks/'+task['id']+'/download?'+urllib.parse.urlencode({'file':task['outputs'][0]['name']}))
        results['unicode_download'] = {'status':status}
    finally:
        httpd.shutdown(); httpd.server_close(); worker.join(2)

output = Path(__file__).with_name('reproduction-results.json')
output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
