"""MediaForge-only release retention. No business data, models or global caches."""
from pathlib import Path
import hashlib,json,os,re,shutil,time,fcntl
PROC_ROOT=Path('/proc')


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def snapshot(path):
    """Revalidated content/identity signature; hard-link sizes are not freed bytes."""
    h=hashlib.sha256();size=0
    for p in sorted(path.rglob('*')) if path.is_dir() else [path]:
        st=p.lstat();h.update(str((str(p.relative_to(path)) if p!=path else '.',st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)).encode())
        if p.is_symlink():h.update(os.readlink(p).encode())
        elif p.is_file():h.update(digest(p).encode());size+=st.st_size
    return h.hexdigest(),size


def release_for(path,base):
    for root in [base/'releases',base/'access/releases']:
        try:part=path.absolute().relative_to(root).parts[0];return root/part
        except (ValueError,IndexError):continue


def plan(base):
    base=Path(base).resolve();keep=set();reasons={};candidates=[];skipped=[]
    def protect(p,why):
        if p:
            p=Path(p);r=release_for(p,base)
            if r:
                keep.add(r)
                if why not in reasons.setdefault(str(r),[]):reasons[str(r)].append(why)
    for root in [base,base/'access']:
        current=root/'current'
        if not current.is_symlink():raise RuntimeError('Current release link missing: '+str(current))
        protect(current.resolve(),'current')
        if root==base:
            previous=json.loads((root/'previous.json').read_text())['release']
        else:
            previous=json.loads((current.resolve()/'deployment.json').read_text())['previous']
        protect(previous,'rollback')
    # Process cwd/exe/fd/maps keep live environments. Permission failures abort
    # the deletion plan rather than assuming an unreadable process is irrelevant.
    for proc in PROC_ROOT.iterdir():
        if not proc.name.isdigit():continue
        try:
            for n in ['cwd','exe']:
                try:protect((proc/n).resolve(strict=True),'process '+proc.name)
                except FileNotFoundError:pass
            for fd in (proc/'fd').iterdir():
                try:protect(fd.resolve(strict=True),'open file '+proc.name)
                except FileNotFoundError:pass
            for line in (proc/'maps').read_text().splitlines():
                if str(base) in line:protect(Path(line.split()[-1]),'mapped '+proc.name)
            for arg in (proc/'cmdline').read_bytes().decode('utf-8','ignore').split('\0'):
                if arg.startswith(str(base)+'/'):protect(Path(arg),'process argument '+proc.name)
        except (FileNotFoundError,ProcessLookupError):continue
    changed=True
    while changed:
        before=len(keep)
        for root in list(keep):
            if not root.is_dir():raise RuntimeError('Retained dependency missing: '+str(root))
            files=list((root/'.venv').rglob('*'))
            for p in files:
                if p.is_symlink():protect(p.resolve(),'runtime symlink')
                elif p.is_file() and (p.parent==root/'.venv/bin' or p.suffix=='.pth' or p.name=='pyvenv.cfg') and p.stat().st_size<262144:
                    text=p.read_bytes().decode('utf-8','ignore')
                    for value in re.findall(re.escape(str(base))+r'/releases/[^\s\x00\x22\x27;]+',text):protect(Path(value),'shebang/pth/runtime config')
            report=root/'dependency-install.json'
            if report.is_file():
                from urllib.parse import urlsplit,unquote
                for item in json.loads(report.read_text()).get('install',[]):
                    info=item.get('download_info',{});url=urlsplit(info.get('url',''));source=Path(unquote(url.path));local=root/'wheels'/source.name
                    expected=info.get('archive_info',{}).get('hashes',{}).get('sha256')
                    if url.scheme=='file' and release_for(source,base) and not (local.is_file() and expected and digest(local)==expected):
                        protect(source,'pip source not materialized with verified local SHA')
        changed=len(keep)!=before
    def candidate(p,reason):
        sig,size=snapshot(p);candidates.append({'path':str(p),'reason':reason,'sha256_tree':sig,'logical_bytes':size})
    for root in [base/'releases',base/'access/releases']:
        for p in root.iterdir():
            if p in keep:continue
            if not p.is_dir() or p.is_symlink():skipped.append(str(p));continue
            try:meta=json.loads((p/'release.json').read_text())
            except (ValueError,OSError):skipped.append(str(p));continue
            if meta.get('project_id')!='local.mediaforge':skipped.append(str(p));continue
            # Unknown recent directories may be another in-progress installation.
            if not (p/'deployment.json').exists() and time.time()-p.stat().st_mtime<48*3600:
                skipped.append(str(p));continue
            candidate(p,'unreferenced MediaForge release')
    backups=base/'access/backups'
    if backups.is_dir():
        kept_names={p.name for p in keep if p.parent==base/'access/releases'}
        for p in backups.iterdir():
            if p.name in kept_names or p.is_symlink() or not p.is_dir():continue
            try:
                names={x.name for x in p.iterdir()};m=json.loads((p/'previous.json').read_text())
                if re.fullmatch('[a-f0-9]{40}',p.name) and names<={'nginx.conf','previous.json'} and m.get('config')=='mediaforge.conf':
                    candidate(p,'superseded delivery configuration rollback snapshot')
                else:skipped.append(str(p))
            except (OSError,ValueError):skipped.append(str(p))
    # Upload groups: validate archive SHA against its own metadata, never select
    # a sidecar alone or infer version from modification order.
    protected_shas=set()
    for p in keep:
        for n in ['release.json','deployment.json']:
            try:
                m=json.loads((p/n).read_text());value=m.get('artifact_sha256')
                if value:protected_shas.add(value)
            except FileNotFoundError:pass
    for incoming in [base/'incoming',base/'access/incoming']:
        for side in incoming.glob('*.tar.gz.*'):
            if not Path(str(side).split('.tar.gz.')[0]+'.tar.gz').exists():skipped.append(str(side))
        for archive in incoming.glob('*.tar.gz'):
            if archive.is_symlink() or time.time()-archive.stat().st_mtime<48*3600:continue
            sha=digest(archive)
            if sha in protected_shas:continue
            side=Path(str(archive)+'.release.json');check=Path(str(archive)+'.sha256')
            if incoming==base/'incoming':
                try:m=json.loads(side.read_text());expected=check.read_text().split()[0]
                except (ValueError,OSError,IndexError):skipped.append(str(archive));continue
                if m.get('project_id')!='local.mediaforge' or m.get('artifact_sha256')!=sha or expected!=sha:
                    skipped.append(str(archive));continue
                candidate(archive,'verified superseded upload');candidate(side,'upload sidecar');candidate(check,'upload sidecar')
            else:
                matching=incoming.parent/'releases'/archive.name.removesuffix('.tar.gz')/'deployment.json'
                try:
                    if matching.exists():
                        m=json.loads(matching.read_text());valid=m.get('project_id')=='local.mediaforge' and m.get('artifact_sha256')==sha
                    else:
                        import tarfile
                        with tarfile.open(archive) as tar:
                            m=json.load(tar.extractfile('release.json'));manifest=json.load(tar.extractfile('site/manifest.json'))
                            valid=m.get('project_id')=='local.mediaforge' and m.get('source_commit')==archive.name.removesuffix('.tar.gz')
                            for f in manifest['files']:
                                content=tar.extractfile('files/'+Path(f['name']).name).read()
                                valid=valid and len(content)==f['size'] and hashlib.sha256(content).hexdigest()==f['sha256']
                    if valid:candidate(archive,'verified superseded delivery upload')
                    else:skipped.append(str(archive))
                except (OSError,ValueError,KeyError):skipped.append(str(archive))
    return {'project_id':'local.mediaforge','created_at':time.time(),'kept':{str(p):reasons.get(str(p),[]) for p in sorted(keep)},'candidates':candidates,'skipped':skipped}


def retain(base,apply=False):
    base=Path(base).resolve()
    if base==Path('/opt/mediaforge'):
        import socket
        if socket.gethostname()!='ser693712513899':raise RuntimeError('Wrong deployment host')
    with (base/'access/activation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=plan(base);result['applied']=apply;result['deleted']=[]
        before=shutil.disk_usage(base);result['disk_before']={'free':before.free,'used':before.used}
        if apply:
            # Validate the complete snapshot before mutating any upload group.
            if any(snapshot(Path(c['path']))[0]!=c['sha256_tree'] for c in result['candidates']):raise RuntimeError('Retention resources changed; preview again')
            current_refs=plan(base)
            if [x['path'] for x in current_refs['candidates']]!=[x['path'] for x in result['candidates']]:raise RuntimeError('Retention references changed; preview again')
            for c in result['candidates']:
                p=Path(c['path'])
                if p.is_dir():shutil.rmtree(p)
                else:p.unlink()
                result['deleted'].append(c)
            after=shutil.disk_usage(base);result['disk_after']={'free':after.free,'used':after.used}
            temp=base/'release-retention.next';temp.write_text(json.dumps(result,indent=2));os.replace(temp,base/'release-retention.json')
        return result
