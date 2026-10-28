# MediaForge 103 环境与业务验收

日期：2026-10-27，America/Los_Angeles。原始证据时间为 UTC 2026-10-28。

结论：103 环境和本轮实际业务流程通过；修复并发布了客户端下载包中仍指向 107 的安装文档。应用 HTTP 日志仍有下述关联精度限制，因此没有采用绕过原 HTTPS/Nginx 的调用路径，也不声称完整审计等价。未操作 107，未读取其它聊天、联系其它窗口或修改其它项目。

## 真实目标与版本

- SSH 目标 `103.236.60.28:22`，实际 hostname `ser693712513899`，仅用本项目 103 专用 SSH 身份。入口为 `https://103.236.60.28:18081/mediaforge/`。
- 服务程序仍为 **0.2.6 / f159f8fbb4c8a6767622d8e9b3bedf326dedad1b**，发布包 SHA-256 `ac032e520e4e07fa105c729415773e75d7411c0a2e8f80aaa632f0e2cce3516f`。本轮未更新或重启业务服务。
- `mediaforge-web.service` active/running，用户 mediaforge（UID995），组 www-data；Unix socket `/run/mediaforge/api.sock`。进程限制 AF_UNIX、NoNewPrivileges、ProtectSystem=strict、ProtectHome=true，文件处理和模型推理不依赖其它服务器项目。
- SQLite quick_check=ok；初始任务为空，所有新增任务均为本轮隔离样例。新机没有旧机任务和媒体，不能用旧机任务 ID 声称新机业务成功。
- 当前服务目录与 0.2.5 回滚目录、各自解释器和 99 个 wheel 均存在；模型及依赖保留。已核对回滚材料，本轮没有实际切回旧程序或重演服务重启。

## 必需配置和依赖

配置来源是 `/opt/mediaforge/runtime.env`（root:root 0600）、项目受控的管理员令牌文件，以及 `/opt/mediaforge/models`。报告不包含真实令牌、Cookie 或密钥。数据目录 0700、令牌和数据库 0600；均归 mediaforge。实际业务写入、处理、读取和清理通过，未扩大权限。

`MEDIAFORGE_PUBLIC_URL=https://103.236.60.28:18081`；Cookie 使用 `/mediaforge/`、Secure、HttpOnly、SameSite=strict。默认并发2、单文件512MiB、工作区10GiB、保留7天，均由实际 doctor 回读确认。登录、会话注销、匿名拒绝和非管理员权限检查通过。

| 依赖 | 103 状态与本轮证据 |
| --- | --- |
| FFmpeg、FFprobe | 启动自检通过；实际转码、音轨、裁剪、合并、压缩、抽帧、响度、降噪通过 |
| Poppler | 启动自检通过；PDF 转图片及浏览器逐页预览通过 |
| Tesseract | chi_sim / eng / osd 可用；真实中英文图片 OCR 通过 |
| LibreOffice | 启动自检通过；Word→PDF、PDF→Word 后排版预览通过 |
| Pillow | 可用；缩放、裁剪、水印、图片预览与实际像素尺寸通过 |
| pypdf | 可用；拆分、合并、旋转、压缩及页数/角度核对通过 |
| PyMuPDF | 可用；扫描 PDF 中文文字层、搜索及继续提取全文通过，无 NUL |
| python-docx | 可用；Word 批量替换与实际正文核对通过 |
| pdfplumber | 可用；PDF 表格 CSV/JSON 处理通过 |
| pysubs2 | 可用；字幕格式转换及文本字幕提取通过 |
| OpenCV | 可用；实际授权遮罩修复通过 |
| OCRmyPDF | 可用；PDF OCR 处理、下载、中文文字层与后续提取通过 |
| Mammoth | 模块就绪；本轮未单独验收 Word→HTML/Markdown 所有表现 |
| img2pdf | 可用；实际图片合成 PDF、输出页数与哈希核验通过 |
| pdf2docx | 可用；生成可打开的 DOCX 与实际排版 PDF，浏览器预览通过 |
| Faster Whisper small | 配置及模型文件就绪；CPU 实际识别通过，批量取消/恢复后的4份文字均含预期语音内容 |
| rembg / U²-Net | 配置及模型文件就绪；实际去背景完成并下载核验 |
| Noto CJK 字体 | `NotoSansCJK-Regular.ttc` 可读；中文水印和中文 OCR 样例通过 |
| 浏览器 | 服务端不依赖自动化浏览器；客户端 Chromium 的8项网页回归通过 |
| CUDA | 0设备；当前使用CPU，不声称GPU或Windows实机通过 |

