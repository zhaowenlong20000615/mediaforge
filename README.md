# MediaForge 0.2.6

媒体与文档工作台：选择文件与工具、设置参数、观察任务、核对结果，再下载或继续处理。Web、CLI 和标准 MCP 使用同一个有认证的 API；服务端只接受工作区内的文件 ID。

## 本地运行

需要 Python 3.11+（验收使用 3.12）与 [uv](https://docs.astral.sh/uv/)。

```sh
uv sync --frozen --all-extras
.venv/bin/mediaforge serve
```

打开 `http://127.0.0.1:18081/`。第一次启动会在 `~/.mediaforge/admin.token` 创建权限为 0600 的访问令牌文件。将令牌粘贴到工作区登录页；不要将它提交到 Git 或发给不可信服务。文件存储在服务所在设备，远程部署时会上传到服务器。

```sh
# macOS 外部依赖（模型单独配置）
brew install ffmpeg poppler tesseract tesseract-lang libreoffice
# Ubuntu/Debian
sudo apt-get install ffmpeg poppler-utils tesseract-ocr tesseract-ocr-chi-sim libreoffice-writer fonts-noto-cjk
```

## 已实现的工具

- 音视频：转码、音轨提取/转换、裁剪、合并、压缩、抽帧、音量标准化、频谱降噪。
- 字幕/语音：SRT/VTT/ASS 转换、文本字幕轨提取、预配置 Faster Whisper 模型转写为 TXT/SRT/VTT。
- PDF：拆分、合并、旋转、无损压缩、渲染图片、文本提取、保留布局/图片/有框表格为 Word（附 PDF 预览）、OCRmyPDF 补充文字层/可搜索 PDF、表格 CSV/JSON。
- Word：PDF、HTML、Markdown、文本导出，段落/表格/页眉页脚文字替换。
- 图片：格式/质量/尺寸、裁剪、OCR、合成 PDF、重命名、U²-Net 去背景与边缘细化、遮罩修复、文字水印。
- 批量：统一参数多文件、参数模板、分组、逐项部分成功、失败项恢复、可取消进程、ZIP 打包、分页过滤。

准确参数以工具页面、`tools` JSON Schema 为准。每个操作有输入类型、参数范围和依赖状态；缺依赖或无有效结果会失败，不会复制文件假装完成。仅重命名操作有意保留原始字节。

## CLI

CLI 连接服务，不直接修改状态数据库。全局 `--server`、`--token-file` 位于资源命令前；`--json` 可放在任意位置。

```sh
.venv/bin/mediaforge tools --json
.venv/bin/mediaforge doctor --json
.venv/bin/mediaforge tasks create image-process ./photo.png --param width=1600 --param format=webp --wait --json
.venv/bin/mediaforge tasks list --status failed --limit 20 --json
.venv/bin/mediaforge tasks get TASK_ID --json
.venv/bin/mediaforge tasks cancel TASK_ID --json
.venv/bin/mediaforge tasks resume TASK_ID --wait --json
.venv/bin/mediaforge tasks export TASK_ID --wait --json
.venv/bin/mediaforge files download FILE_ID --output ./outputs/result.webp --json
```

`tasks create` 不加 `--wait` 只确认受理；长任务通过 `tasks wait` 查询终态。稳定退出码：0 成功/受理，2 输入/连接/权限错误，3 部分成功，4 处理失败，5 已取消，6 可恢复中断，7 等待超时，130 用户中断客户端。客户端中断或等待超时不会隐式取消服务器任务。

远程访问示例（不将令牌放入命令参数）：

```sh
export MEDIAFORGE_URL=https://107.151.245.166:18081/mediaforge
export MEDIAFORGE_TOKEN_FILE=/secure/path/workspace.token
.venv/bin/mediaforge doctor --json
```

## MCP 与项目内 Skill

使用标准 MCP stdio 服务 `.venv/bin/mediaforge mcp`。它提供能力发现、诊断、上传、提交、状态、逐项详情、脱敏日志、取消、恢复、预览、下载和 ZIP 打包。使用官方 Python MCP SDK 实现初始化、`tools/list`、`tools/call` 与 Schema。

```json
{
  "mcpServers": {
    "mediaforge": {
      "command": "/absolute/path/mediaforge/.venv/bin/mediaforge",
      "args": ["mcp"],
      "env": {
        "MEDIAFORGE_URL": "https://107.151.245.166:18081/mediaforge",
        "MEDIAFORGE_TOKEN_FILE": "/secure/path/workspace.token",
        "MEDIAFORGE_LOCAL_ROOTS": "/authorized/input/folder",
        "MEDIAFORGE_OUTPUT_ROOTS": "/authorized/output/folder"
      }
    }
  }
}
```

以上是配置示例，不包含真实凭证，也不会自动安装到其他应用或全局配置。项目技能包见 [skill/SKILL.md](skill/SKILL.md)，加载说明见 [docs/AI.md](docs/AI.md)。

## 模型与边界

`MEDIAFORGE_ASR_MODEL` 指向预下载 CTranslate2 模型目录；`U2NET_HOME` 指向含 `u2net.onnx` 的目录。运行任务时不自动下载。诊断页明确显示模型、CPU/CUDA 与 OCR 语言。安装方式、来源和限制见 [docs/MODELS.md](docs/MODELS.md)。

PDF→Word 默认重建可编辑版式、附渲染预览；复杂多栏/公式/无框表格仍需核对，text 模式仅文字重排；ASS→SRT/VTT 丢弃样式；动画图片目前处理首帧；图片字幕轨不能直接导出为文本；压缩不保证已优化文件继续变小；OCR/ASR、复杂表格和修复结果需要人工复核。水印与修复只针对拥有编辑权的素材，不提供 DRM/版权保护绕过功能。

## 验证与发布

```sh
.venv/bin/python -m pytest -q
# 有已配置本地模型与合成语音样本时，设置环境后复测全部能力
MEDIAFORGE_ASR_MODEL=/path/model U2NET_HOME=/path/u2net MEDIAFORGE_SPEECH_FIXTURE=/path/synthetic.wav .venv/bin/python -m pytest -q
```

没有配置可选模型时相应测试显式 skip，不能当作通过。原始 0.1 的审查与复现记录在 `reports/product-audit-2026-09-10/`；那些缺陷记录对应旧提交，修复后的验收依据见 [reports/verification.md](reports/verification.md)。

源码在本机推送 [GitHub](https://github.com/zhaowenlong20000615/mediaforge)，发布包在本机生成，再通过 SSH 上传固定服务器。完整流程、回滚、令牌获取和迁移见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 项目下载与 AI 接入

本项目自己的中文下载、安装和 CLI／MCP／技能说明：https://107.151.245.166:18081/mediaforge/access/ 。接入包固定到已核对的客户端提交，不带业务凭证；下载沿用原项目身份，不依赖私有 GitHub 访问。运行位置：命令行和 AI 工具连接本项目服务；数据和授权仍由原项目管理。 Windows 本次未实机验证。构建：python3 accessDelivery/build.py。

## 0.2.2 运行与验证说明

处理仍在当前连接的服务中完成。诊断不再仅检查程序路径：FFmpeg、FFprobe、Poppler、OCR 和 LibreOffice 必须能完成启动自检，缺动态库等情况显示“启动失败”。修复后最多30秒更新缓存。工作区清理会一起保护仍被任务引用的输入与结果，避免“继续处理”链路被拆断。

PDF OCR 改用 OCRmyPDF；已有文本页保留，扫描页增加文字层。它不承诺复杂版式转Word或任意OCR质量。CLI下载校验服务端记录的大小与SHA-256，再原子发布文件；校验失败不覆盖已有文件。

前端端到端测试采用Playwright，axe-core检查可访问性。运行 `npm ci && npm run test:ui` 前启动隔离测试服务并配置 `MF_BROWSER_URL`、`MF_BROWSER_TOKEN_FILE`；仅使用测试工作区。详见 `reports/audit-2026-10-06/verification.md`。

已有多个FFmpeg安装时，诊断与执行共用已核验的程序路径；macOS默认安装损坏时，会尝试已安装的Homebrew完整版本。启动检查最多缓存30秒。不会改写系统PATH、安装系统软件或替换其他项目的依赖。

## 0.2.3 输出质量

兼容视频合并直接保留原始码流；其他视频沿用首段分辨率/帧率，以 CRF 18 转码。图片转 PDF 使用 img2pdf 无损嵌入，JPEG 默认质量92、4:4:4，WebP 默认无损；保留有效色彩配置并正确转换 CMYK/Lab。HDR 重编码当前会明确拒绝，避免静默输出错误色彩。

Word 的 HTML/Markdown 正文导出使用 Mammoth、markdownify，保留标题、列表、表格和内嵌图片；样式与页眉页脚限制显示在结果中，完整外观使用 PDF。PDF→Word 使用固定版本 pdf2docx，并以 LibreOffice 渲染后复查可见文字和数字；发现明显丢字/漏数会失败，成功结果附排版预览。

服务器语音默认使用 small 模型，逐词对齐并限制字幕两行/六秒；OCR 默认中英文；音量标准化采用两遍测量。模型选择以实测为准：BiRefNet-lite 在验收人像中漏掉头盔，故保留 U²-Net 并使用边缘细化。质量证据见 [质量验收报告](reports/quality-2026-10-07/verification.md)，组件来源与许可见 [第三方说明](docs/THIRD_PARTY.md)。

0.2.4补充OCR版面选择：默认block连续文字，避免本轮中文样张漏掉整行；多栏用auto、散落标签用sparse。图片与扫描PDF共用该设置。

0.2.5使用PyMuPDF正确读取中文OCR文字层，避免无效NUL字符影响TXT/Word导出。CLI/MCP遇到临时连接断开时，仅自动重试只读请求及带原幂等键的任务/导出提交一次，避免重复操作。

0.2.6增加存储异常恢复：调度线程持续重试，空间/数据库恢复后继续已有排队任务；诊断显示具体故障，已完成结果保留。本机下载空间不足返回local_storage_full，不发布半成品。
