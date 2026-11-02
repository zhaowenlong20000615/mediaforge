# 发布、迁移与回滚

唯一目标：`root@103.236.60.28:22`。本机推送GitHub，本机打包，再SSH上传；服务器只离线安装发布包中的wheel，不访问GitHub。

## 准备和本机构建

```sh
uv sync --frozen --all-extras
.venv/bin/python -m pytest -q
uv export --frozen --all-extras --no-emit-project --format requirements-txt --output-file dist/dependencies.txt
python3 -m pip download --dest dist/wheels --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_34_x86_64 --platform manylinux_2_27_x86_64 --implementation cp --python-version 312 -r dist/dependencies.txt
./deploy/build.sh
git add -A
git commit -m 'release: verified MediaForge update'
git push origin main
./deploy/package.sh
```

package拒绝未提交源码，包只包含Git跟踪的允许文件、项目wheel、固定Linux wheels及依赖清单。包外sidecar记录版本、commit、构建UTC时间及SHA-256，不包含凭证、模型缓存或运行数据库。

## 上传/激活

```sh
export PACKAGE=/absolute/path/to/dist/mediaforge-VERSION-COMMIT-TIME.tar.gz
DRY_RUN=1 ./deploy/upload.sh
DRY_RUN=1 ./deploy/activate.sh
./deploy/upload.sh
./deploy/activate.sh
./deploy/status.sh
```

`DEPLOY_SSH_KEY`可指向有该服务器权限的密钥文件。脚本不打印密钥内容。TARGET_HOST若不是103.236.60.28立即拒绝。

服务器准备Ubuntu依赖：python3-venv、ffmpeg、poppler-utils、tesseract-ocr、tesseract-ocr-chi-sim、libreoffice-writer、fonts-noto-cjk。模型由本机单独上传 `/opt/mediaforge/models` 并核验，不在任务中下载。安装命令不会在服务器访问GitHub。

服务：`mediaforge-web.service`，独立mediaforge用户，Unix socket `/run/mediaforge/api.sock`。Nginx仅新增本项目conf.d文件与18081端口，使用已存在的IP证书提供 `https://103.236.60.28:18081/mediaforge/`。HTTP入口重定向HTTPS。三个健康接口也可在端口根路径查询。

配置：`/opt/mediaforge/runtime.env`，数据：`/opt/mediaforge/data`，模型：`/opt/mediaforge/models`，当前发布：`/opt/mediaforge/current`，发布记录：`/opt/mediaforge/deployment.json`。服务禁止以root身份运行；子进程、网络地址族和资源受systemd约束。

第一次启动在数据目录创建0600管理员令牌。只通过授权SSH读取或复制到本机安全目录，不写入日志、Git或公共文档。浏览器登录页需使用该令牌；令牌不是公开入口参数。

## 激活和回滚保障

- 上传后先核对SHA-256与sidecar，再解包，拒绝符号链接/设备/路径穿越。
- 在独立版本目录离线安装，成功后原子切换current。健康检查失败时恢复上一安全发布，禁止回滚到0.1无认证版本。
- previous.json明确记录上一安全发布的实际路径，不按commit字符串排序。
- `./deploy/rollback.sh`回到previous记录，并交换回滚点。`DRY_RUN=1`仅预览。
- 禁止盲目删除历史发布与数据；当前和上一安全发布均保留。
- systemd负责异常重启，服务正常停止会将未完成任务保留为recoverable；重启后用户显式恢复。

升级0.1时，旧JSON状态和文件移到legacy目录保留，不把旧“成功”结果迁移为可信结果。新状态数据库不覆盖旧数据。0.2内部schema兼容回滚；未来破坏性迁移必须提供独立备份/恢复流程。

TLS证书由主机已有证书续期机制维护，本项目复用证书路径。发布验收需要检查证书有效期、未授权401、授权主流程、可用依赖、真实业务输出、MCP、CLI及回滚，不仅检查healthz。

0.2.3默认PDF→Word需LibreOffice做渲染核验；可编辑DOCX与PDF排版预览一同返回。模型部署默认small（详见MODELS.md）；已有runtime.env不会被activate静默覆盖，模型切换需要项目内独立备份/校验。升级依赖后将不再属于uv.lock的旧wheel移到dist/previous-wheels再打包，完整性检查会拒绝混入未锁定依赖。

## 复用已上传的依赖（可选）

第三方依赖未改变、当前服务器发布有完整wheel缓存时，可以设置`MEDIAFORGE_DEPENDENCY_CACHE_COMMIT`为该发布的完整40位Git提交后运行package。本机构建仍检查完整锁定wheelhouse；发布包携带该缓存来源，不重复携带第三方wheel。服务器在安装前强制核对当前发布commit，pip仍使用incoming requirements的require-hashes离线校验；任何缺包/不匹配都在切换current前失败。pip实际验证并安装的缓存wheel会以硬链接保留在新发布目录，共用磁盘块，可供下次更新使用。新安装、当前缓存不完整或无法确认时不设置此变量，使用完整包；回滚点仍保留。

## 0.2.7 维护与发布保留

发布前需要至少10GiB可用空间，且满足解包字节+2GiB运行环境峰值估算；upload和activate均核对103身份和容量。成功激活后自动预览/清理本项目未引用的旧程序和上传组；`python3 deploy/release.py retain`只预览，`retain-apply`在项目锁内重新核对后执行。当前/回滚、进程/打开文件、shebang、符号链接、pth及pip实际依赖保留；已在新版本wheels按SHA物化的安装来源不要求永久保留原目录。未核实元数据、近期未知目录和不完整上传组跳过。48小时只用于上传副本，不是业务原件的删除期限。

本项目部署锁和交付组件activation.lock均为短时本项目锁。静态交付发布也调用同一保留流程。清理失败写release-retention.json，可用status查询及单独重试，不把清理失败当作健康程序回滚理由。现有数据目录/模型/密钥不进入发布清理范围；兼容代码更新不重复全库备份。维护状态写数据目录maintenance.json，不修改SQLite结构，旧程序回滚可读原业务状态。
