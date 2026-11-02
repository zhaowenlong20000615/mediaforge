# MediaForge 存储实现与103验收

2026-11-01，America/Los_Angeles。**当前运行0.2.8 / bf40baf34653ee4575034c854fa90b6c062eeb39**，入口 https://103.236.60.28:18081/mediaforge/ 。后台清理状态、提交后物理删除失败、发布资源收尾及可选独立浏览代理已实现并发布。新版本维护已实际成功执行，没有观察到生产清理故障；故障验证在本项目隔离临时目录中注入，不能冒充生产曾发生的故障。

本轮只操作MediaForge及登记表自己的条目，不改其它项目、旧107、全局出口或长期锁，不发送跨窗口消息，不新增付费AI调用。初始9处本项目103迁移改动经核对后保留并纳入发布，没有覆盖其它项目或共享文件的其它条目。

## 清理状态和原有保留规则

- 沿用原有配额、7天保留和任务/文件连通图引用保护。没有将共享方案里的7天候选、24–48小时ZIP或低清取舍自动应用到业务原件。
- Engine使用独立维护线程，按工作区保存last_attempt、last_success、last_failure、state、脱敏error、backlog及measured_at。只有一份有界maintenance.json，原子替换，故障文本不包含凭据或内部异常原文。诊断页、CLI doctor、MCP diagnose_workspace调用同一授权API，普通工作区只能看到自己的记录。
- 尚未执行、上次中断、未测得积压和状态持久化失败分别表达；null积压不等于零。状态文件无法写入时当前进程明确返回persistence_error，不能保证断电前未落盘的信息跨重启保留。
- 0.2.8补齐数据库提交后的物理删除：删除失败返回错误并保留恢复manifest，不把已退役文件搬回原位置制造无索引副本。下一轮先核对恢复清单再重试；事务提交前失败仍恢复原文件和索引。不中断已有活动任务。

## 派生文件及精确编辑边界

video-transcode默认custom保持原行为。只有显式选择profile=browse-540p才生成最大960×540、30fps、CRF23的浏览文件，不放大空间尺寸，保留音轨和播放时长；完成前检查实际规格、时长、音轨数并完整解码。

派生使用独立file ID，保存父ID/SHA、profile、参数、输出SHA/尺寸/帧率/音轨、播放时间关系和original_replaced=false。图片调整、裁剪/压缩和抽帧等既有派生也保存来源；抽帧记录采样位置，时间关系不是逐帧精确映射。UI和Skill明确：浏览代理仅浏览，精确编辑取父原件；取消、失败和转码成功都不授权覆盖或退役原件。

4份线上10秒样例实际输出960×540/30fps/H264+AAC、约10.008秒；全部完整解码，原件重新下载后SHA不变。处理中取消确认后在同一task恢复4/4，成功项SHA与attempt不变，同幂等键不创建第二任务。[批量证据](../reports/storage-2026-11-01/business.json)。最终0.2.8再次实际转码、解码及浏览器播放通过，[最终样例](../reports/storage-2026-11-01/final-preview.json)、[UI证据](../reports/storage-2026-11-01/new-ui.json)、[预览截图](../reports/storage-2026-11-01/browse-ui.png)。

不接管StoryLoom或抖音目录，未增加冷存储或远端原件恢复。真实作品中的小字、人脸、运动等质量仍须另行验证；未用浏览代理替换精确编辑或模型原输入。

## 发布保留和容量准入

1. 本机提交推送GitHub、本机构建无凭证包，再SSH上传103.236.60.28；实际hostname=ser693712513899，使用103专用身份。upload/activate均校验目标与容量：至少10GiB可用，并满足解包字节+2GiB环境峰值估算。本轮第三方依赖未升级，wheel按锁与SHA校验后从明确前一版缓存离线安装，在新版本保留物化硬链接，不反复上传整套依赖。
2. 本项目短时deploy.lock及交付activation.lock覆盖发布/清理，不设置跨项目长期锁。成功后预览并重新核对项目归属、SHA树、文件身份、进程cwd/exe/fd/maps/参数和解释器/shebang/pth/符号链接/pip依赖图，才退役无引用版本。未在新版本按SHA物化的pip来源继续保留。
3. 程序与交付各保留current和previous，以及传递运行依赖。仅按完整组处理已验证上传包/sidecar，48小时只是旧上传副本的规则，不是业务原件保留期。近期未知目录、缺完整组或无法核验者跳过；数据、模型、密钥、授权、余额、回执/账单不在发布清理范围。不执行global prune或删除数据卷。
4. 维护失败单独记录release-retention.json；deploy/release.py status可查，retain只预览、retain-apply重新核对后执行，不因收尾失败回滚健康业务服务。Nginx规则和服务单元未变时避免共享reload；只重启本项目业务进程。
5. 复核发现旧发布器只将成功元数据写BASE/deployment.json，刚退役的成功版本会因缺逐版本回执被保守跳过。已补每版成功回执；本轮历史版本仅按已保存的真实运行快照、原deployed_at与一致SHA补齐，没有伪造发布成功。核验后旧555环境已退役。[回执依据](../reports/storage-2026-11-01/verified-release-receipts.json)、[预览](../reports/storage-2026-11-01/receipt-retention-preview.json)、[实际收尾](../reports/storage-2026-11-01/receipt-retention-applied.json)。该发布工具补充从本机SSH发送生效，运行程序源码仍为上述bf40baf。

