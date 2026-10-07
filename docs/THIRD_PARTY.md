# 本次复用的成熟组件

- [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF)：17.13.0，MPL-2.0；通过公开Python API补文字层，使用pypdfium渲染、Tesseract识别。没有修改上游代码。已有文本页使用skip模式，输出仍检查页数与可提取文字。
- [filetype.py](https://github.com/h2non/filetype.py)：1.2.0，MIT；根据文件签名识别媒体MIME，然后使用FFprobe进一步核对轨道/时长。扩展名不再决定媒体预览类型。
- [Playwright](https://github.com/microsoft/playwright)：开发测试依赖，浏览器实测上传、任务、预览、下载、断网和响应竞态。
- [axe-core](https://github.com/dequelabs/axe-core)：开发测试依赖，检查页面的WCAG A/AA规则。自动化检查不替代所有辅助技术或人工可用性测试。

Python依赖版本与校验值在uv.lock，浏览器测试依赖在package-lock.json。实际发布包包含依赖wheel自身的许可证与元数据；模型与用户内容不进入源码包。其他处理能力继续复用FFmpeg、pypdf、LibreOffice、Pillow、pysubs2、faster-whisper、rembg、OpenCV。

## 0.2.3 产物保真组件

- [img2pdf](https://gitlab.mister-muffin.de/josch/img2pdf)：LGPL-3.0-or-later；直接嵌入JPEG/PNG等图像，避免Pillow重压缩。使用未修改的上游包。
- [Mammoth](https://github.com/mwilliamson/python-mammoth)：BSD-2-Clause；Word正文的标题、列表、表格、格式与图片。关闭外部文件访问和嵌入样式映射；图片转为安全PNG，再用[bleach](https://github.com/mozilla/bleach)（Apache-2.0）限制输出标签与链接。
- [markdownify](https://github.com/matthewwithanm/python-markdownify)：MIT；将已清理HTML转换为Markdown，复用列表/表格转换能力。
- [pdf2docx](https://github.com/ArtifexSoftware/pdf2docx)：固定0.5.13，MIT。上游说明Artifex已不再积极维护，仍可接收社区贡献；因此通过独立适配器集成、锁定版本并增加真实渲染验收，不将上游默认转换成功当作交付依据。关闭易把列表误判为表格的无框表格推断，有框表格仍可编辑。
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)：pdf2docx的依赖，AGPL-3.0或商业许可。发布包保留上游wheel的许可证和元数据；再分发/闭源集成须按适用许可处理，不能把它当作MIT组件。未修改该库。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)及[small模型](https://huggingface.co/Systran/faster-whisper-small)：沿用本地CTranslate2推理，CPU/int8。模型单独传输与校验，不打入源码包。

本轮质量样本中的NASA astronaut图像来自scikit-image自带公共领域样本；coffee图像由Rachel Michetti提供，CC0。其他文字、表格、测试视频与Mac系统语音由验收脚本生成，仅用于可重复测试。候选BiRefNet-general-lite模型来源rembg官方release；主体保留不佳，未作为本次部署依赖。
