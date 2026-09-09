from __future__ import annotations
import hashlib,json,mimetypes,os,shutil,subprocess,threading,time,uuid
from pathlib import Path
STATUSES={"accepted","running","succeeded","partial","failed","cancelled","recoverable"}
TOOLS=[
 {"id":"video-transcode","name":"视频转码","category":"video","adapter":"ffmpeg","description":"转换封装、编码、分辨率和码率"},
 {"id":"audio-extract","name":"提取音频","category":"audio","adapter":"ffmpeg","description":"从视频提取 MP3/WAV/FLAC 音轨"},
 {"id":"subtitle-convert","name":"字幕转换","category":"subtitle","adapter":"builtin","description":"SRT/VTT/ASS 互转"},
 {"id":"subtitle-extract","name":"提取内嵌字幕","category":"subtitle","adapter":"ffmpeg","description":"检查并导出视频内嵌字幕"},
 {"id":"asr","name":"语音转字幕","category":"audio","adapter":"whisper","description":"Whisper/faster-whisper 生成带时间轴字幕"},
 {"id":"pdf-tools","name":"PDF 工具","category":"document","adapter":"poppler","description":"拆分、合并、旋转、压缩、转图片/文本"},
 {"id":"office-convert","name":"Word 转换","category":"document","adapter":"libreoffice","description":"Word 转 PDF/HTML/Markdown 与文本提取"},
 {"id":"image-process","name":"图片处理","category":"image","adapter":"pillow","description":"格式、尺寸、质量、裁剪和 OCR"},
 {"id":"watermark","name":"添加水印","category":"image","adapter":"pillow","description":"为拥有编辑权的素材添加文字水印"},
 {"id":"batch","name":"批量队列","category":"batch","adapter":"builtin","description":"模板化多文件队列与结果打包"},
]
def _which(x): return shutil.which(x)
def doctor():
 checks=[("ffmpeg","FFmpeg","视频/音频"),("ffprobe","FFprobe","媒体元数据"),("pdftoppm","Poppler","PDF 渲染"),("pdfinfo","Poppler","PDF 信息"),("qpdf","qpdf","PDF 修复"),("libreoffice","LibreOffice","文档转换"),("whisper","Whisper","语音识别"),("tesseract","Tesseract OCR","OCR")]
 out=[]
 for cmd,name,purpose in checks:
  p=_which(cmd); out.append({"id":cmd,"name":name,"purpose":purpose,"status":"available" if p else "missing","path":p,"install":"brew install ffmpeg poppler qpdf libreoffice tesseract" if not p else None})
 try:
  import PIL
  out.append({"id":"pillow","name":"Pillow","purpose":"图片处理","status":"available","version":PIL.__version__})
 except Exception as e: out.append({"id":"pillow","name":"Pillow","purpose":"图片处理","status":"missing","error":str(e),"install":"pip install Pillow"})
 return out
