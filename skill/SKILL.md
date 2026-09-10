---
name: mediaforge
description: 使用 MediaForge 对授权文件进行音视频、字幕、PDF、Word、图片和批量处理；发现工具、检查依赖、创建任务、核实结果、取消与恢复。
---

# MediaForge

只对用户明确授权的文件操作。CLI、MCP和Web共用认证服务；没有文件ID时先上传，不能把本地路径当服务器路径。不要把本技能自动安装到其他任务或全局配置。

## 连接与发现

1. 配置 `MEDIAFORGE_URL` 和 `MEDIAFORGE_TOKEN_FILE`；令牌只从受控文件读取。
2. MCP 调用 `discover_operations`、`diagnose_workspace`；CLI 用 `mediaforge tools --json`、`mediaforge doctor --json`。
3. 读取工具的schema、输入类型和依赖状态。模型/语言包未配置时说明缺失项，不能使用其他文件复制冒充处理。
4. MCP本地文件范围由 `MEDIAFORGE_LOCAL_ROOTS` / `MEDIAFORGE_OUTPUT_ROOTS` 限制；不读取凭证、`.git`、SSH配置或用户未授权的目录。

## 完整流程示例

目标：批量将用户选择的图片缩到1600px，检查结果后导出。

- `upload_file({"path":"/authorized/inputs/photo.png"})` → 得到 `file_...`。
- `create_processing_task({"operation":"image-process","file_ids":["file_..."],"params":{"width":1600,"format":"webp","quality":85},"idempotency_key":"user-request-unique-key"})`。
- `get_task_status({"task_id":"task_..."})` 查询直到终态；accepted和running不表示处理完成。
- `get_task_details` 检查逐项状态、输出尺寸/格式/大小/哈希/verification。
- `preview_result` 查看结果；需要人工确认视觉、语音或文字质量。
- `download_result({"file_id":"file_...","output_path":"/authorized/outputs/result.webp"})`；拒绝覆盖已有文件。
- 多任务使用 `export_results({"task_ids":["task_..."],"idempotency_key":"export-unique-key"})`，再查询打包任务并下载ZIP。

CLI等价流程：

```sh
mediaforge tasks create image-process /authorized/inputs/photo.png --param width=1600 --param format=webp --wait --json
mediaforge tasks get TASK_ID --json
mediaforge files download FILE_ID --output /authorized/outputs/result.webp --json
```

## 成功、部分成功与失败

业务成功至少需要：终态为succeeded、每个预期输入对应成功项、输出可访问、实际格式/尺寸/时长/页数/字幕条目等与请求一致。文件存在和哈希相同本身不能证明发生了转换。

- partial：保留成功输出并说明失败项目；`resume_task` 只重试其余项。
- cancelled：任务已停止；cancel请求后要查询到此状态，不以请求成功代替停止。
- recoverable：服务中断；确认依赖与源文件仍可用后恢复。
- failed：用 `get_task_logs` 读取脱敏事件，并根据error.code/action处理。密码错误需要重新提交正确参数；不要在对话或日志中复述密码。
- wait_timeout：只是客户端等待结束；任务可能仍在运行。继续查询或按用户意图取消。
- idempotency_conflict：同键不同参数应报409，不得用随机新键掩盖可能的重复业务操作。

## 限制

PDF→Word为文字重排；扫描件先OCR。ASS样式无法完整保留到SRT/VTT。图片字幕轨不支持直接文本导出。动画图片处理首帧。OCR/ASR与复杂表格必须检查内容，不能宣布“质量已审核”。水印/修复要求素材编辑权；不处理DRM、平台版权标识或保护绕过。

## 安装/加载

在兼容AI应用中配置本项目stdio MCP，然后将本目录作为项目技能来源加载，或按该应用文档手动复制技能目录。只在用户明确要求时安装到全局配置。所需环境与配置样例见项目 `docs/AI.md`。
