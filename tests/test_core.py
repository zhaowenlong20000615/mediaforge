import tempfile,time
from pathlib import Path
from mediaforge.core import TaskStore

def wait(store,tid):
 for _ in range(100):
  t=store.get(tid)
  if t['status'] in {'succeeded','failed','cancelled'}: return t
  time.sleep(.02)
 return store.get(tid)
def test_image_copy_and_hash():
 with tempfile.TemporaryDirectory() as d:
  f=Path(d)/'你好.txt';f.write_text('hello')
  s=TaskStore(Path(d)/'data');t=s.submit('image-process',[str(f)],{'format':'txt'},'idem-1');r=wait(s,t['id']);assert r['status']=='succeeded';assert r['outputs'][0]['sha256']
def test_idempotency_and_cancel():
 with tempfile.TemporaryDirectory() as d:
  f=Path(d)/'a.bin';f.write_bytes(b'x');s=TaskStore(Path(d)/'data');a=s.submit('batch',[str(f)],idem='same');b=s.submit('batch',[str(f)],idem='same');assert a['id']==b['id'];s.cancel(a['id']);assert s.get(a['id'])['status'] in {'cancelled','succeeded'}
