import os
from pathlib import Path
import subprocess
import pytest
from PIL import Image,ImageDraw,ImageFont
from mediaforge.dependencies import checks,binary,ocr_languages,font_path
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


def test_chinese_ocr_retains_spaced_lines_and_amounts(running,tmp_path):
    import img2pdf
    if not {'chi_sim','eng'}<=set(ocr_languages()):pytest.skip('Chinese and English OCR language packs not configured')
    font=font_path()
    if not font:pytest.skip('Chinese OCR fixture font not available')
    source=tmp_path/'chinese.png';image=Image.new('RGB',(1024,768),'white')
    draw=ImageDraw.Draw(image);font=ImageFont.truetype(font,38)
    lines=['媒体工具箱质量验收','合同编号：MF-2026-1007','应付金额：1,280.50 元','交付要求：画面清晰，文字完整。','Word / PDF / OCR - Quality 12345']
    for i,line in enumerate(lines):draw.text((45,55+i*105),line,font=font,fill='#172b45')
    image.save(source)
    pdf=tmp_path/'chinese.pdf';pdf.write_bytes(img2pdf.convert(str(source)))
    store,_=running
    for operation,path in [('image-ocr',source),('pdf-ocr',pdf)]:
        t=job(store,operation,[path]);assert t['status']=='succeeded',t['error']
        text=''.join(output_path(store,t).read_text().split())
        assert all(value in text for value in ['媒体工具箱质量验收','合同编号','MF-2026-1007','应付金额','1,280.50','交付要求','画面清晰','文字完整','12345']),text
        if operation=='pdf-ocr':
            import pymupdf
            with pymupdf.open(output_path(store,t,1)) as pdf:
                searchable=''.join(pdf[0].get_text().split())
                assert '交付要求' in searchable and '1,280.50' in searchable
                assert pdf[0].search_for('交付要求')


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
