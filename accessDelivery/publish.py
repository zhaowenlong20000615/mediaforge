"""Publish this project's delivery component only; application authentication remains unchanged."""
import argparse,hashlib,json,os,re,subprocess,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dry-run',action='store_true');p.add_argument('--fork',action='store_true');a=p.parse_args()
if a.fork and root.name!='sub2api':p.error('--fork is supported only by the isolated Sub2API instance')
configName='configFork.json' if a.fork else 'config.json';config=json.loads((root/'accessDelivery'/configName).read_text())
slug=config.get('deploySlug',root.name);assert slug==root.name or root.name=='sub2api' and slug=='sub2api-fork'
conf,port=('sub2api-fork.conf',18087) if a.fork else ('mediaforge.conf',18081)
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip();assert re.fullmatch('[a-f0-9]{40}',commit)
if a.dry_run:
 print(json.dumps({'target':'107.151.245.166','project_id':config['projectId'],'port':port,'nginx':conf,'source_commit':commit,'component_only':True}));raise SystemExit()
assert not subprocess.check_output(['git','status','--porcelain','--','accessDelivery','tool.manifest.json'],cwd=root,text=True).strip(),'Commit delivery changes before publishing'
remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],cwd=root,text=True).split()[0];assert remote==commit,'Push the exact source commit before publishing'
subprocess.run(['python3',str(root/'accessDelivery/build.py'),configName] if a.fork else ['python3',str(root/'accessDelivery/build.py')],cwd=root,check=True)
output=root/'dist'/config.get('output','accessDelivery');meta=json.loads((output/'release.json').read_text());assert meta['source_commit']==commit
manifest=json.loads((output/'site/manifest.json').read_text());allowed={f['name'] for f in manifest['files']}
artifact=root/'dist'/(slug+'-'+commit+'.access.tar.gz')
with tarfile.open(artifact,'w:gz') as archive:
 for file in sorted(output.rglob('*')):
  if file.is_file() and not file.is_symlink() and (file.parent.name!='files' or file.name in allowed):archive.add(file,arcname=file.relative_to(output),recursive=False)
sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
key=Path(os.environ.get('DELIVERY_SSH_KEY',str(Path.home()/'.ssh/chimera-lab_root_ed25519')))
ssh=['ssh','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','root@107.151.245.166']
base='/usr/local/lib/homeward/access' if conf=='native' else '/opt/'+slug+'/access'
subprocess.run([*ssh,'install -d -m 0755 '+base+'/incoming'],check=True)
subprocess.run(['scp','-i',str(key),'-o','IdentitiesOnly=yes',str(artifact),'root@107.151.245.166:'+base+'/incoming/'+commit+'.tar.gz'],check=True)
args=[slug,config['projectId'],commit,sha,conf,str(port)];assert all(re.fullmatch('[A-Za-z0-9.-]+',x) for x in args)
subprocess.run([*ssh,'python3 - '+' '.join(args)],input=(root/'accessDelivery/activate.py').read_text(),text=True,check=True)
