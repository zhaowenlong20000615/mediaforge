#!/usr/bin/env python3
"""Local build, credential-free package and explicit SSH artifact transport."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import time
import tomllib
import urllib.parse

ROOT=Path(__file__).resolve().parents[1]
HOST='107.151.245.166'


def run(args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)


def build():
    run(['uv','build','--wheel','--out-dir','dist'],cwd=ROOT)
    if not (ROOT/'dist/dependencies.txt').exists():raise SystemExit('Prepare pinned Linux wheels first; see docs/DEPLOYMENT.md.')


def package():
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise SystemExit('Commit all source changes before packaging.')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    version=json.loads(subprocess.check_output([str(ROOT/'.venv/bin/python'),'-c','import json,mediaforge;print(json.dumps(mediaforge.__version__))'],cwd=ROOT,text=True))
    own=list((ROOT/'dist').glob('mediaforge-'+version+'-*.whl'))
    if not own or not list((ROOT/'dist/wheels').glob('*.whl')):raise SystemExit('Build project wheel and pinned Linux dependencies first.')
    # Refuse incomplete or changed wheelhouses before spending time uploading.
    locked = {}
    for dependency in tomllib.loads((ROOT/'uv.lock').read_text())['package']:
        for wheel in dependency.get('wheels',[]):
            locked[Path(urllib.parse.unquote(urllib.parse.urlsplit(wheel['url']).path)).name] = wheel['hash'].removeprefix('sha256:')
    for wheel in (ROOT/'dist/wheels').glob('*.whl'):
        with wheel.open('rb') as stream:actual = hashlib.file_digest(stream,'sha256').hexdigest()
        if locked.get(wheel.name) != actual:raise SystemExit('Wheel is absent from the lock or has failed integrity verification: '+wheel.name)
    run(['uv','pip','compile','--offline','--no-index','--find-links','dist/wheels','--python-version','3.12','--python-platform','x86_64-unknown-linux-gnu','dist/dependencies.txt','--output-file','dist/validated-linux-requirements.txt'],cwd=ROOT,stdout=subprocess.DEVNULL)
    built=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());name=f'mediaforge-{version}-{commit[:12]}-{time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())}.tar.gz'
    artifact=ROOT/'dist'/name
    sources=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().strip('\0').split('\0')
    def safe(path):
        p=Path(path)
        if p.is_absolute() or any(x in {'.git','.venv','var','dist','node_modules'} for x in p.parts) or p.name in {'.env','admin.token','secret.key'} or p.suffix in {'.sqlite3','.db','.pem','.key'}:
            raise SystemExit('Unsafe tracked release member: '+path)
        if (ROOT/p).is_symlink():raise SystemExit('Symlinks are not accepted in release source.')
    with tarfile.open(artifact,'w:gz',format=tarfile.PAX_FORMAT) as tar:
        for source in sources:
            safe(source);tar.add(ROOT/source,arcname=source,recursive=False)
        for wheel in sorted((ROOT/'dist/wheels').glob('*.whl')):tar.add(wheel,arcname='wheels/'+wheel.name)
        tar.add(own[0],arcname='wheels/'+own[0].name)
        tar.add(ROOT/'dist/dependencies.txt',arcname='dependencies.txt')
    digest=hashlib.file_digest(artifact.open('rb'),'sha256').hexdigest()
    meta={'project_id':'local.mediaforge','version':version,'git_commit':commit,'artifact_sha256':digest,'built_at':built,'python':'3.12','target':'linux-x86_64'}
    Path(str(artifact)+'.release.json').write_text(json.dumps(meta,indent=2)+'\n')
    Path(str(artifact)+'.sha256').write_text(digest+'  '+artifact.name+'\n')
    print(artifact)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['build','package','upload','activate','status','rollback']);p.add_argument('artifact',nargs='?');p.add_argument('--dry-run',action='store_true');args=p.parse_args()
    if os.getenv('TARGET_HOST',HOST)!=HOST:raise SystemExit('Refusing unexpected deployment host.')
    dry=args.dry_run or os.getenv('DRY_RUN')=='1'
    key=Path(os.getenv('DEPLOY_SSH_KEY',str(Path.home()/'.ssh/chimera-lab_root_ed25519'))).expanduser()
    ssh=['ssh','-i',key,'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10','root@'+HOST]
    if args.action=='build':
        if dry:print('DRY_RUN: build local wheel')
        else:build()
    elif args.action=='package':
        if dry:print('DRY_RUN: package only committed sources and Linux wheels')
        else:package()
    else:
        artifact=Path(args.artifact or os.getenv('PACKAGE','')).resolve()
        if args.action in {'upload','activate'}:
            if not artifact.is_file() or not re.fullmatch(r'mediaforge-[A-Za-z0-9.\-]+\.tar\.gz',artifact.name):raise SystemExit('A valid MediaForge artifact is required.')
        if dry:
            print('DRY_RUN:',args.action,'target='+HOST,'artifact='+artifact.name);return
        if args.action=='upload':
            for suffix in ['', '.sha256','.release.json']:
                if not Path(str(artifact)+suffix).is_file():raise SystemExit('Missing artifact sidecar.')
            run(ssh+['install -d -m 700 /opt/mediaforge/incoming'])
            run(['scp','-i',key,'-o','IdentitiesOnly=yes','-o','BatchMode=yes',artifact,str(artifact)+'.sha256',str(artifact)+'.release.json','root@'+HOST+':/opt/mediaforge/incoming/'])
            print('Uploaded artifact and integrity metadata.')
        else:
            # The script is sent from the local checkout; the server does not access GitHub.
            with (ROOT/'deploy/remote.py').open('rb') as script:
                run(ssh+['python3 - '+args.action+' '+(artifact.name if args.action=='activate' else '')],stdin=script)

if __name__=='__main__':main()
