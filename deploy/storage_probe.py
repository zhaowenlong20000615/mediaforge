"""Isolated real task probe; never fills disks or changes production state."""
from pathlib import Path
from contextlib import contextmanager
import argparse,json,sqlite3,tempfile,threading,time
from PIL import Image
from mediaforge.config import Settings
from mediaforge.store import Store
from mediaforge.engine import Engine


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scratch',required=True);parser.add_argument('--report',required=True);args=parser.parse_args()
    report={'failure':'Injected SQLITE_FULL in an isolated data directory; real image processing after recovery'}
    with tempfile.TemporaryDirectory(prefix='storage-probe-',dir=args.scratch) as directory:
        directory=Path(directory);source=directory/'fixture.png';Image.new('RGB',(160,100),'navy').save(source)
        store=Store(Settings(data=directory/'state',concurrency=1));file=store.import_file('workspace_default',source)
        task=store.submit('workspace_default','image-process',[file['id']],{'width':48});real_tx=store.tx;blocked=threading.Event();blocked.set()
        @contextmanager
        def flaky_tx():
            if threading.current_thread().name=='mediaforge-scheduler' and blocked.is_set():
                error=sqlite3.OperationalError('database or disk is full');error.sqlite_errorcode=sqlite3.SQLITE_FULL;raise error
            with real_tx() as connection:yield connection
        store.tx=flaky_tx;engine=Engine(store);engine.start()
        try:
            deadline=time.monotonic()+10
            while engine.scheduler_error is None and time.monotonic()<deadline:time.sleep(.05)
            report.update(thread_survived=engine.thread.is_alive(),readiness_degraded=not engine.ready,error_code=engine.scheduler_error['code'],task_retained=store.task('workspace_default',task['id'])['status']=='accepted')
            blocked.clear();deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                result=store.task('workspace_default',task['id'])
                if result['status'] in {'succeeded','failed','partial'}:break
                time.sleep(.1)
            report.update(final_status=result['status'],readiness_restored=engine.ready)
            if result['outputs']:
                output=store.file('workspace_default',result['outputs'][0]['id'],True)
                with Image.open(output['path']) as image:report['actual_size']=list(image.size)
            report['passed']=report['thread_survived'] and report['readiness_degraded'] and report['task_retained'] and report['final_status']=='succeeded' and report['readiness_restored'] and report.get('actual_size')==[48,30]
        finally:blocked.clear();engine.stop()
    path=Path(args.report);path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
