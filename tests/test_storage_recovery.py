import errno
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
import pytest
import httpx
from mediaforge.engine import Engine
from mediaforge.client import Client
from mediaforge.errors import ForgeError
from tests.test_core import wait
from mediaforge.maintenance import Maintenance


def test_scheduler_survives_full_database_and_processes_queued_task(store,samples,monkeypatch):
    file=store.import_file('workspace_default',samples/'图片 sample.png')
    task=store.submit('workspace_default','image-process',[file['id']],{'width':48})
    real_tx=store.tx;blocked=threading.Event();blocked.set()
    @contextmanager
    def simulate_full_database():
        if threading.current_thread().name=='mediaforge-scheduler' and blocked.is_set():
            error=sqlite3.OperationalError('database or disk is full');error.sqlite_errorcode=sqlite3.SQLITE_FULL;raise error
        with real_tx() as con:yield con
    monkeypatch.setattr(store,'tx',simulate_full_database)
    engine=Engine(store);engine.start()
    try:
        deadline=time.monotonic()+5
        while engine.scheduler_error is None and time.monotonic()<deadline:time.sleep(.02)
        assert engine.thread.is_alive() and not engine.ready
        assert engine.scheduler_error['code']=='storage_full'
        assert store.task('workspace_default',task['id'])['status']=='accepted'
        blocked.clear();result=wait(store,task['id'],20)
        assert result['status']=='succeeded' and result['outputs'][0]['width']==48
        assert engine.ready and engine.scheduler_error is None
    finally:blocked.clear();engine.stop()


def test_download_reports_full_local_disk_without_publishing_partial_file(tmp_path,monkeypatch):
    token=tmp_path/'test.token';token.write_text('synthetic-test-token')
    client=Client('http://127.0.0.1',token);client.http.close()
    def respond(request):
        return httpx.Response(200,json={'size':3,'sha256':'unused'} if request.url.path.endswith('/file_fixture') else None,content=None if request.url.path.endswith('/file_fixture') else b'abc')
    client.http=httpx.Client(transport=httpx.MockTransport(respond))
    def full_disk(*args,**kwargs):raise OSError(errno.ENOSPC,'No space left on device')
    monkeypatch.setattr('mediaforge.client.tempfile.NamedTemporaryFile',full_disk)
    target=tmp_path/'output.png'
    try:
        with pytest.raises(ForgeError) as error:client.download('file_fixture',target)
        assert error.value.code=='local_storage_full' and error.value.retryable
        assert not target.exists() and not list(tmp_path.glob('.mediaforge-*.part'))
    finally:client.http.close()


def test_cleanup_failure_is_durable_scoped_and_does_not_stop_processing(store,samples,monkeypatch):
    old=store.import_file('workspace_default',samples/'图片 sample.png')
    with store.tx() as con:con.execute('UPDATE files SET created=0 WHERE id=?',(old['id'],))
    engine=Engine(store);engine.start();real=store.cleanup
    def fail_cleanup(owner,days=None,dry_run=True):
        if not dry_run:raise PermissionError('sensitive internal path must not leak')
        return real(owner,days,dry_run)
    monkeypatch.setattr(store,'cleanup',fail_cleanup)
    try:
        engine.cleanup_pool.submit(engine.maintenance.run_once).result(10)
        status=engine.maintenance.status('workspace_default')
        assert status['state']=='failed' and status['last_failure'] and status['last_success'] is None
        assert status['backlog']['files']==1 and status['error']['code']=='cleanup_permission'
        assert 'sensitive' not in json.dumps(status)
        assert Maintenance(store).status('workspace_default')['last_failure']==status['last_failure']
        assert engine.maintenance.status('unrelated-workspace')['backlog'] is None
        f=store.import_file('workspace_default',samples/'图片 sample.png')
        task=store.submit('workspace_default','image-process',[f['id']],{'width':48})
        assert wait(store,task['id'])['outputs'][0]['width']==48 and engine.ready
        monkeypatch.setattr(store,'cleanup',real);engine.maintenance.run_once()
        status=engine.maintenance.status('workspace_default')
        assert status['state']=='ok' and status['last_success'] and status['last_failure']
        assert status['backlog']['files']==0 and not status['error']
        assert store.task('workspace_default',task['id'])['outputs']
    finally:engine.stop()


def test_browse_derivative_keeps_original_and_real_stream_metadata(running,samples):
    from mediaforge.files import sha256
    store,engine=running
    if not (samples/'video.mp4').exists():pytest.skip('ffmpeg required')
    f=store.import_file('workspace_default',samples/'video.mp4');before=f['sha256']
    t=store.submit('workspace_default','video-transcode',[f['id']],{'profile':'browse-540p'},'browse-once')
    assert store.submit('workspace_default','video-transcode',[f['id']],{'profile':'browse-540p'},'browse-once')['id']==t['id']
    done=wait(store,t['id']);out=done['outputs'][0];d=out['derivation']
    assert d['purpose']=='browse_proxy' and d['parents'][0]['sha256']==before and not d['original_replaced']
    video=next(s for s in out['streams'] if s['codec_type']=='video')
    assert video['width']<=960 and video['height']<=540 and video['avg_frame_rate']=='30/1'
    assert any(s['codec_type']=='audio' for s in out['streams']) and abs(out['duration']-f['duration'])<.2
    assert sha256(store.file('workspace_default',f['id'],True)['path'])==before
