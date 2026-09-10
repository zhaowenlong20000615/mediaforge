# AI 与命令接入

Web、CLI、MCP只能通过同一受认证HTTP API操作文件和任务。CLI命令及MCP配置见README。`mediaforge mcp`提供标准stdio协议；模型工具默认返回结构化摘要，逐项详情和日志单独查询。

输入：用户授权的本地文件通过upload工具流式上传，返回工作区文件ID。任务参数按 `discover_operations` 的JSON Schema填写。远程服务不能读取调用端路径，调用端也不能指定服务器路径。

输出：状态、阶段、进度、逐项数量、错误分类、输出文件ID和元数据。预览/下载URL需要当前工作区认证，没有公开分享令牌。下载在调用端配置目录内落盘，拒绝覆盖。

安装技能：配置stdio MCP后，将 `skill/` 手动添加为应用的项目技能目录。不同应用的技能安装入口可能不同；本项目不写入用户全局配置。格式与示例见 `skill/SKILL.md`。

验收须用标准MCP客户端执行initialize → tools/list → tools/call，并完成上传、处理、终态查询与结果核验。测试 `tests/test_clients.py` 覆盖这一路径，以及越界上传拒绝。
