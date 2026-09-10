import json
import os
from pathlib import Path
import shutil
import time
import zipfile
import pytest
from pypdf import PdfReader
from PIL import Image
from docx import Document
import pysubs2
from mediaforge.store import Store
from mediaforge.engine import Engine
from mediaforge.errors import ForgeError
from mediaforge.dependencies import binary,checks
from mediaforge.files import probe

OWNER='workspace_default'


def wait(store,tid,seconds=35):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        t=store.task(OWNER,tid)
        if t['status'] in {'succeeded','failed','partial','cancelled','recoverable'}:return t
        time.sleep(.05)
    raise AssertionError('Task timeout')


def job(store,op,paths,params=None,**kw):
    ids=[store.import_file(OWNER,p)['id'] for p in paths]
    t=store.submit(OWNER,op,ids,params or {},**kw)
    return wait(store,t['id'],120 if op in {'office-convert','image-background','asr'} else 35)


def output_path(store,result,index=0):return Path(store.file(OWNER,result['outputs'][index]['id'],True)['path'])


def test_reject_fake_types_and_empty(store,samples):
    f=store.import_file(OWNER,samples/'plain.txt')
    for tool in ['image-process','asr','pdf-rotate']:
        with pytest.raises(ForgeError,match='类型'):store.submit(OWNER,tool,[f['id']],{})
    with pytest.raises(ForgeError):store.submit(OWNER,'image-process',[],{})
    with pytest.raises(ForgeError):store.import_file(OWNER,samples/'broken.pdf')


def test_isolated_stores_and_idempotency(store,samples):
    f=store.import_file(OWNER,samples/'图片 sample.png')
    first=store.submit(OWNER,'image-process',[f['id']],{},'same')
    reader=Store(store.settings)
    assert reader.task(OWNER,first['id'])['status']=='accepted'
    second=reader.submit(OWNER,'image-process',[f['id']],{'width':100})
    assert store.tasks(OWNER)['total']==2
    assert reader.submit(OWNER,'image-process',[f['id']],{},'same')['id']==first['id']
    with pytest.raises(ForgeError) as e:reader.submit(OWNER,'image-process',[f['id']],{'width':22},'same')
    assert e.value.code=='idempotency_conflict'
    with pytest.raises(ForgeError):store.task('another-workspace',first['id'])
    assert second['id']!=first['id']


@pytest.mark.parametrize('op,params',[
 ('image-process',{'width':160,'format':'jpeg'}),('image-crop',{'x':10,'y':10,'width':40,'height':50}),
 ('watermark',{'text':'我的素材','rights_confirmed':True,'size':24}),('image-rename',{'prefix':'测试'})])
def test_images(running,samples,op,params):
    store,_=running;t=job(store,op,[samples/'图片 sample.png'],params)
    assert t['status']=='succeeded',t['error']
    with Image.open(output_path(store,t)) as im:
        if op=='image-process':assert im.size==(160,120) and im.format=='JPEG'
        if op=='image-crop':assert im.size==(40,50)
    if op=='watermark':assert t['outputs'][0]['sha256']!=t['inputs'][0]['sha256']


def test_pdf_merge_split_rotate(running,samples):
    s,_=running
    t=job(s,'pdf-split',[samples/'document.pdf'],{'pages':'1,3'});assert t['status']=='succeeded',t['error'];assert len(t['outputs'])==2
    assert all(o['pages']==1 for o in t['outputs'])
    t=job(s,'pdf-merge',[samples/'document.pdf',samples/'document.pdf']);assert t['status']=='succeeded',t['error'];assert t['outputs'][0]['pages']==6
    t=job(s,'pdf-rotate',[samples/'document.pdf'],{'pages':'2','angle':'90'});assert t['status']=='succeeded',t['error']
    reader=PdfReader(output_path(s,t));assert [p.get('/Rotate',0) for p in reader.pages]==[0,90,0]


@pytest.mark.parametrize('op',['pdf-compress','pdf-text','pdf-word','pdf-tables','pdf-images'])
def test_pdf_outputs(running,samples,op):
    if op=='pdf-images' and not binary('poppler'):pytest.skip('Poppler not installed')
    s,_=running;t=job(s,op,[samples/'document.pdf']);assert t['status']=='succeeded',t['error']
    if op=='pdf-text':assert 'MEDIAFORGE TEST PAGE 3' in output_path(s,t).read_text()
    if op=='pdf-word':assert any('MEDIAFORGE TEST PAGE' in p.text for p in Document(output_path(s,t)).paragraphs)
    if op=='pdf-tables':assert 'Apple' in output_path(s,t).read_text(encoding='utf-8-sig')
    if op=='pdf-images':assert len(t['outputs'])==3 and all(f['kind']=='image' for f in t['outputs'])


