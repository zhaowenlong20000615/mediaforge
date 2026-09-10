import os
from pathlib import Path
import subprocess
import pytest
from PIL import Image,ImageDraw,ImageFont
from mediaforge.dependencies import checks,binary
from .test_core import job,output_path


def test_ocr_actual_text(running,tmp_path):
    if not binary('tesseract'):pytest.skip('Tesseract missing')
    path=tmp_path/'ocr.png';image=Image.new('RGB',(1000,250),'white')
    font=None
    for candidate in ['/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if Path(candidate).exists():font=ImageFont.truetype(candidate,56);break
    if font is None:font=ImageFont.load_default(size=56)
    ImageDraw.Draw(image).text((30,60),'MEDIAFORGE 12345',font=font,fill='black');image.save(path)
    s,_=running;t=job(s,'image-ocr',[path],{'language':'eng'});assert t['status']=='succeeded',t['error']
    assert 'MEDIAFORGE' in output_path(s,t).read_text().upper()
    pdf=tmp_path/'scanned.pdf';image.save(pdf,'PDF')
    if binary('poppler'):
        t=job(s,'pdf-ocr',[pdf],{'language':'eng'});assert t['status']=='succeeded',t['error'];assert len(t['outputs'])==2
        assert '12345' in output_path(s,t).read_text()


def test_asr_local_model(running):
    fixture=os.getenv('MEDIAFORGE_SPEECH_FIXTURE')
    if not fixture or not next(c for c in checks() if c['id']=='asr-model')['available']:pytest.skip('Explicit local ASR model and synthetic speech fixture not configured')
    s,_=running;t=job(s,'asr',[Path(fixture)],{'language':'en','device':'cpu'})
    assert t['status']=='succeeded',t['error'];assert len(t['outputs'])==3
    text=' '.join(output_path(s,t,i).read_text().lower() for i in range(3))
    assert 'hello' in text and 'test' in text


def test_background_model(running,samples):
    if not next(c for c in checks() if c['id']=='background-model')['available']:pytest.skip('Explicit background model not configured')
    s,_=running;t=job(s,'image-background',[samples/'图片 sample.png'])
    assert t['status']=='succeeded',t['error']
    with Image.open(output_path(s,t)) as im:
        assert im.mode=='RGBA' and im.getchannel('A').getextrema()[0]<255
