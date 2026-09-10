# 外部工具与本地模型

外部处理器使用FFmpeg、Poppler、Tesseract与LibreOffice；Python依赖通过uv.lock固定。缺少依赖时任务返回dependency_missing；诊断区给出平台对应的安装说明。OCR语言只接受已安装的Tesseract语言包。

Faster Whisper：安装 `uv sync --extra asr`；从官方维护的 [Systran/faster-whisper-tiny](https://huggingface.co/Systran/faster-whisper-tiny) 下载CTranslate2模型文件，设 `MEDIAFORGE_ASR_MODEL` 指向包含model.bin、config.json、tokenizer.json和词表的目录。验收使用tiny与CPU/int8；准确性受语言、口音、噪声和模型规模影响。CUDA要有匹配驱动与库，未在当前无GPU服务器验证。运行任务采用local_files_only，不自动下载。

去背景：安装 `uv sync --extra background`；将 [rembg官方发布的u2net.onnx](https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx) 放在 `U2NET_HOME`。本次模型175,997,641字节，官方包配置的MD5为60024c5c889badc19c04ad937298a77b。部署前另记录SHA-256；模型由本机上传独立模型目录，不混入源码或用户文件。使用CPU provider。

图像修复：`uv sync --extra repair` 安装OpenCV。第二张输入是与原图同尺寸的黑白遮罩，白色区域用于修复；必须明确拥有编辑权。

中文水印字体：服务器安装Noto CJK，本机优先PingFang/STHeiti，也可设 `MEDIAFORGE_FONT`。缺字体不会静默跳过水印。

所有模型输出都需要人工复核。模型预配置仅表示可以运行，并不表示所有真实素材质量达到交付要求。