def test_password_and_secret_storage(running,samples):
    s,_=running
    t=job(s,'pdf-text',[samples/'protected.pdf']);assert t['status']=='failed' and t['error']['code']=='password_required'
    t=job(s,'pdf-text',[samples/'protected.pdf'],{'password':'bad'});assert t['status']=='failed' and t['error']['code']=='wrong_password'
    t=job(s,'pdf-text',[samples/'protected.pdf'],{'password':'audit-password'});assert t['status']=='succeeded',t['error']
    assert 'password' not in t['params']
    assert b'audit-password' not in s.db_path.read_bytes()


@pytest.mark.parametrize('fmt',['srt','vtt','ass'])
def test_subtitle_conversion(running,samples,fmt):
    s,_=running;t=job(s,'subtitle-convert',[samples/'subtitle.srt'],{'format':fmt});assert t['status']=='succeeded',t['error']
    subs=pysubs2.load(str(output_path(s,t)));assert len(subs)==2 and subs[1].start==1000
    if fmt=='vtt':assert output_path(s,t).read_text().startswith('WEBVTT')


@pytest.mark.parametrize('fmt',['txt','html','md','pdf'])
def test_word_convert(running,samples,fmt):
    if fmt=='pdf' and not binary('libreoffice'):pytest.skip('LibreOffice missing')
    s,_=running;t=job(s,'office-convert',[samples/'input.docx'],{'format':fmt});assert t['status']=='succeeded',t['error']
    if fmt!='pdf':assert 'World' in output_path(s,t).read_text()
    else:assert len(PdfReader(output_path(s,t)).pages)>=1


def test_word_replace(running,samples):
    s,_=running;t=job(s,'word-replace',[samples/'input.docx'],{'find':'World','replace':'Earth'});assert t['status']=='succeeded',t['error']
    doc=Document(output_path(s,t));assert 'Earth' in doc.paragraphs[0].text
    assert doc.tables[0].cell(1,0).text=='Earth';assert 'Earth' in doc.sections[0].header.paragraphs[0].text


@pytest.mark.parametrize('op,params,input_file',[
 ('audio-extract',{'format':'flac','track':1},'tracks.mp4'),('audio-extract',{'format':'wav'},'audio.wav'),
 ('audio-normalize',{},'audio.wav'),('audio-denoise',{},'audio.wav'),('media-compress',{},'video.mp4'),
 ('video-transcode',{'format':'webm','width':160},'video.mp4'),('media-trim',{'start':.5,'duration':.7},'video.mp4'),
 ('video-frames',{'interval':.5,'count':3},'video.mp4'),('subtitle-extract',{},'tracks.mp4')])
def test_media(running,samples,op,params,input_file):
    if not (samples/input_file).exists():pytest.skip('FFmpeg missing')
    s,_=running;t=job(s,op,[samples/input_file],params);assert t['status']=='succeeded',t['error']
    if op=='audio-extract':assert probe(output_path(s,t))['streams'][0]['codec_name']==('flac' if params['format']=='flac' else 'pcm_s16le')
    if op=='media-trim':assert abs(t['outputs'][0]['duration']-.7)<.25
    if op=='video-frames':assert len(t['outputs'])==3
    if op=='subtitle-extract':assert len(pysubs2.load(str(output_path(s,t))))==2


@pytest.mark.parametrize('kind',['audio','video'])
def test_merge(running,samples,kind):
    if not (samples/'video.mp4').exists():pytest.skip('FFmpeg missing')
    s,_=running;files=[samples/'video.mp4',samples/('silent.mp4' if kind=='video' else 'audio.wav')]
    t=job(s,'media-merge',files,{'kind':kind});assert t['status']=='succeeded',t['error']
    assert t['outputs'][0]['duration']>2.8


def test_no_audio_subtitles_and_missing_models(running,samples,monkeypatch):
    s,_=running
    for op in ['audio-extract','subtitle-extract']:
        t=job(s,op,[samples/'silent.mp4']);assert t['status']=='failed';assert t['error']['code'] in {'no_audio','no_subtitle'}
    monkeypatch.setenv('MEDIAFORGE_ASR_MODEL','/not-configured')
    t=job(s,'asr',[samples/'audio.wav']);assert t['status']=='failed' and t['error']['code']=='dependency_missing';assert not t['outputs']