模型完整文件大小及 SHA-256、全部19条 doctor 检查和31项实际工具目录见[环境证据](../reports/server103-2026-10-27/environment.json)与[诊断/目录](../reports/server103-2026-10-27/preflight.json)。启动或导入通过和实际运行验证在上表分别说明。

## 调用位置、回环和日志

| 发起位置 | 实际路径 | 认证与日志判断 |
| --- | --- | --- |
| 用户浏览器 / 本机 CLI / stdio MCP | `https://103.236.60.28:18081/mediaforge` | 严格TLS、同源约束、工作区令牌/会话、原Nginx与应用日志链路保留；下载URL仍为103 |
| 103 Nginx | 原有 Unix socket → MediaForge API | socket权限、原有认证与任务归属不变；未新增直连后端入口 |
| 103 文件处理进程 | 本项目独立文件目录、系统工具、预装模型 | AF_UNIX限制，不调用AI中转、账号工作台或其它项目，无外部消息、收费生成、第三方媒体回调或独立计费链路 |
| 103 宿主机请求自身103地址 | 路由显示 local / lo | 这是宿主机直连事实；不外推到用户电脑、容器或外部供应商。本轮业务客户端在Mac上访问公开HTTPS |

服务器进程 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY 及小写变量均未设置。CLI/MCP 的共享 httpx 客户端明确 `trust_env=False`，未配置显式代理；本机环境变量只记录是否设置，未打印值。没有把用户链接或MCP配置改为127，没有关闭证书校验或放宽Origin/权限。TLS 证书链及IP SAN严格校验通过，有效期见[边界检查](../reports/server103-2026-10-27/edge-checks.json)。

原有 Nginx 使用 `/var/log/nginx/access.log`；本项目应用JSON请求日志进入 journal，任务生命周期事件保存在SQLite并由授权API读取。抽样10个返回的API request_id全部可在journal定位；取消、恢复和逐项执行事件与同一 task_id 可回查，工作区隔离通过。[关联证据](../reports/server103-2026-10-27/audit.json)。

已确认的限制：跨Origin提前返回403时，没有应用request_id或应用JSON日志，但同一拒绝请求能在原Nginx访问日志找到；应用HTTP JSON日志的task_id恒为空，也没有工作区身份字段，具体任务/归属需通过任务API或SQLite关联。保留现有入口可以保留当前证据，不能因此宣称已达到完整的请求→身份→任务审计。未更换访问路径，未绕过Nginx，也未新增收费或用量路径。

## 实际业务验证

所有样例均为项目已有或本轮生成的小型合成媒体、文档和图像。它们是实际送到103处理并下载的文件，不是模拟接口返回，不代表任意真实文档质量。

- **31/31**：实际HTTPS上传、处理至终态、下载SHA核验；覆盖音视频、字幕、ASR、PDF、Word、图片和ZIP导出。[结果](../reports/server103-2026-10-27/workflows.json)
- **8/8 网页，0重试、0跳过**：上传、尺寸参数、结果图片/PDF预览、下载哈希、无效页码、中文筛选、窄屏、断网恢复、上传与切页竞态、幂等键更新。axe检查无critical/serious问题。[结果](../reports/server103-2026-10-27/browser.json) · [桌面](../reports/server103-2026-10-27/desktop.png) · [窄屏](../reports/server103-2026-10-27/mobile.png)
- **11/11 CLI/MCP**：标准握手、发现、真实处理、预览与下载、失败退出码4、凭证文件拒绝、Secure/HttpOnly会话及退出失效。[结果](../reports/server103-2026-10-27/clients.json)
- **20/20 边界检查**：匿名401、管理员边界403、恶意Origin403、跨工作区文件/任务404、同键不重复、异参同键409、实际Range206、可操作错误、ASR处理中取消、保留成功输出和attempt、同任务恢复完成、任务事件、下载鉴权及包完整性。[结果](../reports/server103-2026-10-27/edge-checks.json)
- **中文质量补测**：图片OCR、扫描PDF OCR及继续提取文字；逐项核对“交付要求”、合同编号、金额和全部目标行；PDF搜索中文命中，文字层无NUL。[结果](../reports/server103-2026-10-27/chinese-quality.json)
- **实际下载包独立安装**：严格认证下载、SHA/ZIP CRC、安装到新虚拟环境、导入路径确认；再独立运行11项CLI/MCP检查全部通过。[安装/包](../reports/server103-2026-10-27/downloaded-client.json) · [实际调用](../reports/server103-2026-10-27/downloaded-client-functional.json)

