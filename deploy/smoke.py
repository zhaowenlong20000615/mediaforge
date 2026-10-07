"""Run real synthetic-file workflows through the deployed authenticated API.

No private user input is used. A separate workspace is created for evidence and
its files/tasks are cleaned after verification. Tokens are never written to reports.
"""
import argparse
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime,timezone
import httpx
from mediaforge.dependencies import verified_binary
from PIL import Image,ImageDraw,ImageFont
from pypdf import PdfReader
from docx import Document
from reportlab.pdfgen import canvas
from mediaforge.client import Client


def main():
    p=argparse.ArgumentParser();p.add_argument('--server',required=True);p.add_argument('--token-file',required=True);p.add_argument('--speech');p.add_argument('--report',required=True);a=p.parse_args()
    report={'tested_at':datetime.now(timezone.utc).isoformat(),'server':a.server,'fixture':'Synthetic files generated locally and processed over real HTTPS; no user documents','operations':[]}
    root=Client(a.server,a.token_file)
    with tempfile.TemporaryDirectory(prefix='mediaforge-live-smoke-') as folder:
        folder=Path(folder)
        account=root.request('POST','api/workspaces',json={'name':'release-smoke-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M')})
        token=folder/'access.token';token.write_text(account['token']);token.chmod(0o600)
        client=Client(a.server,str(token));report['workspace']=account['owner']
        try:
            with httpx.Client(timeout=15,trust_env=False) as anon:
                report['unauthorized_status']=anon.get(a.server.rstrip('/')+'/api/tasks').status_code
                assert report['unauthorized_status']==401
                report['version']=anon.get(a.server.rstrip('/')+'/version').json()
            report['diagnostics']=client.request('GET','api/doctor')
            assert not [x for x in report['diagnostics']['checks'] if not x['available']]
            img=Image.new('RGB',(800,600),'white');draw=ImageDraw.Draw(img);draw.ellipse((150,100,650,530),fill='#337a9b');img.save(folder/'image.png')
            mask=Image.new('L',img.size,0);ImageDraw.Draw(mask).rectangle((300,300,330,320),fill=255);mask.save(folder/'mask.png')
            text_img=Image.new('RGB',(1000,250),'white');font=ImageFont.load_default(size=55);ImageDraw.Draw(text_img).text((30,65),'MEDIAFORGE TEST 12345',font=font,fill='black');text_img.save(folder/'text.png')
            c=canvas.Canvas(str(folder/'pages.pdf'))
            for page in range(3):
                c.drawString(50,750,'MEDIAFORGE TEST PAGE '+str(page+1))
                if page==0:
                    for x in [50,190,330]:c.line(x,580,x,680)
                    for y in [580,630,680]:c.line(50,y,330,y)
                    c.drawString(60,650,'Name');c.drawString(200,650,'Count');c.drawString(60,600,'Apple');c.drawString(200,600,'42')
                c.showPage()
            c.save()
            doc=Document();doc.add_paragraph('Hello MediaForge World');doc.add_table(rows=1,cols=2).cell(0,0).text='Table text';doc.save(folder/'word.docx')
            (folder/'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nMEDIAFORGE TEST\n\n2\n00:00:01,000 --> 00:00:02,000\nSECOND LINE\n')
            ffmpeg=verified_binary('ffmpeg')
            if not ffmpeg:raise SystemExit('A working ffmpeg is required to generate synthetic smoke fixtures')
            def ff(args):subprocess.run([ffmpeg,'-y','-v','error',*map(str,args)],check=True,capture_output=True,timeout=30)
            ff(['-f','lavfi','-i','sine=frequency=440:duration=2',folder/'sound.wav'])
            ff(['-f','lavfi','-i','color=c=blue:s=320x240:d=2','-i',folder/'sound.wav','-c:v','libx264','-c:a','aac',folder/'video.mp4'])
            ff(['-i',folder/'video.mp4','-i',folder/'sound.wav','-i',folder/'captions.srt','-map','0:v','-map','0:a','-map','1:a','-map','2:s','-c:v','copy','-c:a','aac','-c:s','mov_text',folder/'tracks.mp4'])
            ids={}
            for name in ['image.png','mask.png','text.png','pages.pdf','word.docx','captions.srt','sound.wav','video.mp4','tracks.mp4']:
                ids[name]=client.upload(folder/name)['id']
            if a.speech:ids['speech']=client.upload(a.speech)['id']
            cases=[
                ('image-process',['image.png'],{'width':160,'format':'webp'}),('image-crop',['image.png'],{'width':80,'height':90}),
                ('image-rename',['image.png'],{'prefix':'测试图片'}),('watermark',['image.png'],{'text':'我的素材','rights_confirmed':True,'size':25}),
                ('image-pdf',['image.png','text.png'],{}),('image-ocr',['text.png'],{'language':'eng'}),('image-background',['image.png'],{}),
                ('image-repair',['image.png','mask.png'],{'rights_confirmed':True}),('pdf-split',['pages.pdf'],{'pages':'1,3'}),
                ('pdf-merge',['pages.pdf','pages.pdf'],{}),('pdf-rotate',['pages.pdf'],{'pages':'2','angle':'90'}),('pdf-compress',['pages.pdf'],{}),
                ('pdf-images',['pages.pdf'],{'pages':'1','dpi':72}),('pdf-text',['pages.pdf'],{}),('pdf-word',['pages.pdf'],{}),
                ('pdf-tables',['pages.pdf'],{}),('pdf-ocr',['pages.pdf'],{'pages':'1','language':'eng'}),
                ('office-convert',['word.docx'],{'format':'pdf'}),('word-replace',['word.docx'],{'find':'World','replace':'Verified'}),
                ('video-transcode',['video.mp4'],{'width':160,'format':'mp4'}),('audio-extract',['tracks.mp4'],{'format':'flac','track':1}),
                ('media-trim',['video.mp4'],{'start':.5,'duration':.7}),('media-merge',['video.mp4','tracks.mp4'],{'kind':'video'}),
                ('media-compress',['video.mp4'],{}),('video-frames',['video.mp4'],{'count':2,'interval':1}),('audio-normalize',['sound.wav'],{}),
                ('audio-denoise',['sound.wav'],{}),('subtitle-convert',['captions.srt'],{'format':'vtt'}),('subtitle-extract',['tracks.mp4'],{})]
            if a.speech:cases.append(('asr',['speech'],{'language':'en','device':'cpu'}))
            tasks=[]
            for index,(op,names,params) in enumerate(cases):
                inputs=[]
                for name in names:
                    value=ids[name]
                    if value in inputs:value=client.upload(folder/name)['id']
                    inputs.append(value)
                task=client.request('POST','api/tasks',json={'tool':op,'file_ids':inputs,'params':params,'group':'release-smoke','idempotency_key':'smoke-'+str(index)})
                tasks.append((op,task['id'],params))
            for op,tid,params in tasks:
                t=client.wait(tid,300)
                evidence={'operation':op,'id':tid,'status':t['status'],'error':t['error'],'outputs':[]}
                for i,out in enumerate(t['outputs']):
                    dest=folder/(tid+str(i)+Path(out['name']).suffix)
                    client.download(out['id'],dest)
                    assert hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()==out['sha256']
                    evidence['outputs'].append({k:out.get(k) for k in ['name','size','sha256','kind','width','height','pages','duration','verification']})
                    if op=='image-process':assert out['width']==160
                    if op=='pdf-rotate':assert [x.get('/Rotate',0) for x in PdfReader(dest).pages]==[0,90,0]
                    if op=='pdf-merge':assert out['pages']==6
                    if op=='image-ocr':assert 'MEDIAFORGE' in dest.read_text().upper()
                    if op=='asr':assert 'hello' in dest.read_text().lower()
                    if op=='word-replace':assert 'Verified' in Document(dest).paragraphs[0].text
                report['operations'].append(evidence)
                print(op,t['status'],flush=True)
            finished=[x['id'] for x in report['operations'] if x['status']=='succeeded']
            if finished:
                export=client.request('POST','api/exports',json={'task_ids':finished[:3],'idempotency_key':'smoke-export'})
                t=client.wait(export['id'],60);report['operations'].append({'operation':'export-results','id':t['id'],'status':t['status'],'error':t['error'],'outputs':t['outputs']})
                print('export-results',t['status'],flush=True)
            report['passed']=all(x['status']=='succeeded' and x['outputs'] for x in report['operations']) and len(report['operations'])==31
        finally:
            try:report['cleanup']=client.request('POST','api/cleanup',json={'days':0,'dry_run':False})
            except Exception:report['cleanup']={'failed':True}
            Path(a.report).parent.mkdir(parents=True,exist_ok=True)
            Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if not report.get('passed'):raise SystemExit(1)

if __name__=='__main__':main()
