"""Inspect actual bytes. Paths here are internal and never serialized to clients."""
import hashlib
import json
import mimetypes
import subprocess
import warnings
import zipfile
from pathlib import Path
from .dependencies import binary
from .errors import ForgeError


MIME = {'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','doc':'application/msword',
        'subtitle':'text/plain','text':'text/plain','zip':'application/zip','unknown':'application/octet-stream'}


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def probe(path):
    exe=binary('ffprobe')
    if not exe:
        raise ForgeError('dependency_missing','媒体检查需要 FFprobe。','安装 FFmpeg 后重试。',409)
    try:
        r=subprocess.run([exe,'-protocol_whitelist','file,pipe','-v','error','-show_entries','format=duration:stream=index,codec_type,codec_name,width,height,sample_rate,channels:stream_disposition=attached_pic','-of','json',str(path)],capture_output=True,timeout=20)
        if r.returncode or len(r.stdout)>4*1024**2: raise ValueError()
        return json.loads(r.stdout)
    except (ValueError,OSError,subprocess.TimeoutExpired):
        raise ForgeError('invalid_media','无法读取音视频信息。','文件可能损坏，或使用了不支持的格式。')


def inspect(path, name=None):
    p=Path(path); name=name or p.name
    size=p.stat().st_size
    if not size: raise ForgeError('empty_file','文件为空。','请选择有内容的文件。')
    with p.open('rb') as f: header=f.read(4096)
    suffix=Path(name).suffix.lower()
    data={'size':size,'sha256':sha256(p),'kind':'unknown','mime':'application/octet-stream','warnings':[]}
    if header.lstrip().startswith(b'%PDF-'):
        from pypdf import PdfReader
        data.update(kind='pdf',mime=MIME['pdf'])
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                reader=PdfReader(p,strict=False)
                data['encrypted']=reader.is_encrypted
                if not reader.is_encrypted or reader.decrypt(''):
                    data['pages']=len(reader.pages)
        except Exception:
            raise ForgeError('damaged_pdf','PDF 结构损坏，无法读取。','请重新导出源 PDF。')
    elif header.startswith(b'PK'):
        try:
            with zipfile.ZipFile(p) as z:
                entries=z.infolist()
                if len(entries)>20000 or sum(i.file_size for i in entries)>512*1024**2:
                    raise ForgeError('archive_limit','压缩文档展开大小超过限制。','缩小或拆分文档后重试。',413)
                names={i.filename for i in entries}
                data.update(kind='docx' if 'word/document.xml' in names else 'zip')
                data['mime']=MIME[data['kind']]
        except zipfile.BadZipFile: raise ForgeError('damaged_document','文档结构损坏。','重新导出源文件。')
    elif header.startswith(b'\xd0\xcf\x11\xe0'):
        data.update(kind='doc',mime=MIME['doc'])
    else:
        from PIL import Image, UnidentifiedImageError
        Image.MAX_IMAGE_PIXELS=60_000_000
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(p) as im:
                    data.update(kind='image',mime=Image.MIME.get(im.format,'image/png'),width=im.width,height=im.height,frames=getattr(im,'n_frames',1))
                    im.verify()
        except (Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise ForgeError('image_too_large','图像像素数超过处理限制。','请先降低图片分辨率。',413)
        except (UnidentifiedImageError,OSError,SyntaxError):
            if suffix in {'.srt','.vtt','.ass','.ssa'}:
                try:
                    import pysubs2
                    subs=pysubs2.load(str(p),encoding='utf-8-sig')
                    if not len(subs): raise ValueError()
                    data.update(kind='subtitle',mime='text/vtt' if suffix=='.vtt' else 'text/plain',cues=len(subs))
                except Exception: raise ForgeError('invalid_subtitle','字幕格式或编码无法识别。','使用 UTF-8 编码的 SRT、VTT 或 ASS 字幕。')
            elif suffix in {'.txt','.md','.csv','.json','.html','.htm'} and b'\x00' not in header:
                try: header.decode('utf-8')
                except UnicodeDecodeError: raise ForgeError('invalid_text','文本不是 UTF-8 编码。','请将文件编码转换为 UTF-8。')
                data.update(kind='text',mime=mimetypes.guess_type(name)[0] or 'text/plain')
            else:
                try:
                    signatures = (header[4:8] == b'ftyp' or header.startswith((b'RIFF',b'fLaC',b'OggS',b'ID3',b'\x1aE\xdf\xa3',b'FORM',b'\x00\x00\x01')) or (len(header)>1 and header[0]==255 and header[1]&0xe0==0xe0))
                    if not signatures: raise ValueError()
                    info=probe(p)
                    streams=info.get('streams',[])
                    # Cover artwork does not turn an audio file into a video task input.
                    video=[s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')]
                    audio=[s for s in streams if s.get('codec_type')=='audio']
                    if not video and not audio: raise ValueError()
                    kind='video' if video else 'audio'
                    data.update(kind=kind,mime=mimetypes.guess_type(name)[0] or kind+'/octet-stream',
                                duration=float(info.get('format',{}).get('duration',0)),
                                streams=[{k:s[k] for k in ['index','codec_type','codec_name','width','height','sample_rate','channels'] if k in s} for s in streams])
                except (ForgeError,ValueError):
                    raise ForgeError('unsupported_file','文件格式不支持或文件已损坏。','请选择有效的媒体、PDF、Word、图片或 UTF-8 字幕文件。')
    if data['kind']=='unknown': raise ForgeError('unsupported_file','无法识别文件内容。','不要仅修改文件扩展名；请重新导出文件。')
    return data
