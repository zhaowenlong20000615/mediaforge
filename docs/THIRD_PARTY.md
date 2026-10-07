# 本次复用的成熟组件

- [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF)：17.13.0，MPL-2.0；通过公开Python API补文字层，使用pypdfium渲染、Tesseract识别。没有修改上游代码。已有文本页使用skip模式，输出仍检查页数与可提取文字。
- [filetype.py](https://github.com/h2non/filetype.py)：1.2.0，MIT；根据文件签名识别媒体MIME，然后使用FFprobe进一步核对轨道/时长。扩展名不再决定媒体预览类型。
- [Playwright](https://github.com/microsoft/playwright)：开发测试依赖，浏览器实测上传、任务、预览、下载、断网和响应竞态。
- [axe-core](https://github.com/dequelabs/axe-core)：开发测试依赖，检查页面的WCAG A/AA规则。自动化检查不替代所有辅助技术或人工可用性测试。

Python依赖版本与校验值在uv.lock，浏览器测试依赖在package-lock.json。实际发布包包含依赖wheel自身的许可证与元数据；模型与用户内容不进入源码包。其他处理能力继续复用FFmpeg、pypdf、LibreOffice、Pillow、pysubs2、faster-whisper、rembg、OpenCV。
