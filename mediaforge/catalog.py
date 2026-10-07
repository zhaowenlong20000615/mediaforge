"""The same operation schema drives UI forms, API validation, CLI and MCP."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from .errors import ForgeError


def field(kind, title, default=None, **kw):
    result = {'type': kind, 'title': title, **kw}
    if default is not None:
        result['default'] = default
    return result


def choice(title, values, default):
    return field('string', title, default, enum=values)


FORMAT_IMAGE = choice('输出格式', ['png', 'jpeg', 'webp', 'tiff', 'bmp'], 'png')
QUALITY = field('integer', '画质（1–100）', 92, minimum=1, maximum=100)
LANG = field('string', 'OCR 语言（如 eng、chi_sim）', 'chi_sim+eng', pattern=r'^[A-Za-z_+]{2,50}$')
PASSWORD = field('string', 'PDF 打开密码（可选）', '', maxLength=200, format='password', sensitive=True)
RIGHTS = field('boolean', '我拥有素材编辑权', False, const=True)
PAGES = field('string', '页码（留空为全部，如 1-3,5）', '', maxLength=200, pattern=r'^[0-9,\- ]*$')


def op(id, name, category, formats, deps, desc, params=None, *, combine=False, min_files=1,
       max_files=100, note='', required=None):
    return {'id': id, 'name': name, 'category': category, 'accept': formats,
            'dependencies': deps, 'description': desc, 'note': note, 'combine': combine,
            'min_files': min_files, 'max_files': max_files,
            'schema': {'type': 'object', 'properties': params or {}, 'additionalProperties': False,
                       'required': required or []}}


MEDIA = ['video', 'audio']
OPS = [
    op('export-results','结果打包','批量',['image','video','audio','pdf','docx','doc','text','subtitle','zip'],[],'将已完成的结果打包为 ZIP。',{},combine=True,max_files=500),
    op('video-transcode', '视频转码', '视频 / 音频', ['video'], ['ffmpeg'], '转换视频格式与分辨率。', {
        'format': choice('输出格式', ['mp4','mkv','webm'], 'mp4'),
        'width': field('integer','输出宽度（0 保持原尺寸）',0,minimum=0,maximum=7680,anyOf=[{'const':0},{'minimum':2}]),
        'crf': field('integer','压缩强度（越大体积越小）',18,minimum=16,maximum=40)}),
    op('audio-extract','提取 / 转换音频','视频 / 音频',MEDIA,['ffmpeg'], '导出指定音轨，或转换音频格式。', {
        'format': choice('输出格式',['mp3','wav','flac','m4a','ogg'],'mp3'),
        'track':field('integer','音轨序号（从 0 开始）',0,minimum=0,maximum=31)}),
    op('media-trim','裁剪音视频','视频 / 音频',MEDIA,['ffmpeg'],'按开始时间和时长裁剪。', {
        'start':field('number','开始时间（秒）',0,minimum=0),
        'duration':field('number','保留时长（秒）',10,exclusiveMinimum=0,maximum=86400)}, required=['duration']),
    op('media-merge','合并音视频','视频 / 音频',MEDIA,['ffmpeg'],'按列表顺序合并，优先保留原始画面质量。',
       {'kind':choice('合并类型',['video','audio'],'video')}, combine=True,min_files=2,max_files=30,
       note='默认沿用第一段视频的分辨率与帧率；相容视频直接拼接，其他视频高质量重编码；缺音轨补静音。'),
    op('media-compress','压缩音视频','视频 / 音频',MEDIA,['ffmpeg'],'重编码减少体积，可预览后比较大小。',{
        'crf':field('integer','视频压缩强度',23,minimum=16,maximum=40),
        'audio_kbps':field('integer','音频码率 kbps',192,minimum=32,maximum=320)}, note='已经高度压缩的源文件不保证进一步变小。'),
    op('video-frames','视频抽帧','视频 / 音频',['video'],['ffmpeg'],'定间隔提取 PNG 帧。',{
        'interval':field('number','抽帧间隔（秒）',5,minimum=.1,maximum=86400),
        'count':field('integer','最多帧数',20,minimum=1,maximum=200)}),
    op('audio-normalize','音量标准化','视频 / 音频',MEDIA,['ffmpeg'],'统一感知响度，输出 WAV。',{
        'lufs':field('number','目标响度 LUFS',-16,minimum=-30,maximum=-9)}),
    op('audio-denoise','音频降噪','视频 / 音频',MEDIA,['ffmpeg'],'使用 FFmpeg 频谱降噪，输出 WAV。',{
        'strength':field('number','降噪强度 dB',8,minimum=1,maximum=40)},note='适合稳定底噪；不等同于人声与音乐分离。'),
    op('subtitle-convert','字幕格式转换','字幕 / 语音',['subtitle'],['pysubs2'],'SRT、VTT、ASS 字幕互转。',{
        'format':choice('输出格式',['srt','vtt','ass'],'srt')},note='转为 SRT/VTT 时会丢失 ASS 的样式效果。'),
    op('subtitle-extract','提取内嵌字幕','字幕 / 语音',['video'],['ffmpeg'],'导出视频中的文本字幕轨。',{
        'track':field('integer','字幕轨序号（从 0 开始）',0,minimum=0,maximum=31),
        'format':choice('输出格式',['srt','vtt','ass'],'srt')},note='图片字幕需 OCR；不支持的轨道会明确报错。'),
    op('asr','语音转文字与字幕','字幕 / 语音',MEDIA,['asr-model'],'本机或服务器离线模型转写，生成文本、SRT 与 VTT。',{
        'language':field('string','语言（留空自动识别，如 zh、en）','',pattern=r'^[a-z]{0,3}$'),
        'device':choice('计算设备',['cpu','cuda'],'cpu'),
        'max_line_chars':field('integer','字幕行宽（中文约占两格）',28,minimum=12,maximum=60)},note='每条字幕最多两行、六秒；模型需要管理员预先配置，不在任务执行中自动下载。'),
    op('pdf-split','PDF 拆分','PDF / Word',['pdf'],['pypdf'],'选择页码，每页保存为独立 PDF。',{'pages':PAGES,'password':PASSWORD}),
    op('pdf-merge','PDF 合并','PDF / Word',['pdf'],['pypdf'],'按文件顺序合并所有页面。',{'password':PASSWORD},combine=True,min_files=2),
    op('pdf-rotate','PDF 旋转','PDF / Word',['pdf'],['pypdf'],'旋转选定页面。',{'pages':PAGES,'angle':choice('旋转角度',['90','180','270'],'90'),'password':PASSWORD}),
    op('pdf-compress','PDF 无损压缩','PDF / Word',['pdf'],['pypdf'],'压缩内容流并复用重复对象。',{'password':PASSWORD},note='不降低图片分辨率；源文件已优化时体积可能不减。'),
    op('pdf-images','PDF 转图片','PDF / Word',['pdf'],['pypdf','poppler'],'将选定页面渲染成 PNG。',{'pages':PAGES,'dpi':field('integer','渲染 DPI',120,minimum=72,maximum=300),'password':PASSWORD}),
    op('pdf-text','PDF 提取文本','PDF / Word',['pdf'],['pypdf'],'按页提取可选中的文字。',{'pages':PAGES,'password':PASSWORD},note='扫描 PDF 没有文本层时，请使用 PDF OCR。'),
    op('pdf-word','PDF 转 Word','PDF / Word',['pdf'],['pypdf','docx','pdf2docx'],'转换为可编辑 Word，附实际排版的 PDF 预览。',{'password':PASSWORD,'mode':choice('转换方式',['layout','text'],'layout')},note='layout 保留图片与有框表格，并检查渲染后的文字与数字；text 仅提取文字。扫描件请先 OCR；多栏、公式及无框表格请核对预览。'),
    op('pdf-ocr','PDF OCR','PDF / Word',['pdf'],['pypdf','ocrmypdf','tesseract'],'保留已有文本与页面内容，为扫描页补 OCR 文字层。',{'pages':PAGES,'language':LANG,'password':PASSWORD}),
    op('pdf-tables','PDF 表格提取','PDF / Word',['pdf'],['pypdf','pdfplumber'],'提取可检测的表格为 CSV 和 JSON。',{'password':PASSWORD},note='扫描表格与跨页复杂布局可能无法可靠还原；请检查行列与合并单元格。'),
    op('office-convert','Word 转换','PDF / Word',['docx','doc'],['office-dynamic'],'Word 转 PDF、HTML、Markdown 或文本。',{
        'format':choice('输出格式',['pdf','html','md','txt'],'pdf')},note='旧版 .doc 及 PDF 导出需要 LibreOffice；HTML/Markdown 保留标题、列表、格式、表格与图片；它们采用语义排版，视觉版式需要 PDF。'),
    op('word-replace','Word 批量替换','PDF / Word',['docx'],['docx'],'替换段落、表格、页眉与页脚中的文字。',{
        'find':field('string','查找文本',minLength=1,maxLength=500),
        'replace':field('string','替换为','',maxLength=5000)},required=['find'],note='跨格式片段的匹配保留首片段格式；请检查复杂排版。'),
    op('image-process','图片转换与调整','图片',['image'],['pillow'],'格式转换、压缩和等比缩放。',{
        'format':FORMAT_IMAGE,'quality':QUALITY,
        'lossless':field('boolean','WebP 使用无损编码（其他格式忽略）',True),
        'width':field('integer','最大宽度（0 不限制）',0,minimum=0,maximum=16000),
        'height':field('integer','最大高度（0 不限制）',0,minimum=0,maximum=16000)},note='JPEG 不支持透明背景，会合成到白色。'),
    op('image-crop','图片裁剪','图片',['image'],['pillow'],'从左上角坐标开始裁剪指定区域。',{
        'x':field('integer','左边距',0,minimum=0),'y':field('integer','上边距',0,minimum=0),
        'width':field('integer','裁剪宽度',500,minimum=1,maximum=16000),
        'height':field('integer','裁剪高度',500,minimum=1,maximum=16000)}),
    op('image-ocr','图片 OCR','图片',['image'],['tesseract'],'识别图片文字，输出 TXT。',{'language':LANG}),
    op('image-pdf','图片合成 PDF','图片',['image'],['pillow','img2pdf'],'无损嵌入图片，按列表顺序合成多页 PDF。',{},combine=True),
    op('image-rename','图片批量重命名','图片',['image'],['pillow'],'以自定义前缀与序号导出副本，保留原文件。',{
        'prefix':field('string','文件名前缀','image',minLength=1,maxLength=60,pattern=r'^[^/\\\x00-\x1f]+$'),
        'start':field('integer','起始序号',1,minimum=0,maximum=999999)}),
    op('image-background','图片去背景','图片',['image'],['background-model'],'使用本地抠图模型输出透明 PNG。',{'refine_edges':field('boolean','精修半透明边缘',True)},note='需预先配置模型；头发、透明物体等细节需人工检查。'),
    op('image-repair','修复自有图片瑕疵','图片',['image'],['opencv'],'按第二张图片的白色遮罩修复第一张图片。',{
        'rights_confirmed':RIGHTS,'radius':field('integer','修复半径',3,minimum=1,maximum=20)},
        combine=True,min_files=2,max_files=2,required=['rights_confirmed'],note='仅用于有编辑权的自有图片；禁止处理 DRM、平台版权标识或保护措施。'),
    op('watermark','添加文字水印','图片',['image'],['pillow','font'],'给自有素材叠加可配置的文字。',{
        'text':field('string','水印文字',minLength=1,maxLength=120),
        'position':choice('位置',['bottom-right','bottom-left','top-right','top-left','center'],'bottom-right'),
        'opacity':field('integer','不透明度 %',65,minimum=1,maximum=100),
        'size':field('integer','文字尺寸 px',32,minimum=12,maximum=200),
        'rights_confirmed':RIGHTS},required=['text','rights_confirmed']),
]
CATALOG = {item['id']:item for item in OPS}


def validate(operation, params):
    if not isinstance(operation,str):raise ForgeError('invalid_tool','工具名称必须是文字。')
    if operation not in CATALOG:
        raise ForgeError('unknown_tool','没有这个处理工具。','刷新工具列表后重试。',404)
    if not isinstance(params,dict):
        raise ForgeError('invalid_parameters','参数必须是 JSON 对象。','按工具表单填写参数。')
    try:json.dumps(params,allow_nan=False)
    except (ValueError,TypeError):
        raise ForgeError('invalid_parameters','参数包含无效的数字或数据类型。','只使用有限数值和标准 JSON 值。')
    tool = CATALOG[operation]
    values = deepcopy(params)
    for key, spec in tool['schema']['properties'].items():
        if key not in values and 'default' in spec:
            values[key] = deepcopy(spec['default'])
    errors = list(Draft202012Validator(tool['schema']).iter_errors(values))
    if errors:
        path = str(next(iter(errors[0].path), '参数'))
        title = tool['schema']['properties'].get(path,{}).get('title',path)
        raise ForgeError('invalid_parameters',f'请检查“{title}”。','按工具表单填写必填项和允许的范围。')
    return tool, values
