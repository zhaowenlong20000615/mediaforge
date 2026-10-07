# 本项目交付组件的发布与回滚

交付页面和安装包在本项目维护。先提交并在本机推送源码，再构建和上传。服务端不访问 GitHub。此流程只发布交付组件，不迁移业务数据库或权限，不重启业务服务。

预览：python3 accessDelivery/publish.py --dry-run

发布：python3 accessDelivery/publish.py

SSH 目标固定为 107.151.245.166；可用 DELIVERY_SSH_KEY 指定自己的本机密钥文件。发布前要求 accessDelivery 与 tool.manifest.json 已提交且 GitHub main 与本机提交一致。安装包从 config.json 指定的提交白名单构建，不携带 .env、令牌、数据库或私钥。

Nginx 入口继续调用本项目原认证。发布包校验失败、元数据不符或 Nginx 配置不通过时停止；配置检查失败会恢复原入口。每次更新业务主程序之后核对该入口仍在，必要时重跑本项目的组件发布命令。不要用工作台身份代替项目身份，也不要为了方便放宽内容安全策略。

发布目录保留上一个版本及 deployment.json / backups 中的记录。回滚只将本项目 access/current 原子切回其中记录的上一目录；若本次首次加入入口，还原同项目 backups 中的 Nginx 配置，运行 nginx -t 后 reload。不要删除其他项目配置或变更业务授权。

原生归途服务需先有 0.1.2 的管理员鉴权下载路由；组件发布本身不更改主程序。Sub2API 的隔离实例使用 --fork，部署地址及权限与正式实例分开。

2026-10-07：0.2.2 接入包已从提交0c00918生成并发布，认证下载、ZIP/SHA校验、独立安装与远程CLI/MCP实际处理通过。当前证据见 `reports/audit-2026-10-06/delivery-checks.json` 与 `downloaded-client-functional.json`。

2026-10-07：0.2.6客户端从f159f8f生成并发布，与应用同版本/同代码提交；认证下载、ZIP/SHA、独立安装及真实CLI/MCP任务与下载全部通过。证据见reports/quality-2026-10-07/delivery-checks.json及downloaded-client-functional.json。
