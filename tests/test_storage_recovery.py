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
