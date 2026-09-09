# MediaForge 验证报告

## 已通过

- `python3 -m pytest -q`：核心任务、Unicode 文件名、幂等和取消测试。
- CLI `--help`、`tools --json`、`doctor --json`、任务提交/查询/预览。
- REST `/healthz`、`/readyz`、`/version`、`/api/tools`、`/api/doctor`，并用 JSON 上传接口验证浏览器文件导入。
- 使用本机 FFmpeg 生成短音频并完成 `audio-extract` 输出校验。
- 批量任务生成 ZIP 结果包；浏览器上传与结果下载路径已接通。
- stdio MCP JSON-RPC 工具发现与 `doctor`。
- `bash -n deploy/*.sh` 与 DRY_RUN 目标校验。

## 条件与限制

- 本机是否安装 FFmpeg/Poppler/LibreOffice/OCR/Whisper 由 doctor 实时决定；未安装适配器时任务会保留/复制输入并明确依赖状态。
- SSH 检查目标 `107.151.245.166` 返回 `Permission denied (publickey)`，因此未执行真实上传/启动；已完成本机 DRY_RUN 上传校验，不能冒称线上通过。
- fixture 仅用于自动化状态机验证，不代表媒体内容质量。加密/损坏 PDF、复杂表格和 GPU ASR 需在依赖配置后单独验证。
