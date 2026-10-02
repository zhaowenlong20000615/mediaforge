"""Remote activation of a locally assembled, verified artifact. Invoked over SSH."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import grp
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time

BASE=Path('/opt/mediaforge')
CURRENT=BASE/'current'
SERVICE='mediaforge-web.service'
NGINX=Path('/etc/nginx/conf.d/mediaforge.conf')


def command(args,**kw):return subprocess.run(args,check=True,**kw)


def target(path):return path.resolve() if path.is_symlink() else None


def switch(path):
    temp=BASE/'current.next';temp.unlink(missing_ok=True);temp.symlink_to(path);temp.replace(CURRENT)


def now():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())


def ready():
    for i in range(40):
        r=subprocess.run(['curl','-fsS','--max-time','3','--unix-socket','/run/mediaforge/api.sock','http://localhost/readyz'],capture_output=True)
        if r.returncode==0:
            try:
                data=json.loads(r.stdout)
                if data.get('worker_ready'):return data
            except ValueError:pass
        time.sleep(.5)
    raise RuntimeError('New release did not become ready')


def secure_release(path):
    if not path:return False
    try:return json.loads((path/'release.json').read_text())['version'].startswith('0.2.')
    except Exception:return False


def configure():
    try:pwd.getpwnam('mediaforge')
    except KeyError:command(['useradd','--system','--home-dir',str(BASE),'--no-create-home','--shell','/usr/sbin/nologin','mediaforge'])
    user=pwd.getpwnam('mediaforge')
    data=BASE/'data'
    if (data/'tasks.json').exists() and not (data/'state.sqlite3').exists():
        data.rename(BASE/('legacy-data-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())))
    data.mkdir(exist_ok=True,mode=0o700);os.chown(data,user.pw_uid,user.pw_gid);data.chmod(0o700)
    (BASE/'models').mkdir(exist_ok=True)
    if not (BASE/'runtime.env').exists():
        (BASE/'runtime.env').write_text('MEDIAFORGE_DATA=/opt/mediaforge/data\nMEDIAFORGE_UNIX_SOCKET=/run/mediaforge/api.sock\nMEDIAFORGE_PORT=18081\nMEDIAFORGE_SECURE_COOKIE=1\nMEDIAFORGE_COOKIE_PATH=/mediaforge/\nMEDIAFORGE_PUBLIC_URL=https://107.151.245.166:18081\nMEDIAFORGE_RELEASE_FILE=/opt/mediaforge/current/release.json\nMEDIAFORGE_ASR_MODEL=/opt/mediaforge/models/faster-whisper-tiny\nU2NET_HOME=/opt/mediaforge/models/u2net\nMEDIAFORGE_WORKER_MEMORY=6442450944\nOMP_NUM_THREADS=2\nOPENBLAS_NUM_THREADS=2\nNUMBA_CACHE_DIR=/opt/mediaforge/data/numba-cache\n')
        (BASE/'runtime.env').chmod(0o600)
    unit='''[Unit]
Description=MediaForge authenticated media workbench
After=network.target
[Service]
Type=simple
User=mediaforge
Group=www-data
WorkingDirectory=/opt/mediaforge/current
EnvironmentFile=/opt/mediaforge/runtime.env
Environment=HOME=/opt/mediaforge/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ExecStart=/opt/mediaforge/current/.venv/bin/python -m mediaforge.server
RuntimeDirectory=mediaforge
RuntimeDirectoryMode=0750
UMask=0007
Restart=on-failure
RestartSec=3
TimeoutStopSec=25
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/mediaforge/data /run/mediaforge
RestrictAddressFamilies=AF_UNIX
MemoryMax=8G
TasksMax=256
CPUQuota=250%
[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/'+SERVICE).write_text(unit)
    cert=Path('/etc/letsencrypt/live/homeward-ip/fullchain.pem');key=cert.with_name('privkey.pem')
    if not cert.exists() or not key.exists():raise RuntimeError('Configured shared IP TLS certificate is unavailable')
    if NGINX.exists() and '# MediaForge owned' not in NGINX.read_text():raise RuntimeError('Refusing to replace an unowned ingress configuration')
    # Preserve existing delivery and authentication locations during upgrades.
    if not NGINX.exists():
        NGINX.write_text('''# MediaForge owned; no other virtual host is modified.
    server {
        listen 18081 ssl;
        server_name 107.151.245.166;
        ssl_certificate /etc/letsencrypt/live/homeward-ip/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/homeward-ip/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        client_max_body_size 512m;
        error_page 497 =301 https://$host:18081$request_uri;
        location = / { return 302 /mediaforge/; }
        location /mediaforge/ {
            proxy_pass http://unix:/run/mediaforge/api.sock:/;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_request_buffering off;
            proxy_buffering off;
            proxy_read_timeout 120s;
        }
        location = /healthz { proxy_pass http://unix:/run/mediaforge/api.sock:/healthz; }
        location = /readyz { proxy_pass http://unix:/run/mediaforge/api.sock:/readyz; }
        location = /version { proxy_pass http://unix:/run/mediaforge/api.sock:/version; }
    }
    ''')
    command(['nginx','-t'])
    command(['systemctl','daemon-reload'])


def activate(name):
    if not re.fullmatch(r'mediaforge-[A-Za-z0-9.\-]+\.tar\.gz',name):raise ValueError('Bad artifact name')
    artifact=BASE/'incoming'/name
    meta=json.loads(Path(str(artifact)+'.release.json').read_text())
    digest=hashlib.file_digest(artifact.open('rb'),'sha256').hexdigest()
    expected=Path(str(artifact)+'.sha256').read_text().split()[0]
    if digest!=expected or digest!=meta['artifact_sha256'] or meta['project_id']!='local.mediaforge':raise RuntimeError('Artifact integrity mismatch')
    if not re.fullmatch('[0-9a-f]{40}',meta['git_commit']) or not re.fullmatch(r'\d+\.\d+\.\d+',meta['version']):raise RuntimeError('Invalid release metadata')
    release=BASE/'releases'/(meta['version']+'-'+meta['git_commit'][:12]+'-'+digest[:8])
    release.mkdir(parents=True,exist_ok=True)
    with tarfile.open(artifact) as tar:
        if any(m.issym() or m.islnk() or m.isdev() for m in tar):raise RuntimeError('Links and devices are not accepted in release packages')
        tar.extractall(release,filter='data')
    (release/'release.json').write_text(json.dumps(meta,indent=2)+'\n')
    venv=release/'.venv'
    if not venv.exists():command(['python3','-m','venv',str(venv)])
    old=target(CURRENT)
    wheel_sources=['--find-links',str(release/'wheels')]
    cached_wheels=None
    if old and old.is_relative_to(BASE/'releases') and secure_release(old) and (old/'wheels').is_dir():
        # Reuse only this project's retained release cache. pip still verifies
        # every selected dependency against the incoming requirement hashes.
        cached_wheels=old/'wheels'
        wheel_sources.extend(['--find-links',str(cached_wheels)])
    with (release/'install.log').open('wb') as log:
        command([str(venv/'bin/pip'),'install','--no-index',*wheel_sources,'--require-hashes','--report',str(release/'dependency-install.json'),'-r',str(release/'dependencies.txt')],stdout=log,stderr=log)
        wheel=next((release/'wheels').glob('mediaforge-*.whl'))
        command([str(venv/'bin/pip'),'install','--no-index','--no-deps',str(wheel)],stdout=log,stderr=log)
    previous_nginx=NGINX.read_bytes() if NGINX.exists() else None
    database=BASE/'data/state.sqlite3'
    if database.exists():
        connection=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
        try:active=connection.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('accepted','running')").fetchone()[0]
        finally:connection.close()
        if active:raise RuntimeError('Active media tasks exist; activation stopped before switching releases')
    try:
        configure();switch(release)
        command(['systemctl','enable',SERVICE],capture_output=True)
        command(['systemctl','restart',SERVICE])
        health=ready()
        command(['systemctl','reload','nginx'])
        if secure_release(old) and old!=release:(BASE/'previous.json').write_text(json.dumps({'release':str(old)}))
        deployed={**meta,'deployed_at':now(),'release':str(release),'url':'https://107.151.245.166:18081/mediaforge/','health':health,'uid':pwd.getpwnam('mediaforge').pw_uid,'dependency_cache':str(cached_wheels) if cached_wheels else None,'dependency_install_report_sha256':hashlib.sha256((release/'dependency-install.json').read_bytes()).hexdigest()}
        (BASE/'deployment.json').write_text(json.dumps(deployed,indent=2)+'\n')
        print(json.dumps({'activated':str(release),'git_commit':meta['git_commit'],'health':health,'url':deployed['url']}))
    except BaseException:
        if previous_nginx is not None:NGINX.write_bytes(previous_nginx)
        else:NGINX.unlink(missing_ok=True)
        if secure_release(old):switch(old);command(['systemctl','restart',SERVICE]);ready()
        else:subprocess.run(['systemctl','stop',SERVICE],capture_output=True)
        subprocess.run(['nginx','-t'],capture_output=True)
        subprocess.run(['systemctl','reload','nginx'],capture_output=True)
        raise


def rollback():
    previous=json.loads((BASE/'previous.json').read_text())
    release=Path(previous['release']).resolve()
    if not release.is_relative_to(BASE/'releases') or not secure_release(release):raise RuntimeError('No safe rollback release')
    old=target(CURRENT)
    try:
        switch(release);command(['systemctl','restart',SERVICE]);health=ready()
        (BASE/'previous.json').write_text(json.dumps({'release':str(old)}))
        meta=json.loads((release/'release.json').read_text());(BASE/'deployment.json').write_text(json.dumps({**meta,'deployed_at':now(),'release':str(release),'rollback':True,'health':health},indent=2))
        print(json.dumps({'rolled_back_to':str(release),'git_commit':meta['git_commit'],'health':health}))
    except BaseException:
        switch(old);command(['systemctl','restart',SERVICE]);raise

if sys.argv[1]=='activate':activate(sys.argv[2])
elif sys.argv[1]=='rollback':rollback()
else:
    print((BASE/'deployment.json').read_text() if (BASE/'deployment.json').exists() else '{}')
    print(json.dumps(ready()))
