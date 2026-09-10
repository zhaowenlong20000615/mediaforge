import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
from .errors import ForgeError


def binary(name):
    names = {'libreoffice':['libreoffice','soffice'], 'poppler':['pdftoppm']}.get(name,[name])
    for candidate in names:
        found = shutil.which(candidate)
        if found:
            return found
    if name == 'libreoffice':
        mac = Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')
        if mac.exists(): return str(mac)
    return None


def installed(module):
    try: return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError): return False


def checks():
    linux = platform.system() == 'Linux'
    install = 'sudo apt-get install ffmpeg poppler-utils tesseract-ocr tesseract-ocr-chi-sim libreoffice fonts-noto-cjk' if linux else 'brew install ffmpeg poppler tesseract tesseract-lang libreoffice'
    result = []
    for id, command, purpose in [('ffmpeg','ffmpeg','音视频处理'),('ffprobe','ffprobe','媒体检查'),('poppler','poppler','PDF 渲染'),('tesseract','tesseract','OCR'),('libreoffice','libreoffice','Office/PDF 导出')]:
        available = bool(binary(command))
        result.append({'id':id,'name':command,'available':available,'status':'available' if available else 'missing',
                       'purpose':purpose,'install':install if not available else '', 'details':{}})
    for id, module in [('pillow','PIL'),('pypdf','pypdf'),('docx','docx'),('pdfplumber','pdfplumber'),('pysubs2','pysubs2'),('opencv','cv2')]:
        available = installed(module)
        result.append({'id':id,'name':id,'available':available,'status':'available' if available else 'missing','purpose':'文件处理',
                       'install':'uv sync --extra repair' if id == 'opencv' else 'uv sync --frozen', 'details':{}})
    model = Path(os.getenv('MEDIAFORGE_ASR_MODEL','/nonexistent'))
    has_model = model.is_dir() and (model/'model.bin').is_file() and (model/'config.json').is_file()
    gpu = 0
    if installed('ctranslate2'):
        try:
            import ctranslate2
            gpu = ctranslate2.get_cuda_device_count()
        except Exception: pass
    available = installed('faster_whisper') and has_model
    result.append({'id':'asr-model','name':'Faster Whisper','available':available,'status':'available' if available else 'missing',
                   'purpose':'离线语音转写','install':'uv sync --extra asr；配置 MEDIAFORGE_ASR_MODEL 为已下载的 CTranslate2 模型目录。',
                   'details':{'library':installed('faster_whisper'),'model_configured':has_model,'cpu':True,'cuda_devices':gpu}})
    model_dir = Path(os.getenv('U2NET_HOME','/nonexistent'))
    available = installed('rembg') and (model_dir/'u2net.onnx').is_file()
    result.append({'id':'background-model','name':'U²-Net','available':available,'status':'available' if available else 'missing',
                   'purpose':'离线去背景','install':'uv sync --extra background；在 U2NET_HOME 配置 u2net.onnx。','details':{'model_configured':(model_dir/'u2net.onnx').is_file()}})
    available=bool(font_path())
    result.append({'id':'font','name':'水印字体','available':available,'status':'available' if available else 'missing','purpose':'文字水印','install':'配置 MEDIAFORGE_FONT，或安装 Noto CJK 字体。','details':{}})
    return result


def required(tool, params=None, input_kinds=None):
    deps = list(tool['dependencies'])
    if 'office-dynamic' in deps:
        deps.remove('office-dynamic')
        deps.append('libreoffice' if (params or {}).get('format','pdf')=='pdf' or 'doc' in (input_kinds or []) else 'docx')
    if 'ffmpeg' in deps: deps.append('ffprobe')
    return deps


def ensure(tool, params, input_kinds):
    indexed = {x['id']:x for x in checks()}
    missing = [indexed[x] for x in required(tool,params,input_kinds) if not indexed[x]['available']]
    if missing:
        raise ForgeError('dependency_missing','尚未配置：'+ '、'.join(x['name'] for x in missing),
                         '打开诊断页面，按安装说明配置后再恢复任务。',409)
    if tool['id']=='asr' and params.get('device')=='cuda' and not indexed['asr-model']['details']['cuda_devices']:
        raise ForgeError('gpu_unavailable','没有可用的 CUDA GPU。','将计算设备改为 CPU。',409)


def catalog_status(tools):
    status = {x['id']:x for x in checks()}
    return [{**t,'available':all(status[x]['available'] for x in required(t)),
             'missing':[x for x in required(t) if not status[x]['available']]} for t in tools]


def ocr_languages():
    exe=binary('tesseract')
    if not exe: return []
    try:
        p=subprocess.run([exe,'--list-langs'],capture_output=True,text=True,timeout=8)
        return [line.strip() for line in p.stdout.splitlines() if line.strip() and not line.startswith('List of')]
    except (OSError,subprocess.TimeoutExpired): return []


def font_path():
    candidates=[os.getenv('MEDIAFORGE_FONT',''),'/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Medium.ttc','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    return next((x for x in candidates if x and Path(x).is_file()),None)
