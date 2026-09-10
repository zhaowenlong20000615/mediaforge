"""Bounded adapter process. All transforms either produce verified outputs or fail."""
from pathlib import Path
import csv
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import warnings
from .errors import ForgeError,safe_error
from .dependencies import binary,ocr_languages
from .files import probe


class Context:
    def __init__(self,request):
        self.r=request; self.work=Path(request['work']); self.outputs=[]
        self.p=request['params']; self.files=request['inputs']; self.op=request['operation']

    def progress(self,n,stage):
        temp=self.work/'progress.next'
        temp.write_text(json.dumps({'percent':n,'stage':stage},ensure_ascii=False))
        temp.replace(self.work/'progress.json')

    def out(self,path,name=None,verification=None):
        path=Path(path)
        if not path.is_file() or path.stat().st_size==0:
            raise ForgeError('empty_output','工具没有生成有效输出。','检查输入内容或调整参数。')
        self.outputs.append({'path':str(path),'name':name or path.name,'verification':verification or {'readable':True}})
        if len(self.outputs)>self.r['max_outputs']: raise ForgeError('too_many_outputs','输出数量超过限制。','缩小页码范围或减少抽帧数。')

    def run(self,args,*,progress=False,duration=0):
        errpath=self.work/'tool.stderr'
        with errpath.open('wb') as err:
            proc=subprocess.Popen([str(a) for a in args],stdout=subprocess.PIPE,stderr=err,cwd=self.work)
            if progress:
                output=b''
                for line in proc.stdout:
                    if line.startswith(b'out_time_us=') and duration:
                        try:self.progress(min(92,8+float(line.split(b'=')[1])/1_000_000/duration*84),'正在编码')
                        except ValueError:pass
                proc.wait()
            else:
                output,_=proc.communicate()
                if len(output)>16*1024**2: raise ForgeError('tool_output_limit','工具输出超过安全限制。')
        if proc.returncode:
            text=errpath.read_bytes()[-8192:].decode('utf-8','replace').lower()
            if 'password' in text or 'encrypted' in text: raise ForgeError('password_required','文件已加密或密码不正确。','填写正确的打开密码。')
            if 'no such filter' in text or 'unknown encoder' in text: raise ForgeError('codec_unavailable','当前工具链缺少需要的编码器或滤镜。','在诊断页更新 FFmpeg。')
            raise ForgeError('adapter_failed','处理工具未能完成此文件。','检查文件格式或重新导出源文件，再重试此项。')
        return output

    def ffmpeg(self,args,duration=0):
        return self.run([binary('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-y','-threads','2','-filter_threads','2','-protocol_whitelist','file,pipe',*args,'-progress','pipe:1','-nostats'],progress=True,duration=duration)


def check_track(file,kind,track=0):
    streams=[s for s in file.get('streams',[]) if s.get('codec_type')==kind]
    if track>=len(streams):
        code='no_audio' if kind=='audio' else 'no_subtitle'
        raise ForgeError(code,'没有所选音轨。' if kind=='audio' else '没有所选字幕轨。','查看文件信息中的轨道列表后选择。')
    return streams[track]


def media(c):
    f=c.files[0]; src=f['path']; p=c.p; op=c.op; duration=f.get('duration',0)
    c.progress(5,'检查媒体轨道')
    if op=='video-transcode' or op=='media-compress' and f['kind']=='video':
        fmt=p.get('format','mp4'); out=c.work/('video.'+fmt)
        filters=['scale=trunc(iw/2)*2:trunc(ih/2)*2']
        if p.get('width'): filters=['scale='+str(p['width']//2*2)+':-2']
        codec='libvpx-vp9' if fmt=='webm' else 'libx264'
        args=['-i',src,'-map','0:v:0','-map','0:a?','-vf',','.join(filters),'-c:v',codec,'-crf',str(p.get('crf',28)),
              '-c:a','libopus' if fmt=='webm' else 'aac']
        if fmt=='webm':args+=['-b:v','0']
        else:args+=['-preset','fast']
        if fmt=='mp4':args+=['-movflags','+faststart']
        c.ffmpeg(args+[out],duration)
        c.out(out,verification={'operation':op,'expected_container':fmt,'codec':codec}); return
    if op in {'audio-extract','audio-normalize','audio-denoise','media-compress'}:
        track=p.get('track',0); check_track(f,'audio',track)
        fmt=p.get('format','mp3' if op=='media-compress' else 'wav')
        codec={'mp3':'libmp3lame','wav':'pcm_s16le','flac':'flac','m4a':'aac','ogg':'libvorbis'}[fmt]
        out=c.work/('audio.'+fmt)
        args=['-i',src,'-map',f'0:a:{track}','-vn','-c:a',codec]
        if op=='audio-normalize':args+=['-af',f'loudnorm=I={p["lufs"]}:TP=-1.5:LRA=11','-ar','48000']
        if op=='audio-denoise':args+=['-af',f'afftdn=nr={p["strength"]}']
        if op=='media-compress':args+=['-b:a',str(p['audio_kbps'])+'k']
        c.ffmpeg(args+[out],duration)
        actual=probe(out); codecs=[s['codec_name'] for s in actual['streams'] if s['codec_type']=='audio']
        c.out(out,verification={'audio_codecs':codecs,'source_track':track}); return
    if op=='media-trim':
        start=p['start']; length=p['duration']
        if duration and start>=duration:raise ForgeError('invalid_range','开始时间超过媒体时长。','设置更早的开始时间。')
        out=c.work/('clip.mp4' if f['kind']=='video' else 'clip.wav')
        args=['-i',src,'-ss',str(start),'-t',str(length)]
        if f['kind']=='video':args+=['-map','0:v:0','-map','0:a?','-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-preset','fast','-c:a','aac','-movflags','+faststart']
        else:args+=['-map','0:a:0','-c:a','pcm_s16le']
        c.ffmpeg(args+[out],length)
        actual=float(probe(out)['format'].get('duration',0))
        expected=min(length,max(0,duration-start)) if duration else length
        if actual<=0 or abs(actual-expected)>max(.25,expected*.03):raise ForgeError('verification_failed','输出时长与裁剪范围不一致。')
        c.out(out,verification={'requested_start':start,'expected_duration':expected,'actual_duration':actual}); return
    if op=='video-frames':
        out=c.work/'frame-%04d.png'
        c.ffmpeg(['-i',src,'-vf',f'fps=1/{p["interval"]}','-frames:v',str(p['count']),out],duration)
        frames=sorted(c.work.glob('frame-*.png'))
        if not frames:raise ForgeError('no_frames','所选间隔内没有可提取的视频帧。','缩短抽帧间隔。')
        for file in frames:c.out(file,verification={'decoded_frame':True})
        return
    if op=='media-merge':
        is_video=p['kind']=='video'; normalized=[]
        for i,file in enumerate(c.files):
            c.progress(5+i/len(c.files)*75,f'标准化第 {i+1} 个文件')
            part=c.work/(f'part-{i}.mp4' if is_video else f'part-{i}.wav')
            if is_video:
                if file['kind']!='video':raise ForgeError('unsupported_input','视频合并只接受视频。','选择音频合并以提取并合并音轨。')
                args=['-i',file['path']]
                if not any(s['codec_type']=='audio' for s in file.get('streams',[])):
                    args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-shortest']
                args+=['-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
                       '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',part]
            else:
                check_track(file,'audio')
                args=['-i',file['path'],'-map','0:a:0','-vn','-ar','48000','-ac','2','-c:a','pcm_s16le',part]
            c.ffmpeg(args); normalized.append(part)
        manifest=c.work/'concat.txt'
        manifest.write_text('\n'.join("file '"+p.name+"'" for p in normalized))
        out=c.work/('merged.mp4' if is_video else 'merged.wav')
        c.ffmpeg(['-f','concat','-safe','1','-i',manifest,'-c','copy',out],sum(f.get('duration',0) for f in c.files))
        c.out(out,verification={'merged_files':len(normalized),'order_preserved':True}); return
    raise ForgeError('unknown_operation','未实现的媒体操作。')


def subtitles(c):
    p=c.p; src=c.files[0]['path']; fmt=p.get('format','srt')
    out=c.work/('subtitles.'+fmt)
    if c.op=='subtitle-convert':
        import pysubs2
        subs=pysubs2.load(src,encoding='utf-8-sig')
        if not len(subs): raise ForgeError('empty_subtitle','字幕没有有效条目。')
        subs.save(str(out),format_=fmt,encoding='utf-8')
        check=pysubs2.load(str(out),encoding='utf-8')
        if len(check)!=len(subs):raise ForgeError('verification_failed','转换后字幕条目数量不一致。')
        c.out(out,verification={'cues':len(check),'format':fmt})
    else:
        stream=check_track(c.files[0],'subtitle',p['track'])
        if stream.get('codec_name') in {'hdmv_pgs_subtitle','dvd_subtitle','dvb_subtitle','xsub'}:
            raise ForgeError('image_subtitle','此轨道是图片字幕，不能直接导出为文本。','请先将字幕渲染为图像，再进行 OCR。')
        c.ffmpeg(['-i',src,'-map',f'0:s:{p["track"]}',out])
        import pysubs2
        subs=pysubs2.load(str(out),encoding='utf-8')
        if not subs:raise ForgeError('empty_subtitle','所选轨道没有字幕条目。')
        c.out(out,verification={'cues':len(subs),'source_track':p['track']})


def asr(c):
    from faster_whisper import WhisperModel
    import pysubs2
    check_track(c.files[0],'audio')
    c.progress(8,'加载本地语音模型')
    device=c.p['device']
    model=WhisperModel(os.environ['MEDIAFORGE_ASR_MODEL'],device=device,compute_type='int8' if device=='cpu' else 'float16',cpu_threads=2,local_files_only=True)
    segments,info=model.transcribe(c.files[0]['path'],language=c.p['language'] or None,beam_size=3)
    subs=pysubs2.SSAFile(); texts=[]
    for segment in segments:
        text=segment.text.strip()
        if text:
            subs.append(pysubs2.SSAEvent(start=int(segment.start*1000),end=int(segment.end*1000),text=text)); texts.append(text)
        c.progress(min(94,10+segment.end/max(info.duration,1)*84),'正在识别语音')
    if not texts:raise ForgeError('no_speech','没有识别出有效语音。','检查音轨、人声清晰度和语言设置。')
    for fmt in ['srt','vtt']:
        file=c.work/('transcript.'+fmt); subs.save(str(file),format_=fmt,encoding='utf-8'); c.out(file,verification={'segments':len(subs),'language':info.language})
    file=c.work/'transcript.txt';file.write_text('\n'.join(texts),encoding='utf-8'); c.out(file,verification={'segments':len(subs)})


def pdf_reader(path,password):
    from pypdf import PdfReader
    try:
        reader=PdfReader(path,strict=False)
        if reader.is_encrypted:
            if not password and not reader.decrypt(''):raise ForgeError('password_required','此 PDF 需要打开密码。','在参数中填写密码后重新提交。')
            if password and not reader.decrypt(password):raise ForgeError('wrong_password','PDF 打开密码不正确。','核实密码后重新提交任务。')
        if not len(reader.pages):raise ForgeError('empty_pdf','PDF 没有页面。')
        if len(reader.pages)>500:raise ForgeError('page_limit','单份 PDF 超过 500 页处理限制。','先拆分为较小的文档。',413)
        return reader
    except ForgeError:raise
    except Exception:raise ForgeError('damaged_pdf','PDF 结构损坏或加密方式不支持。','重新导出源文档。')


def page_indices(value,total):
    if not value.strip(): return list(range(total))
    result=[]
    try:
        for block in value.replace(' ','').split(','):
            if '-' in block:
                start,end=map(int,block.split('-'))
                if start>end:raise ValueError()
                result.extend(range(start-1,end))
            else:result.append(int(block)-1)
        if not result or min(result)<0 or max(result)>=total:raise ValueError()
        return list(dict.fromkeys(result))
    except (ValueError,TypeError):raise ForgeError('page_range','页码范围无效。',f'请输入 1–{total} 内的页码，如 1-3,5。')


def write_pdf(writer,path):
    with path.open('wb') as out: writer.write(out)
    check=pdf_reader(path,'')
    return len(check.pages)


def ocr(c,image,base,searchable=False):
    language=c.p.get('language','eng')
    if not set(language.split('+'))<=set(ocr_languages()):
        raise ForgeError('ocr_language_missing','所选 OCR 语言包未安装。','在诊断页查看可用语言并选择，或请管理员安装。')
    args=[binary('tesseract'),str(image),str(base),'-l',language]
    args+=['pdf','txt'] if searchable else ['txt']
    c.run(args)
    return base.with_suffix('.txt').read_text(encoding='utf-8').strip()


def pdf(c):
    from pypdf import PdfWriter
    readers=[pdf_reader(f['path'],c.p.get('password','')) for f in c.files]
    reader=readers[0]; pages=page_indices(c.p.get('pages',''),len(reader.pages)); op=c.op
    c.progress(10,'读取 PDF 页面')
    if op=='pdf-split':
        if len(pages)>c.r['max_outputs']:raise ForgeError('too_many_outputs','拆分页面数超过输出限制。')
        for j,i in enumerate(pages):
            w=PdfWriter();w.add_page(reader.pages[i]);out=c.work/f'page-{i+1:04}.pdf'
            count=write_pdf(w,out);c.out(out,verification={'pages':count,'source_page':i+1});c.progress(10+(j+1)/len(pages)*80,'正在拆分页面')
    elif op in {'pdf-merge','pdf-rotate','pdf-compress'}:
        w=PdfWriter()
        for r in readers:
            for i,page in enumerate(r.pages):
                if op=='pdf-rotate' and i in pages: page.rotate(int(c.p['angle']))
                w.add_page(page)
        if op=='pdf-compress':
            for page in w.pages:page.compress_content_streams()
            if hasattr(w,'compress_identical_objects'):w.compress_identical_objects(remove_identicals=True,remove_orphans=True)
        out=c.work/(op.removeprefix('pdf-')+'.pdf');count=write_pdf(w,out)
        evidence={'pages':count,'source_pages':sum(len(r.pages) for r in readers)}
        if op=='pdf-rotate':evidence['rotations']=[int(p.get('/Rotate',0)) for p in pdf_reader(out,'').pages]
        c.out(out,verification=evidence)
    elif op in {'pdf-text','pdf-word'}:
        texts=[reader.pages[i].extract_text() or '' for i in pages]
        if not any(x.strip() for x in texts):raise ForgeError('no_text_layer','PDF 没有可提取的文本层。','使用 PDF OCR 识别扫描文档。')
        if op=='pdf-text':
            out=c.work/'document.txt';out.write_text('\n\n'.join(texts),encoding='utf-8')
        else:
            from docx import Document
            doc=Document()
            for i,text in enumerate(texts):
                if i:doc.add_page_break()
                for para in text.splitlines():doc.add_paragraph(para)
            out=c.work/'document.docx';doc.save(out)
        c.out(out,verification={'source_pages':len(texts),'mode':'text_reflow'})
    elif op in {'pdf-images','pdf-ocr'}:
        # Write decrypted bytes privately; never pass a password on a process command line.
        w=PdfWriter()
        for i in pages:w.add_page(reader.pages[i])
        decrypted=c.work/'private-input.pdf';write_pdf(w,decrypted)
        texts=[];searchable=PdfWriter()
        for j,i in enumerate(pages):
            prefix=c.work/f'page-{i+1:04}';dpi=c.p.get('dpi',150)
            c.run([binary('poppler'),'-f',str(j+1),'-l',str(j+1),'-singlefile','-r',str(dpi),'-png',decrypted,prefix])
            image=prefix.with_suffix('.png')
            if op=='pdf-images':c.out(image,verification={'source_page':i+1,'dpi':dpi})
            else:
                outbase=c.work/f'ocr-{i+1:04}'
                texts.append(ocr(c,image,outbase,True))
                for page in pdf_reader(outbase.with_suffix('.pdf'),'').pages:searchable.add_page(page)
            c.progress(10+(j+1)/len(pages)*82,'逐页渲染与识别' if op=='pdf-ocr' else '渲染页面')
        if op=='pdf-ocr':
            if not any(texts):raise ForgeError('no_text','没有识别出文字。','检查扫描清晰度和 OCR 语言设置。')
            text=c.work/'recognized.txt';text.write_text('\n\n'.join(texts),encoding='utf-8');c.out(text)
            out=c.work/'searchable.pdf';count=write_pdf(searchable,out);c.out(out,verification={'pages':count,'searchable':True})
    elif op=='pdf-tables':
        import pdfplumber
        tables=[]
        with pdfplumber.open(c.files[0]['path'],password=c.p.get('password') or None) as document:
            for idx,page in enumerate(document.pages):
                for table in page.extract_tables():
                    if not table:continue
                    tables.append({'page':idx+1,'rows':table})
                    out=c.work/f'table-{len(tables):03}.csv'
                    with out.open('w',encoding='utf-8-sig',newline='') as f:
                        writer=csv.writer(f)
                        for row in table:
                            writer.writerow([("'"+str(x)) if str(x or '').startswith(('=','+','-','@')) else (x or '') for x in row])
                    c.out(out,verification={'source_page':idx+1,'rows':len(table)})
                c.progress(10+(idx+1)/len(document.pages)*80,'检测表格')
        if not tables:raise ForgeError('no_tables','没有检测到可提取的表格。','扫描表格或复杂布局需要人工检查与重建。')
        out=c.work/'tables.json';out.write_text(json.dumps(tables,ensure_ascii=False),encoding='utf-8');c.out(out,verification={'tables':len(tables)})


def doc_blocks(doc):
    # Preserve the paragraph/table order in the main body.
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    for child in doc.element.body.iterchildren():
        if child.tag.endswith('}p'):yield 'paragraph',Paragraph(child,doc)
        elif child.tag.endswith('}tbl'):yield 'table',Table(child,doc)


def office(c):
    from docx import Document
    src=Path(c.files[0]['path']);p=c.p
    if c.op=='office-convert' and (p['format']=='pdf' or c.files[0]['kind']=='doc'):
        profile=c.work/'lo-profile';output=c.work/'lo-output';output.mkdir()
        fmt='pdf' if p['format']=='pdf' else 'docx'
        c.progress(15,'使用独立 Office 进程转换')
        c.run([binary('libreoffice'),'-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to',fmt,'--outdir',output,src])
        converted=output/(src.stem+'.'+fmt)
        if not converted.exists():raise ForgeError('office_conversion_failed','Office 转换没有生成结果。','检查文档是否加密或损坏。')
        if fmt=='pdf':
            count=len(pdf_reader(converted,'').pages);c.out(converted,'document.pdf',{'pages':count});return
        src=converted
    try:doc=Document(src)
    except Exception:raise ForgeError('invalid_word','无法打开 Word 文档。','请使用未加密、结构完整的 DOCX 文件。')
    if c.op=='word-replace':
        count=0;seen=set()
        def replace_paragraph(para):
            nonlocal count
            if id(para._p) in seen:return
            seen.add(id(para._p))
            old=p['find']; new=p['replace']; text=para.text
            positions=[m.start() for m in re.finditer(re.escape(old),text)]
            if not positions:return
            runs=para.runs; starts=[];offset=0
            for run in runs:starts.append(offset);offset+=len(run.text)
            for pos in reversed(positions):
                end=pos+len(old)
                affected=[i for i,r in enumerate(runs) if starts[i]<end and starts[i]+len(r.text)>pos]
                if not affected:continue
                first,last=affected[0],affected[-1]
                prefix=runs[first].text[:pos-starts[first]];suffix=runs[last].text[end-starts[last]:]
                runs[first].text=prefix+new+suffix
                for i in affected[1:]:runs[i].text=''
                count+=1
        def walk(container):
            for para in container.paragraphs:replace_paragraph(para)
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:walk(cell)
        walk(doc)
        for section in doc.sections:
            for part in [section.header,section.footer,section.first_page_header,section.first_page_footer,section.even_page_header,section.even_page_footer]:walk(part)
        if not count:raise ForgeError('no_matches','没有找到要替换的文字。','检查查找文字是否一致。')
        out=c.work/'replaced.docx';doc.save(out);Document(out);c.out(out,verification={'replacements':count});return
    fmt=p['format'];chunks=[]
    for kind,block in doc_blocks(doc):
        if kind=='paragraph':
            text=block.text
            if fmt=='html':chunks.append('<p>'+html.escape(text)+'</p>')
            elif fmt=='md' and block.style.name.startswith('Heading'):
                level=block.style.name.split()[-1];level=int(level) if level.isdigit() else 1
                chunks.append('#'*min(level,6)+' '+text)
            else:chunks.append(text)
        else:
            rows=[[cell.text for cell in row.cells] for row in block.rows]
            if fmt=='html':chunks.append('<table>'+''.join('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table>')
            elif fmt=='md':
                for i,row in enumerate(rows):
                    chunks.append('| '+' | '.join(x.replace('|','\\|').replace('\n',' ') for x in row)+' |')
                    if i==0:chunks.append('| '+' | '.join('---' for _ in row)+' |')
            else:chunks.extend('\t'.join(row) for row in rows)
    text='\n\n'.join(chunks)
    if not text.strip():raise ForgeError('no_text','文档没有可提取的文字。','图片内容可通过 OCR 处理。')
    if fmt=='html':text='<!doctype html><html><meta charset="utf-8"><title>Converted document</title><body>'+text+'</body></html>'
    out=c.work/('document.'+fmt);out.write_text(text,encoding='utf-8');c.out(out,verification={'mode':'semantic_text_and_tables'})


def font_path():
    candidates=[os.getenv('MEDIAFORGE_FONT',''),'/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Medium.ttc','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    return next((x for x in candidates if x and Path(x).is_file()),None)


def image(c):
    from PIL import Image,ImageOps,ImageDraw,ImageFont
    p=c.p;op=c.op
    with Image.open(c.files[0]['path']) as source:im=ImageOps.exif_transpose(source).copy()
    if op=='image-ocr':
        c.progress(20,'识别图片文字');text=ocr(c,c.files[0]['path'],c.work/'recognized')
        if not text:raise ForgeError('no_text','没有识别出文字。','检查图片清晰度或切换 OCR 语言。')
        c.out(c.work/'recognized.txt',verification={'language':p['language']});return
    if op=='image-pdf':
        pages=[]
        for file in c.files:
            with Image.open(file['path']) as source:pages.append(ImageOps.exif_transpose(source).convert('RGB'))
        out=c.work/'images.pdf';pages[0].save(out,save_all=True,append_images=pages[1:],resolution=100)
        count=len(pdf_reader(out,'').pages)
        if count!=len(pages):raise ForgeError('verification_failed','PDF 页数与图片数量不一致。')
        c.out(out,verification={'pages':count});return
    if op=='image-rename':
        suffix=Path(c.files[0]['name']).suffix.lower();name=f'{p["prefix"]}-{p["start"]+c.r["seq"]:04}{suffix}'
        out=c.work/name;shutil.copyfile(c.files[0]['path'],out)
        c.out(out,verification={'operation':'rename_copy','content_unchanged':True});return
    if op=='image-background':
        from rembg import remove,new_session
        c.progress(15,'加载本地抠图模型')
        session=new_session('u2net',providers=['CPUExecutionProvider']);im=remove(im,session=session)
    elif op=='image-repair':
        import cv2
        import numpy as np
        with Image.open(c.files[1]['path']) as src:mask=np.asarray(src.convert('L'))
        mask=(mask>127).astype('uint8')*255
        if not mask.any():raise ForgeError('empty_mask','遮罩没有白色修复区域。','使用与原图同尺寸的黑白遮罩。')
        source=cv2.cvtColor(np.asarray(im.convert('RGB')),cv2.COLOR_RGB2BGR)
        result=cv2.inpaint(source,mask,p['radius'],cv2.INPAINT_TELEA)
        im=Image.fromarray(cv2.cvtColor(result,cv2.COLOR_BGR2RGB))
    elif op=='image-crop':
        x,y,w,h=p['x'],p['y'],p['width'],p['height']
        if x+w>im.width or y+h>im.height:raise ForgeError('crop_range','裁剪范围超过原图尺寸。','根据文件信息调整坐标和尺寸。')
        im=im.crop((x,y,x+w,y+h))
    elif op=='watermark':
        path=font_path()
        if not path:raise ForgeError('font_missing','没有可用的水印字体。','配置 MEDIAFORGE_FONT 或安装 Noto CJK 字体。')
        font=ImageFont.truetype(path,p['size']);layer=Image.new('RGBA',im.size);draw=ImageDraw.Draw(layer)
        box=draw.textbbox((0,0),p['text'],font=font);w,h=box[2]-box[0],box[3]-box[1]
        if w+16>im.width or h+16>im.height:raise ForgeError('watermark_too_large','水印文字超出图片尺寸。','缩小文字或使用更大的图片。')
        pos=p['position'];x=16 if 'left' in pos else im.width-w-16;y=16 if 'top' in pos else im.height-h-16
        if pos=='center':x,y=(im.width-w)/2,(im.height-h)/2
        draw.text((x-box[0],y-box[1]),p['text'],font=font,fill=(255,255,255,round(p['opacity']*2.55)),stroke_width=1,stroke_fill=(25,30,35,round(p['opacity']*2.55)))
        im=Image.alpha_composite(im.convert('RGBA'),layer)
    elif op=='image-process':
        if p['width'] or p['height']:im.thumbnail((p['width'] or 16000,p['height'] or 16000),Image.Resampling.LANCZOS)
    fmt=p.get('format','png');out=c.work/('image.'+fmt)
    if fmt in {'jpeg','bmp'} and im.mode not in {'RGB','L'}:
        base=Image.new('RGB',im.size,'white');base.paste(im,mask=im.getchannel('A') if 'A' in im.getbands() else None);im=base
    im.save(out,quality=p.get('quality',85),optimize=True)
    with Image.open(out) as check:
        if check.size!=im.size:raise ForgeError('verification_failed','输出图片尺寸不一致。')
        check.verify()
    c.out(out,verification={'width':im.width,'height':im.height,'format':fmt,'animated_source_frames':c.files[0].get('frames',1),'processed_frame':0})


def execute(request):
    c=Context(request);c.progress(2,'准备处理')
    if os.name=='posix':
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_FSIZE,(request['max_file_bytes'],request['max_file_bytes']))
        if sys.platform.startswith('linux'):
            # Bound resident allocations without sharing another task's process state.
            limit=int(os.getenv('MEDIAFORGE_WORKER_MEMORY',str(3*1024**3)))
            resource.setrlimit(resource.RLIMIT_AS,(limit,limit))
    if c.op=='export-results':
        import zipfile
        out=c.work/'results.zip'
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
            for i,f in enumerate(c.files):
                archive.write(f['path'],f'{i+1:04}_'+f['name'])
                c.progress(5+(i+1)/len(c.files)*85,'打包结果')
        with zipfile.ZipFile(out) as archive:
            if archive.testzip():raise ForgeError('zip_verification','打包校验失败。')
        c.out(out,verification={'files':len(c.files),'crc_checked':True})
    elif c.op.startswith(('video-','audio-','media-')):media(c)
    elif c.op.startswith('subtitle-'):subtitles(c)
    elif c.op=='asr':asr(c)
    elif c.op.startswith('pdf-'):pdf(c)
    elif c.op in {'office-convert','word-replace'}:office(c)
    elif c.op.startswith('image-') or c.op=='watermark':image(c)
    else:raise ForgeError('unknown_operation','工具尚未实现。','刷新工具列表。')
    c.progress(97,'核验输出内容')
    return {'ok':True,'outputs':c.outputs}


def main():
    request=json.loads(Path(sys.argv[1]).read_text());work=Path(request['work'])
    try:result=execute(request)
    except BaseException as e:result={'ok':False,'error':safe_error(e)}
    target=work/'result.json';target.write_text(json.dumps(result,ensure_ascii=False));target.chmod(0o600)

if __name__=='__main__':main()
