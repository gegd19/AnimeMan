# T15：部署、CI 与最终交付

## 范围与决策

任务卡为《AnimeMan 代码审查与修改计划书》T15 及其明确的任务生命周期、运行路径和持久化依赖。HEAD 仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`；本卡相对 T14 完成状态实施。执行前读取 git 状态、任务卡和真实入口；仓库、祖先及相关子目录未发现 AGENTS.md。保留 T00–T14 未提交修改，没有提交、推送、发布或使用真实媒体/密钥。

用户明确选择：**“超时仍等待写线程，报告停机超时”**。因此任务卡原“等待有限时间”被解释为有限宽限与超时报告；总等待没有强杀期限。没有使用 os._exit、跳过回归、吞掉业务异常或改置信度解决失败。

## 修复行为

- `web_app.py` 改为单进程 Waitress 生产入口；默认本地监听、8 个 HTTP 线程。拒绝非 1 的 worker 设置，线程/端口/宽限参数校验失败拒绝启动。不会复制多进程任务状态。
- Web 与非预览 CLI 共用缓存目录内的操作系统独占进程锁。未知内容和符号链接锁文件保留并报错，第二个所有者不得截断文件；正常退出后保留锁 inode，旧 PID 不影响重启。CLI 在可能创建配置前就加锁；预览仍保留原只读路径。
- SIGTERM/SIGINT 停止接受连接、锁定停机状态、取消任务，等待任务线程及已有 HTTP 线程退出。应用仍处理到的停机写请求返回 503（新连接因停止监听而不能进入）；重置不能清除停机闩锁。到期记录 `shutdown_timeout:` 后继续等待，安全排空后退出码 1；未超时退出码 0。已提交记录/产物保留，未提交事务按取消契约清理。
- Compose 默认 UID/GID 1000:1000，支持明确的正整数 PUID/PGID，复用基础镜像已有 GID（如 NAS 常用 100），取消 root 覆盖；默认仅发布到宿主 loopback。源 bind 为只读，配置/缓存/日志和独立字幕 work 卷可写，缺失宿主 bind 不自动创建，随机 SECRET_KEY 必须显式提供。
- Compose 使用 `stop_grace_period: -1s`，已实测引擎最终 `Config.StopTimeout=-1`，避免宽限后被引擎强杀。文档说明其他启动方式必须保持同一策略，不承诺外部 SIGKILL、断电或存储故障下零丢失。
- 原 Docker 浮动 Python 3.11 改为 T00–T14 已测试的 Python 3.12.15，并固定基础 manifest digest；这是部署运行时的兼容变化，3.11 不在本轮最终验证范围。多阶段编译，仅复制代码与资源，运行身份非 root。真实 Docker 上下文探针验证允许资源存在、18 类模拟配置/密钥/媒体/输出路径被排除。忽略规则显式重新排除目录子项，防止反选父目录意外放行私有文件。
- 沿用本卡开始时已验证的 Python 版本，仅增加 Waitress 3.0.2。固定直接依赖、全部测试环境约束、运行/开发散列锁（36 / 40 个包）；没有顺手升级既有包。构建工具与 Debian 仓库未做完整快照，不宣称镜像逐字节可复现。
- CI 配置 Linux Python/JS 语法、pytest、真实 Chromium、镜像构建、上下文、Docker/Compose 临时卷集成，以及 Windows 硬链/软链/长路径/原子 JSON/进程锁探针；Actions 使用固定提交 SHA，失败日志上传。Windows 不满足能力时直接失败，不静默跳过。

## 改动文件（29 个）

修改 11 个：`.gitignore`、`Dockerfile`、`docker-compose.yml`、`main.py`、`web_app.py`、`web/app.py`、`web/task_state.py`、`requirements.txt`、`requirements-dev.txt`、`README.md`、`TESTING.md`。

新增 18 个：

- `.dockerignore`、`.env.example`、`.github/workflows/ci.yml`。
- `core/process_lock.py`、`server_runtime.py`。
- `constraints.txt`、`requirements.lock`、`requirements-dev.lock`。
- `tests/test_deployment.py`、`tests/support/deployment_probe.py`。
- `tools/check_syntax.py`、`tools/check_dependencies.py`、`tools/windows_smoke.py`、`tools/deployment_smoke.py`、`tools/compose_smoke.py`、`tools/build_context_smoke.py`。
- `DEPLOYMENT.md`、本说明。

## 测试与证据

先写首批 13 项隔离部署回归，修复前 **13 failed**（`/home/su/outputs/animeman-t15-red.txt`）。之后补真实 HTTP 双场景和 CLI 配置创建前加锁，共 15 项。Docker 上下文探针在最初规则下暴露 3 个私有子路径被放行（`animeman-t15-context-red.txt`）；修复后 10 个允许资源存在、18 类禁止路径全部排除。没有使用用户文件作为探针。自定义 UID 1026/GID 100 的真实构建在修复前报 `groupadd: GID 100 already exists`（`animeman-t15-custom-identity-red.txt`），随后以复用已有组的最小改动修复。

实际命令与结果：

```bash
uv venv /home/su/venvs/animeman-t15-locked --python /home/su/venvs/animeman-t00/bin/python
uv pip sync --python /home/su/venvs/animeman-t15-locked/bin/python --require-hashes requirements-dev.lock
uv pip check --python /home/su/venvs/animeman-t15-locked/bin/python
/home/su/venvs/animeman-t15-locked/bin/python tools/check_dependencies.py
/home/su/venvs/animeman-t15-locked/bin/python tools/check_syntax.py
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t15-locked/bin/python -m pytest -q --tb=short
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t15-locked/bin/python npm run test:ui
find static/js tests -name '*.js' -o -name '*.cjs' | xargs -n1 node --check
/tmp/animeman-t15-actionlint/actionlint .github/workflows/ci.yml
git diff --check
```

新建锁定环境安装与兼容检查通过；Python AST **98 文件通过**；完整 Python **691 passed**（676 + T15 的 15）；Node **38 passed**（31 Chromium + 7 VM），均无跳过；JS 语法、actionlint 1.7.7、差异检查通过。

Docker 为任务专用 rootless 28.5.2、Compose 2.40.3；未修改系统 Docker 服务/默认 context。首次本机 cgroup/systemd 授权失败有日志 `animeman-t15-docker-first-failure.txt`，调整任务守护进程的 cgroup 参数后实际构建成功；引擎报告 CgroupDriver=none，本次未验证资源限制。基础镜像公开拉取；本机代理只用于下载构建依赖，未将代理地址写入项目或最终镜像环境。使用 vfs、临时隔离 socket 与数据目录，不是 NAS 生产性能测试。

```bash
# 本机额外使用 DOCKER_BUILDKIT=0、--network host 与临时代理 build-arg；CI 用普通构建。
docker build -t animeman:t15 .
python tools/build_context_smoke.py
python tools/deployment_smoke.py --docker animeman:t15
python tools/compose_smoke.py animeman:t15
docker build --build-arg APP_UID=1026 --build-arg APP_GID=100 -t animeman:t15-custom .
python tools/compose_smoke.py animeman:t15-custom --uid 1026 --gid 100
```

实际全部通过：

- 镜像正常构建，安装包检查通过，最终镜像仅含允许的代码/资源，运行 UID 非 0；源码临时文件/私有配置不进入应用层。
- 真实 Waitress HTTP：健康检查、首页/静态资源、认证 401/200、密钥脱敏、单写任务 409、第二 OS 进程拒绝、配置更新持久化。
- 真实处理 runner、线程池、媒体事务与 JSON 提交；仅处理函数替换为测试桩，无 AI/TMDB 外联。两个临时合成 mkv 中第一个先提交，第二个等待取消。
- 正常 SIGTERM 安全退出 0；顽固测试线程超过 0.2 秒宽限后仍存活，报告超时，释放后退出 1。重复 SIGTERM 不自行强退。保留第一份记录与可读目标，第二份未提交，暂存目录清理。
- 删除旧容器、用同一临时 bind 重建新容器，配置 `max_workers=2` 与首个提交记录仍在；源只读、原字节散列一致。
- 原 Compose 文件叠加测试镜像，在实际生产 CMD 下达到 Docker healthy，实际默认 UID/GID 为 1000:1000，并实测自定义 1026:100（基础镜像 GID 已存在）、源只读，work 独立，StopTimeout 为 -1。

详细日志：`/home/su/outputs/animeman-t15-python.txt`、`animeman-t15-browser.txt`、`animeman-t15-docker-build.txt`、`animeman-t15-context-smoke.txt`、`animeman-t15-docker-smoke.txt`、`animeman-t15-compose-smoke.txt`、`animeman-t15-custom-build.txt`、`animeman-t15-custom-smoke.txt`。运行环境 Python 3.12.15、pytest 9.2.0、Node 26.13.1、Chromium 157.0.8103.38；Flask 3.1.3、requests 2.34.2、Pillow 13.0.0，其他精确版本见 constraints.txt。

## 未测项与边界

**未推送，因此远程 GitHub Actions 未运行；Windows 工作流仅完成配置与静态检查，尚无 Windows 实跑结果。** 未验证其他 CPU 架构、Python 版本、NAS/SMB/NFS、真实跨盘/真实字幕音视频、大媒体库压力、真实 TMDB/AI 服务、真实库升级或宿主断电。Linux 临时链接与已有事务/字幕回归通过，不能替代上述平台/真实环境验证。

锁只覆盖同一 CACHE_PATH 且使用标准入口的本地进程；不同缓存目录共享媒体库、绕过入口导入、外部工具修改不受其协调。宽限超时后的无上限等待是用户选择，运维必须能处理停机超时；更强的强退策略不能自行追加。健康检查不等于认证配置或业务 API 可用，依赖散列不等于安全审计结论。

## 兼容与回滚

T15 不迁移业务数据格式、删除媒体或覆盖旧缓存；只新增保留的 `.animeman-server.lock` 和默认可写 work 目录。现有数据升级先停任务并等待真实退出，备份配置、缓存与已有备份、版本号，再按 DEPLOYMENT.md/T04 迁移说明操作；没有对用户真实目录执行迁移、chown 或删除。

独立补丁 `/home/su/outputs/AnimeMan-T15.patch` **只相对 T14 完成状态**。停止服务、备份运行卷，先 `git apply --reverse --check`，再完整反向应用；保留 T00–T14，不要直接重置整个工作区。正反应用验证在隔离副本完成。旧入口恢复后将重新失去本卡的单进程锁和安全停机保证，旧 Compose 也恢复 root/旧停止策略；不能把代码回滚当作媒体/数据回滚。锁文件可保留，不要删活跃 inode 来解锁。

总补丁 `/home/su/outputs/AnimeMan-T00-T15.patch` 面向原始基线 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，不能叠加到已应用各卡的工作区。已在原始 Git 快照上校验正向应用与完整撤回；各任务的格式兼容/旧缓存备份约束仍须分别阅读。未发布镜像、未创建 Git 标签、未提交或推送。