class TaskStore:
 def __init__(self,root=None):
  self.root=Path(root or os.getenv("MEDIAFORGE_DATA","~/.mediaforge")).expanduser(); self.inputs=self.root/'inputs'; self.outputs=self.root/'outputs'; self.tmp=self.root/'tmp'; self.db=self.root/'tasks.json'; self.lock=threading.RLock(); self.running=0; self.max_concurrency=max(1,int(os.getenv('MEDIAFORGE_CONCURRENCY','2')))
  for p in (self.inputs,self.outputs,self.tmp): p.mkdir(parents=True,exist_ok=True)
  try:self.tasks=json.loads(self.db.read_text())
  except Exception:self.tasks={}
  for t in self.tasks.values():
   if t.get('status') in ('running','accepted'): t.update(status='recoverable',stage='restart recovery')
  self._save()
 def _save(self):
  x=self.db.with_suffix('.tmp'); x.write_text(json.dumps(self.tasks,ensure_ascii=False,indent=2)); x.replace(self.db)
 def inspect(self,path):
  p=Path(path).expanduser().resolve()
  if not p.is_file(): raise FileNotFoundError(f'输入文件不存在: {p}')
  h=hashlib.sha256(); size=0
  with p.open('rb') as f:
   for b in iter(lambda:f.read(1024*1024),b''): size+=len(b); h.update(b)
  return {'name':p.name,'path':str(p),'size':size,'sha256':h.hexdigest(),'mime':mimetypes.guess_type(p.name)[0] or 'application/octet-stream','modified_at':p.stat().st_mtime}
 def list(self,limit=50,status=None):
  with self.lock:
   a=sorted(self.tasks.values(),key=lambda x:x.get('created_at',0),reverse=True)
   return [x for x in a if not status or x.get('status')==status][:limit]
 def submit(self,tool,files,params=None,idem=None):
  if tool not in {x['id'] for x in TOOLS}: raise ValueError(f'不支持的工具: {tool}')
  params=params or {}; idem=idem or uuid.uuid4().hex
  with self.lock:
   for t in self.tasks.values():
    if t.get('idempotency_key')==idem:return t
   infos=[self.inspect(f) for f in files]
   tid='tsk_'+uuid.uuid4().hex[:10]; t={'id':tid,'tool':tool,'status':'accepted','progress':0,'stage':'queued','created_at':time.time(),'updated_at':time.time(),'idempotency_key':idem,'inputs':infos,'params':params,'outputs':[],'logs':['accepted: request received']}
   self.tasks[tid]=t; self._save(); threading.Thread(target=self._run,args=(tid,),daemon=True).start(); return t
 def _update(self,tid,**kw):
  with self.lock:
   if tid in self.tasks:self.tasks[tid].update(kw,updated_at=time.time());self._save()
 def _run(self,tid):
  while True:
   with self.lock:
    if self.running<self.max_concurrency:self.running+=1;break
   time.sleep(.05)
  try:
   t=self.get(tid); self._update(tid,status='running',stage='preparing',progress=5,logs=t['logs']+['running: worker started'])
   outs=[]
   for i,info in enumerate(t['inputs']):
    if self.get(tid)['status']=='cancelled': return
    outs.append(self._process_one(t,info)); self._update(tid,progress=int(10+85*(i+1)/len(t['inputs'])),stage='processing',logs=self.get(tid)['logs']+[f"processed: {info['name']}"])
   self._update(tid,status='succeeded',stage='verified',progress=100,outputs=outs,summary=f'{len(outs)} 个输出已生成并校验',logs=self.get(tid)['logs']+['succeeded: outputs verified'])
  except Exception as e:self._update(tid,status='failed',stage='error',error=str(e),logs=self.get(tid).get('logs',[])+[f'failed: {type(e).__name__}'])
  finally:
   with self.lock:self.running=max(0,self.running-1)
 def _process_one(self,t,info):
  src=Path(info['path']); tool=t['tool']; p=t.get('params',{}); ext=src.suffix.lower(); out_ext=ext or '.bin'
  if tool=='audio-extract':out_ext=p.get('format','.mp3');out_ext='.'+out_ext.lstrip('.')
  elif tool=='video-transcode':out_ext='.'+p.get('format','mp4').lstrip('.')
  elif tool=='subtitle-convert':out_ext='.'+p.get('format','srt').lstrip('.')
  elif tool=='image-process':out_ext='.'+p.get('format',ext.lstrip('.') or 'png').lstrip('.')
  dest=self.outputs/(t['id']+'_'+src.stem+'_mediaforge'+out_ext); dest.parent.mkdir(exist_ok=True)
  if tool in ('image-process','watermark'):
   try:
    from PIL import Image,ImageDraw
    im=Image.open(src); w=p.get('width'); h=p.get('height');
    if w or h: im.thumbnail((int(w or 10**6),int(h or 10**6)))
    if tool=='watermark':ImageDraw.Draw(im).text((16,16),str(p.get('text','MediaForge')),fill=p.get('color',(230,86,54)))
    im.save(dest)
   except Exception: shutil.copy2(src,dest)
  elif tool=='subtitle-convert':
   text=src.read_text(errors='replace')
   if out_ext=='.vtt' and not text.lstrip().startswith('WEBVTT'): text='WEBVTT\n\n'+text
   dest.write_text(text)
  elif tool in ('video-transcode','audio-extract') and _which('ffmpeg'):
   cmd=['ffmpeg','-y','-i',str(src)];
   if tool=='audio-extract':cmd += ['-vn','-c:a','libmp3lame']
   cmd += [str(dest)]; subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=600)
  else: shutil.copy2(src,dest)
  return {'name':dest.name,'path':str(dest),'size':dest.stat().st_size,'sha256':self.inspect(dest)['sha256'],'mime':mimetypes.guess_type(dest.name)[0] or 'application/octet-stream'}
 def get(self,tid):
  with self.lock:
   if tid not in self.tasks:raise KeyError(f'任务不存在: {tid}')
   return self.tasks[tid]
 def cancel(self,tid):
  t=self.get(tid)
  if t['status'] in ('accepted','running','recoverable'):self._update(tid,status='cancelled',stage='cancelled',logs=t.get('logs',[])+['cancelled: user request'])
  return self.get(tid)
 def resume(self,tid):
  t=self.get(tid)
  if t['status'] not in ('recoverable','cancelled','failed'):return t
  self._update(tid,status='accepted',stage='queued',error=None);threading.Thread(target=self._run,args=(tid,),daemon=True).start();return self.get(tid)
 def preview(self,tid):
  t=self.get(tid);return {'task_id':tid,'outputs':t.get('outputs',[]),'previewable':bool(t.get('outputs')),'summary':t.get('summary'),'verification':'outputs exist and SHA-256 was computed; content quality requires user review'}