当前程序0.2.8/bf40baf，回滚程序0.2.7/1d498b3，解释器均实际导入各自版本；交付组件同样保留bf40baf当前及1d498b3回滚。SQLite quick_check=ok；最终仅剩初始2个保留任务，测试只清理本轮隔离资源。发布是兼容代码/独立维护状态文件变化，不改SQLite结构，不重复全库备份。未实际切回旧程序或重演断电。

本轮先后按实际引用退役0.2.5、0.2.6以及已被替代的首个0.2.7/555环境，另清理旧交付目录、旧配置快照和验证过的上传组。两份孤立0.2.3 sidecar缺完整上传组，保守跳过。逐路径、SHA及逻辑字节以[合并删除清单](../reports/storage-2026-11-01/summary.json)和各次原始清理报告为准，不能把共享硬链接的逻辑大小相加当成实际释放量。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| 最终本地回归 | 90通过、2模型条件不足跳过；[结果](../reports/storage-2026-11-01/local-tests-final.json)。两个模型已在103真实业务复验通过 |
| 0.2.8线上工具 | 31/31真实处理至终态、下载SHA/尺寸/时长/页数/内容核对，含ASR、去背景、文档、OCR、字幕、ZIP；[结果](../reports/storage-2026-11-01/workflows-028.json) |
| 0.2.8 CLI/MCP | 11/11，认证、会话退出、错误退出码、真实缩放/下载、MCP握手/发现/预览/凭证文件拒绝；[结果](../reports/storage-2026-11-01/clients-028.json) |
| 网页原回归 | 8/8、0重试/跳过，覆盖上传/下载/预览、页码错误、中文筛选、窄屏、断网和竞态；运行于中间0.2.7，之后只调整诊断空值显示；最终维护/播放页面另行复验；[结果](../reports/storage-2026-11-01/browser.json) |
| 最终界面 | 维护状态/积压/成功失败时间可见；修复截图发现的null显示；实际浏览器播放代理、明确原件用途；[结果](../reports/storage-2026-11-01/new-ui.json)、[维护截图](../reports/storage-2026-11-01/maintenance-ui.png) |
| Linux隔离故障 | 0.2.8实际注入清理前权限错误及数据库已提交后的物理删除错误；状态持久保存、活动48px图片任务继续、无索引副本未被还原、解除故障后残留和manifest消失；[两条场景](../reports/storage-2026-11-01/isolated-linux-final.json) |
| 生产维护状态 | 新版本定时维护state=ok、last_failure=null、积压0且无持久化错误；[实际回读](../reports/storage-2026-11-01/final-state-028.json)。不追溯推断旧版本是否曾静默失败 |
| 最终下载包 | 0.2.8/bf40baf认证下载、SHA/CRC、实际下载源码CLI/MCP运行及maintenance一致、浏览profile发现通过；[证据](../reports/storage-2026-11-01/download-cli-mcp-028.json)。沿用现有依赖，未重做独立联网安装，不冒称独立安装通过 |
| 重复发布 | 同一555制品两次顺序激活均already_active、无新环境；该观察区间本项目du为3,694,219,264字节不变；并发尝试被项目锁拒绝后顺序通过；[证据](../reports/storage-2026-11-01/repeated-activation.json)。本轮三次不同提交实际发布的最终程序/交付数量仍各2 |

首轮曾同时运行31工具批次、代理批次、网页及CLI/MCP，一项网页15秒断言及一项MCP60秒等待超时；没有计为通过。原[网页](../reports/storage-2026-11-01/browser-concurrent.json)、[客户端](../reports/storage-2026-11-01/clients-concurrent.json)记录保留。服务器任务继续完成；批次结束后复验通过。CPU重任务下等待时间仍有限制；客户端等待超时不等于服务器取消。那次已知隔离残留任务已按确切ID核对清理，[记录](../reports/storage-2026-11-01/interrupted-smoke-cleanup.json)。

## 发布与磁盘证据

最终包 `mediaforge-0.2.8-bf40baf34653-20261102T050340Z.tar.gz`，本机UTC2026-11-02T05:03:40Z构建，SHA-256 `e1f43913562f8a3345a2f29bd9c643f9176831a729935cf20d449a48e49974f3`。本机代码bf40baf已推送GitHub main；后续发布工具回执补充及此报告单独提交，不将文档提交冒充运行版本。[包元数据](../reports/storage-2026-11-01/release-028.json)、[激活](../reports/storage-2026-11-01/deployment-028.json)、[交付组件](../reports/storage-2026-11-01/delivery-028.json)。

初始本项目du为4,034,256,896字节；最终观测为3,763,331,072字节，净减少270,925,824字节，包含新环境和正常本项目活动。两套当前/回滚及模型仍保留，不将它们当缓存，也不将所有旧目录逻辑字节当净释放量。

最终UTC 2026-11-02T05:12:35.441279+00:00 的df：

```
Filesystem        1B-blocks        Used   Available Use% Mounted on
/dev/vda1      124678225920 92488675328 32172773376  75% /
```

初始根分区91%、可用11,715,411,968字节；期间其它项目也在发布/清理。全机df净变化不能全部归因于MediaForge。[最终目录/版本/容量](../reports/storage-2026-11-01/final-disk-028.json)。

## 剩余限制

没有验证Windows/CUDA、任意超大文件、高并发、断电或真实生产磁盘耗尽。故障注入只在本项目独立测试目录，不伪称生产故障。浏览代理有损，实际素材质量与是否退役原件由所属项目用途决定；没有新第三方取回/恢复承诺，没有改变固定资产或调用方权限。
