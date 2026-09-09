# MediaForge

MediaForge 是本地优先的媒体与文档工作台：统一处理视频、音频、字幕、PDF、Word 和图片，并用可恢复任务队列追踪每个输出。

## 启动

```bash
python3 -m mediaforge.server   # http://localhost:18081
python3 -m mediaforge.cli --help
python3 -m mediaforge.cli doctor --json
```

核心业务层为 `mediaforge/core.py`，CLI、REST UI 与 MCP 共用同一 `TaskStore`。数据默认写入 `~/.mediaforge`，可用 `MEDIAFORGE_DATA` 隔离工作区。

## CLI

```bash
python3 -m mediaforge.cli tools --json
python3 -m mediaforge.cli submit image-process ./photo.jpg --param width=1600 --json
python3 -m mediaforge.cli tasks --json
python3 -m mediaforge.cli preview tsk_xxxxx --json
python3 -m mediaforge.cli cancel tsk_xxxxx --json
python3 -m mediaforge.cli resume tsk_xxxxx --json
```

退出码：0 成功，2 可操作输入错误，1 未分类内部错误。

## MCP

`python3 -m mediaforge.mcp` 通过 stdio 接受 JSON-RPC。工具：`list_tools`、`doctor`、`inspect_file`、`create_task`、`get_task_status`、`list_tasks`、`cancel_task`、`resume_task`、`get_task_preview`。只接受用户明确提供的本地文件路径；不记录文件内容或凭证。

可选依赖由 `doctor` 检测：FFmpeg/FFprobe、Poppler、qpdf、LibreOffice、Whisper、Tesseract、Pillow。未安装时核心仍可运行，并将需要外部适配器的任务标记为降级复制或未配置。

## 部署

`deploy/` 提供 build/package/upload/activate/rollback/status 脚本。默认目标严格校验为 `107.151.245.166`，上传前使用 `DRY_RUN=1` 预览；服务器只接收发布包，不访问 GitHub。当前预览已部署至 `http://107.151.245.166:18081/`，GitHub 仓库为 `https://github.com/zhaowenlong20000615/mediaforge`。