主要命令复用了 `deploy/smoke.py`、`deploy/client_smoke.py`、`npm run test:ui`；使用本次隔离令牌文件和103地址。补充边界/中文检查脚本在本机忽略目录 `var/server103Validation-20261027/`，未新增测试框架或全局配置。本轮只清理了自己隔离工作区的测试文件和任务，完整业务事件证据在清理前已保存；临时独立安装环境亦已删除。[收尾状态](../reports/server103-2026-10-27/final-state.json)

## 修复、推送、发布和回滚

发现：线上页面/manifest已是103，但原下载ZIP中的 `client/README.md`、`client/docs/DEPLOYMENT.md` 仍给出107地址。已修正构建器，使当前安装说明与连接示例按103公开入口生成，并明确记录生成文档；Skill同步103入口。未对历史验收记录做全局替换。

- 本机源码提交并推送 GitHub `main`：**d395e7ca0aab4811d9da439cfb936f3f6f72bb5f**，仓库 `https://github.com/zhaowenlong20000615/mediaforge.git`。
- 为保留已有未提交迁移内容，从该提交的干净本机副本构建，显式指定 `MEDIAFORGE_DELIVERY_PUBLIC_URL=https://103.236.60.28:18081/mediaforge/`。客户端 `mediaforge/` 程序逐文件与已部署 f159f8f 无差异，仅更新文档和生成流程。
- 本机发布包 `mediaforge-d395e7ca0aab4811d9da439cfb936f3f6f72bb5f.access.tar.gz`，SHA-256 **6b01eb5807fe5044ed92fcc1ad3aca0d35c52147ba79ef2fcbf6a0d3ea2e1aa0**。
- SSH上传103、本项目 `access/activation.lock` 锁内解包和SHA/文件白名单核验、确认新旧Nginx规则字节一致后原子切换静态 `access/current`。没有修改Nginx配置、reload共享服务、重启业务或替换数据库/模型。[发布记录](../reports/server103-2026-10-27/access-release.json)
- 接入包回滚点仍为 `/opt/mediaforge/access/releases/f159f8fbb4c8a6767622d8e9b3bedf326dedad1b`，静态发布元数据记录previous。服务的0.2.6当前和0.2.5程序回滚点不变；本轮不需要新的全库备份。
- 重新下载后的所有活动文档和MCP示例已核对无107地址；文件鉴权、独立安装及真实CLI/MCP完成。9处既有未提交迁移改动逐文件SHA保持一致，未加入本轮提交；登记表等共享文件未修改。

## 未覆盖和剩余事项

- 应用HTTP日志的身份/task关联以及跨Origin拒绝日志仍有限制，详见上文；未将其写成通过，也未启用可能丢失原Nginx日志的后端直连。
- 本轮没有演练103服务重启/断电、磁盘耗尽、程序回滚切换、超大文件、高并发、Windows、CUDA或所有浏览器组合；旧107证据不替代这些新机验证。
- OCR/ASR/抠图、复杂版式、公式及无框表格仍需人工内容确认。本轮精确断言仅覆盖报告列出的样例，不承诺所有文件效果。
- CPU处理路径和预装模型不需要新设备或第三方授权；没有因本轮验证迁移或撤销107上的任何身份。