def test_same_name_partial_resume_export(running,samples):
    s,_=running
    f1=s.import_file(OWNER,samples/'图片 sample.png',name='相同 名字.png');f2=s.import_file(OWNER,samples/'mask.png',name='相同 名字.png')
    t=s.submit(OWNER,'image-process',[f1['id'],f2['id']],{'width':80});t=wait(s,t['id']);assert t['status']=='succeeded',t['error']
    assert len({x['id'] for x in t['outputs']})==2
    export=s.submit(OWNER,'export-results',t['output_ids']);export=wait(s,export['id']);assert export['status']=='succeeded',export['error']
    with zipfile.ZipFile(output_path(s,export)) as z:assert len(set(z.namelist()))==2 and z.testzip() is None
    # A valid two-page-range request works on three pages and fails on one page.
    one=job(s,'pdf-split',[samples/'document.pdf'],{'pages':'1'})['output_ids'][0]
    allpdf=s.import_file(OWNER,samples/'document.pdf')['id']
    partial=wait(s,s.submit(OWNER,'pdf-split',[allpdf,one],{'pages':'2'})['id'])
    assert partial['status']=='partial' and len(partial['outputs'])==1
    kept=partial['output_ids'];attempt=partial['items'][0]['attempt']
    partial=wait(s,s.resume(OWNER,partial['id'])['id'])
    assert partial['output_ids']==kept and partial['items'][0]['attempt']==attempt


def test_cancel_and_restart(store,samples):
    f=store.import_file(OWNER,samples/'图片 sample.png')
    t=store.submit(OWNER,'image-process',[f['id']],{})
    assert store.cancel(OWNER,t['id'])['status']=='cancelled'
    e=Engine(store);e.start();time.sleep(.3);assert store.task(OWNER,t['id'])['status']=='cancelled'
    t=store.resume(OWNER,t['id']);assert wait(store,t['id'])['status']=='succeeded'
    # A longer merge gives the worker a cancellable independent process group.
    ids=[store.import_file(OWNER,samples/'video.mp4')['id'] for _ in range(10)]
    t=store.submit(OWNER,'media-merge',ids,{'kind':'video'})
    deadline=time.monotonic()+8
    while store.task(OWNER,t['id'])['status']!='running' and time.monotonic()<deadline:time.sleep(.02)
    store.cancel(OWNER,t['id']);assert wait(store,t['id'])['status']=='cancelled';time.sleep(.2);assert store.task(OWNER,t['id'])['status']=='cancelled'
    e.stop()
    # Simulate interrupted persistent state; a query must not alter it.
    with store.tx() as con:
        con.execute("UPDATE tasks SET status='running',cancel=0 WHERE id=?",(t['id'],))
        con.execute("UPDATE items SET status='running' WHERE task_id=?",(t['id'],))
    reader=Store(store.settings);assert reader.task(OWNER,t['id'])['status']=='running'
    recovered=Engine(store);recovered.start();assert store.task(OWNER,t['id'])['status']=='recoverable';recovered.stop()


def test_image_pdf_and_repair(running,samples):
    s,_=running;t=job(s,'image-pdf',[samples/'图片 sample.png',samples/'mask.png']);assert t['status']=='succeeded' and t['outputs'][0]['pages']==2
    if next(x for x in checks() if x['id']=='opencv')['available']:
        t=job(s,'image-repair',[samples/'图片 sample.png',samples/'mask.png'],{'rights_confirmed':True});assert t['status']=='succeeded',t['error']


def test_worker_exclusion_and_timeout_retry(store,samples):
    engine=Engine(store);engine.start()
    second=Engine(store)
    with pytest.raises(RuntimeError,match='already owns'):second.start()
    second.pool.shutdown()
    # An intentionally tiny execution deadline produces a bounded failure, not a false success.
    ids=[store.import_file(OWNER,samples/'video.mp4')['id'] for _ in range(20)]
    t=store.submit(OWNER,'media-merge',ids,{'kind':'video'},timeout=1,retries=1)
    result=wait(store,t['id'],15)
    assert result['status']=='failed' and result['error']['code']=='timeout'
    assert result['items'][0]['attempt']==2
    engine.stop()


def test_reuploaded_identical_content_uses_same_idempotent_task(store,samples):
    a=store.import_file(OWNER,samples/'图片 sample.png');b=store.import_file(OWNER,samples/'图片 sample.png')
    first=store.submit(OWNER,'image-process',[a['id']],{},'content-key')
    repeated=store.submit(OWNER,'image-process',[b['id']],{},'content-key')
    assert first['id']==repeated['id']
