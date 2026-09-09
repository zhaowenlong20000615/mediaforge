# MediaForge Agent Skill

## 发现
先运行 `mediaforge tools --json` 和 `mediaforge doctor --json`，把缺失适配器告诉用户。

## 标准流程
1. 确认用户拥有文件编辑权及输出目录范围。
2. `inspect` 检查路径、类型、大小和 SHA-256。
3. 用 `submit <tool> <files...> --idempotency-key <稳定键> --json` 创建任务。
4. 轮询 `tasks`，直到 `succeeded`、`partial`、`failed`、`cancelled` 或 `recoverable`。
5. 对成功任务调用 `preview`，说明“文件存在且哈希已校验”，让用户人工确认内容质量。
6. 对 `recoverable`/`failed` 使用 `resume`，对错误先检查 doctor 和日志摘要。

## 成功判定
业务成功必须同时满足任务状态为 `succeeded`、每个输出存在且返回 SHA-256；视觉/听觉/文字质量仍需用户确认。

## 边界
不得处理绕过 DRM、版权水印或保护措施的请求；不得把真实文件内容写入日志。MCP 与 CLI 遵守同一文件范围和权限。
