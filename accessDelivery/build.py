"""Build this project's credential-free delivery component from committed client files."""
import hashlib,io,json,os,re,shutil,subprocess,tarfile,tempfile,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
config=json.loads((root/'accessDelivery/config.json').read_text())
output=root/'dist/accessDelivery';output.mkdir(parents=True,exist_ok=True)
site=output/'site';site.mkdir(exist_ok=True);files=output/'files';files.mkdir(exist_ok=True)
for name in ['index.html','app.js','style.css']:shutil.copyfile(root/'accessDelivery'/name,site/name)
def git(*args):return subprocess.check_output(['git',*args],cwd=root)
ref=git('rev-parse',config['clientRef']).decode().strip()
assert re.fullmatch('[a-f0-9]{40}',ref)
with tempfile.TemporaryDirectory() as folder:
 stage=Path(folder)/'payload';stage.mkdir();client=stage/'client';client.mkdir()
 raw=git('archive','--format=tar',ref,*config['include'])
 with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
  for m in archive:
   if m.isdir():continue
   p=Path(m.name)
   if not m.isfile() or p.is_absolute() or '..' in p.parts:raise ValueError('unsafe client member')
   if any(x in {'.git','.data','.runtime','.env','.ssh','.secrets','node_modules'} for x in p.parts) or p.suffix in {'.key','.pem','.token','.db','.sqlite3'}:raise ValueError('runtime file in client')
   data=archive.extractfile(m).read()
   if re.search(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}',data):raise ValueError('secret material in client')
   dest=client/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);dest.chmod(m.mode&0o755)
 if config['buildMode']=='bun':
  for rel in ['node_modules','packages/mcp/node_modules']:
   if (root/rel).exists():
    dest=client/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to((root/rel).resolve(),target_is_directory=True)
  for source,target in config['bundles'].items():
   subprocess.run(['bun','build',str(client/source),'--target=bun','--outfile',str(client/target)],cwd=client,check=True)
 if config['buildMode']=='python':
  installer='''import argparse,os,subprocess,sys,venv\nfrom pathlib import Path\np=argparse.ArgumentParser(description="只在接入包目录安装本项目依赖，不启动业务服务")\np.add_argument("--browser",action="store_true",help="为账号执行端安装 Chromium")\na=p.parse_args()\nif not MINIMUM <= sys.version_info[:2] < (3,15):raise SystemExit("请安装项目说明指定的 Python 版本（最高 3.14）")\nroot=Path(__file__).resolve().parent;target=root/".venv"\nvenv.EnvBuilder(with_pip=True).create(target)\npython=target/("Scripts/python.exe" if os.name=="nt" else "bin/python")\nsubprocess.run([str(python),"-m","pip","install","-e",str(root/"client")],check=True)\nif a.browser:\n if not BROWSER:raise SystemExit("此项目不需要浏览器安装")\n subprocess.run([str(python),"-m","playwright","install","chromium"],check=True)\nprint("依赖安装完成。请按说明配置该项目授权，再运行 CLI／MCP 或配对设备。")\n'''.replace('MINIMUM',repr(tuple(config.get('pythonMin',[3,11])))).replace('BROWSER',repr(config.get('browser',False)))
  (stage/'install.py').write_text(installer)
  (stage/'安装依赖.cmd').write_bytes(b'@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\npy -3 install.py\r\nif errorlevel 1 pause\r\n')
 if config['buildMode']=='go':
  for platform,goos,goarch in [('windows-x64','windows','amd64'),('macos-arm64','darwin','arm64'),('macos-x64','darwin','amd64'),('linux-x64','linux','amd64')]:
   binary=client/('homeward.exe' if goos=='windows' else 'homeward')
   subprocess.run(['go','build','-trimpath','-ldflags','-s -w -X network-proxy/internal/version.buildCommit='+ref,'-o',str(binary),'./cmd/homeward'],cwd=client,env={**os.environ,'CGO_ENABLED':'0','GOOS':goos,'GOARCH':goarch},check=True)
   target=files/('homeward-'+config['clientVersion']+'-'+platform+'.zip')
   with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,6) as z:
    z.write(binary,binary.name);z.writestr('安装说明.txt','\n'.join(config['steps']+config['checks']+config['limits']));
    for skill in (client/config['sourceSkill']).parent.rglob('*'):
     if skill.is_file():z.write(skill,'skill/'+str(skill.relative_to((client/config['sourceSkill']).parent)))
   binary.unlink()
 else:
  (stage/'使用说明.txt').write_text(config['title']+'\n\n'+'\n'.join(config['steps']+config['checks']+config['limits'])+'\n\n'+'\n'.join(c['title']+'\n'+c.get('windows',c.get('any',''))+'\n'+c.get('unix','') for c in config['commands']))
  (stage/'clientSource.json').write_text(json.dumps({'project_id':config['projectId'],'version':config['clientVersion'],'git_commit':ref},indent=2))
  target=files/(config['slug']+'-'+config['clientVersion']+'-client.zip')
  with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,6) as z:
   for p in sorted(stage.rglob('*')):
    if p.is_file():z.write(p,p.relative_to(stage))
 manifest={k:v for k,v in config.items() if k not in {'include','clientRef','bundles','buildMode','nginx','pythonMin','browser','sourceSkill'}}
 manifest['clientCommit']=ref;manifest['files']=[]
 for p in sorted(files.glob('*.zip')):
  with zipfile.ZipFile(p) as z:assert z.testzip() is None
  manifest['files'].append({'name':p.name,'label':config['title']+' · '+(p.stem.split(config['clientVersion']+'-')[-1] if config['buildMode']=='go' else config['packageLabel']),'description':config['packageDescription'],'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'url':config['fileBase']+p.name,'verification':'已核对包完整性；Windows 实机尚未验证'})
 (site/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
component={'schema_version':1,'project_id':config['projectId'],'component':'access_delivery','version':'1','client_commit':ref,'source_commit':git('rev-parse','HEAD').decode().strip(),'entrypoints':{k:config['pageUrl']+'#'+anchor for k,anchor in {'downloads':'download','install':'install','cli_docs':'cli','mcp_docs':'mcp','skill':'skill','skill_docs':'skill','docs':'install'}.items()}}
(output/'entrypoints.json').write_text(json.dumps(component,ensure_ascii=False,indent=2))
(output/'release.json').write_text(json.dumps(component,ensure_ascii=False,indent=2))
if (root/'accessDelivery/nginx.conf').exists():shutil.copyfile(root/'accessDelivery/nginx.conf',output/'nginx.conf')
print(json.dumps({'project':config['projectId'],'output':str(output),'files':len(manifest['files']),'client_commit':ref}))
