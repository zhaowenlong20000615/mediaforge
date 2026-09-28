"""Activate one project's static delivery component, preserving its native authentication."""
import fcntl,hashlib,json,os,re,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
slug,project,commit,digest,configName,port=sys.argv[1:]
assert re.fullmatch('[a-z0-9-]+',slug) and re.fullmatch('[a-f0-9]{40}',commit) and re.fullmatch('[a-f0-9]{64}',digest)
assert 18000<=int(port)<=18099
if configName=='native':
 assert slug=='network-proxy' and project=='local.homeward' and port=='18043'
else:assert re.fullmatch(r'[A-Za-z0-9.-]+\.conf',configName)
root=(Path('/usr/local/lib/homeward/access') if configName=='native' else Path('/opt')/slug/'access');root.mkdir(parents=True,exist_ok=True)
with (root/'activation.lock').open('w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 artifact=root/'incoming'/(commit+'.tar.gz');assert hashlib.sha256(artifact.read_bytes()).hexdigest()==digest
 target=root/'releases'/commit;assert not target.exists(),'Immutable component already exists'
 target.mkdir(parents=True)
 try:
  with tarfile.open(artifact) as archive:
   for item in archive:
    p=Path(item.name)
    assert item.isfile() and not p.is_absolute() and '..' not in p.parts and item.size<100*1024*1024
    assert item.name in ['site/index.html','site/app.js','site/style.css','site/manifest.json','entrypoints.json','release.json','nginx.conf'] or re.fullmatch(r'files/[A-Za-z0-9._-]+\.zip',item.name)
    dest=target/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(archive.extractfile(item).read());dest.chmod(0o644)
  metadata=json.loads((target/'release.json').read_text());assert metadata['project_id']==project and metadata['source_commit']==commit
  manifest=json.loads((target/'site/manifest.json').read_text())
  for item in manifest['files']:
   p=target/'files'/item['name'];assert p.is_file() and p.stat().st_size==item['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
  if configName=='native':
   import urllib.request
   with urllib.request.urlopen('https://107.151.245.166:18043/version',timeout=10) as response:running=json.load(response)
   assert tuple(map(int,running['version'].split('.'))) >= (0,1,2),'Upgrade the native authenticated download handler first'
   previous=os.readlink(root/'current') if (root/'current').is_symlink() else None
   temporary=root/'current.next'
   if temporary.is_symlink():temporary.unlink()
   temporary.symlink_to(target);os.replace(temporary,root/'current')
   (target/'deployment.json').write_text(json.dumps({'project_id':project,'source_commit':commit,'artifact_sha256':digest,'previous':previous}))
   print(json.dumps({'deployed':project,'component_only':True,'native_auth_preserved':True}));raise SystemExit(0)
  original=Path('/etc/nginx/conf.d')/configName;before=original.read_text();assert re.search(r'listen\s+'+port+r'\s',before)
  marker='    include '+str(root/'current/nginx.conf')+';'
  assert len(re.findall(r'\bserver\s*\{',before))==1,'Ambiguous server block'
  after=before if marker in before else re.sub(r'(\bserver\s*\{)',lambda m:m.group(1)+'\n'+marker,before,count=1)
  previous=os.readlink(root/'current') if (root/'current').is_symlink() else None
  backup=root/'backups'/commit;backup.mkdir(parents=True,mode=0o700);(backup/'nginx.conf').write_text(before);(backup/'nginx.conf').chmod(0o600)
  (backup/'previous.json').write_text(json.dumps({'target':previous,'config':configName}));(backup/'previous.json').chmod(0o600)
  def link(value):
   tmp=root/'current.next'
   if tmp.is_symlink():tmp.unlink()
   if value:tmp.symlink_to(value);os.replace(tmp,root/'current')
   elif (root/'current').is_symlink():(root/'current').unlink()
  link(str(target))
  temporary=original.with_suffix('.next');temporary.write_text(after);temporary.chmod(0o644);os.replace(temporary,original)
  try:
   subprocess.run(['nginx','-t'],check=True,capture_output=True)
   subprocess.run(['systemctl','reload','nginx'],check=True)
  except Exception:
   original.write_text(before);link(previous);subprocess.run(['nginx','-t'],check=True,capture_output=True);subprocess.run(['systemctl','reload','nginx'],check=True);raise
  (target/'deployment.json').write_text(json.dumps({'project_id':project,'source_commit':commit,'artifact_sha256':digest,'previous':previous}))
  print(json.dumps({'deployed':project,'commit':commit,'artifact_sha256':digest,'component_only':True,'native_auth_preserved':True}))
 except Exception:
  raise
