"""Private, bounded, reconstructible previews. Authorization stays in the API."""
from pathlib import Path
import hashlib,json,os,time,subprocess,shutil
from filelock import FileLock
from PIL import Image,ImageOps
from .errors import ForgeError
from .files import sha256
from .dependencies import verified_binary


class PreviewCache:
    def __init__(self,root,max_bytes=128*1024**2,max_entries=256,ttl=86400):
        self.root=Path(root)/'preview-cache';self.root.mkdir(exist_ok=True,mode=0o700)
        self.lock=FileLock(str(self.root/'cache.lock'));self.max_bytes=max_bytes;self.max_entries=max_entries;self.ttl=ttl

    def prune(self):
        """Called with the cache lease; includes orphaned/incomplete entries."""
        rows=sorted((p for p in self.root.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True)
        kept=0;size=0
        for p in rows:
            n=sum(f.stat().st_size for f in p.iterdir() if f.is_file())
            if time.time()-p.stat().st_mtime>self.ttl or kept>=self.max_entries or size+n>self.max_bytes:
                shutil.rmtree(p)
            else:kept+=1;size+=n

    def clean(self):
        with self.lock.acquire(timeout=25):self.prune()

    @staticmethod
    def signature(path):
        s=path.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

    def get(self,owner,source,profile,page=1):
        spec={'image-thumb':(320,240),'image-screen':(1280,960),'pdf-page':(1400,1400)}[profile]
        identity={'owner_scope':hashlib.sha256(owner.encode()).hexdigest(),'parent_sha256':source['sha256'],'profile':profile,'page':page if profile=='pdf-page' else None,'spec':spec,'version':1}
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();folder=self.root/key
        path=Path(source['path']);signature=self.signature(path)
        with self.lock.acquire(timeout=25):
            self.prune();meta=None
            try:meta=json.loads((folder/'meta.json').read_text())
            except (OSError,ValueError):pass
            output=folder/'preview'
            if meta and meta.get('source_signature')==signature and output.is_file() and output.stat().st_size==meta['bytes'] and sha256(output)==meta['sha256']:
                os.utime(folder,None);return output,meta,'hit'
            if sha256(path)!=source['sha256']:
                raise ForgeError('source_changed','原文件内容已改变，预览已停止。','重新导入原件，不使用旧的SHA声明。',409)
            if folder.exists():shutil.rmtree(folder)
            folder.mkdir(mode=0o700)
            try:
                if profile.startswith('image-'):
                    with Image.open(path) as im:
                        image=ImageOps.exif_transpose(im);image.thumbnail(spec)
                        background=Image.new('RGB',image.size,'white')
                        if image.mode in {'RGBA','LA'} or 'transparency' in image.info:
                            rgba=image.convert('RGBA');background.paste(rgba,mask=rgba.getchannel('A'))
                        else:background.paste(image.convert('RGB'))
                        background.save(output,format='JPEG',quality=82)
                    mime='image/jpeg'
                else:
                    exe=verified_binary('poppler')
                    if not exe:raise ForgeError('dependency_missing','PDF 预览需要 Poppler。','在诊断页配置 PDF 渲染工具。',409)
                    result=subprocess.run([exe,'-f',str(page),'-l',str(page),'-singlefile','-scale-to','1400','-png',path,folder/'page'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
                    if result.returncode or not (folder/'page.png').is_file():raise ValueError('no PDF preview')
                    (folder/'page.png').replace(output);mime='image/png'
                if output.stat().st_size>16*1024**2:raise ValueError('preview too large')
                if self.signature(path)!=signature:raise ForgeError('source_changed','预览期间原文件发生变化。','重新导入原件。',409)
                with Image.open(output) as im:width,height=im.size;im.verify()
                meta={'id':'preview_'+key,'parent_sha256':source['sha256'],'profile':profile,'page':identity['page'],
                      'width':width,'height':height,'mime':mime,'bytes':output.stat().st_size,'sha256':sha256(output),
                      'source_signature':signature,'purpose':'browse_only','original_replaced':False}
                output.chmod(0o600);(folder/'meta.json').write_text(json.dumps(meta));(folder/'meta.json').chmod(0o600)
                self.prune();return output,meta,'miss'
            except BaseException as exc:
                shutil.rmtree(folder,ignore_errors=True)
                if isinstance(exc,ForgeError):raise
                raise ForgeError('preview_failed','预览生成未完成。','可查看原件，或稍后重试。',500) from None
