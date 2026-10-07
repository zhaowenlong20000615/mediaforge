# 发布、迁移与回滚

唯一目标：`root@107.151.245.166:22`。本机推送GitHub，本机打包，再SSH上传；服务器只离线安装发布包中的wheel，不访问GitHub。

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

`DEPLOY_SSH_KEY`可指向有该服务器权限的密钥文件。脚本不打印密钥内容。TARGET_HOST若不是107.151.245.166立即拒绝。

服务器准备Ubuntu依赖：python3-venv、ffmpeg、poppler-utils、tesseract-ocr、tesseract-ocr-chi-sim、libreoffice-writer、fonts-noto-cjk。模型由本机单独上传 `/opt/mediaforge/models` 并核验，不在任务中下载。安装命令不会在服务器访问GitHub。

服务：`mediaforge-web.service`，独立mediaforge用户，Unix socket `/run/mediaforge/api.sock`。Nginx仅新增本项目conf.d文件与18081端口，使用已存在的IP证书提供 `https://107.151.245.166:18081/mediaforge/`。HTTP入口重定向HTTPS。三个健康接口也可在端口根路径查询。

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
