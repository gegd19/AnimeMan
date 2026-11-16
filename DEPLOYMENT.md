# 单进程部署与停机

## 支持范围

维护基线为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，依次应用 T00–T15。原 Docker 使用浮动 Python 3.11；本版统一到前序测试环境的 3.12.15，部署升级需同步更新运行时，未验证继续沿用 3.11。使用 Python 3.12、一个应用进程、多个 HTTP/处理线程；入口 `python web_app.py` 使用 Waitress 3.0.2，默认监听 `127.0.0.1:8000`，8 个 HTTP 线程。不要启动多个 WSGI worker、多个副本或滚动重叠运行。`WEB_CONCURRENCY` / `ANIMEMAN_WORKERS` 若不是 `1`，入口拒绝启动。

Web 与非预览 CLI 共用 `CACHE_PATH/.animeman-server.lock` 的操作系统独占锁，持锁直到写线程退出。退出后保留锁文件；不依据 PID 是否存在判断锁，不手工删除活跃锁文件。旧 PID 不影响正常重启。未知内容和符号链接锁文件会报错并保留原件。此锁保护使用入口且共享同一缓存目录的进程；它不能协调不同缓存目录指向同一目标库、绕过入口直接导入处理器、远程/NFS 锁语义或多个独立部署。显式迁移仍须停服务后执行。

`ANIMEMAN_THREADS=1..64`；`ANIMEMAN_PORT=0..65535`（0 用于隔离测试随机端口）；`ANIMEMAN_HOST` 指定监听地址。HTTP 线程数与配置中的 `max_workers` 是不同设置。反向代理应明确配置 HTTPS 和访问策略；当前入口不信任任意转发头。

## 源码安装

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip check
python web_app.py
```

`requirements.txt` 固定直接运行依赖，`constraints.txt` 记录本次测试环境的全部版本，两个 `.lock` 包含传递依赖与下载散列。除新增 Waitress 外没有升级既有 Python 包；Node 开发依赖继续使用 `npm ci`。更换 Python/平台/依赖时另做兼容验证，不静默重新解析最新版。

锁定版本与下载散列可复现依赖选择；这不是整个镜像的逐字节可复现承诺。Debian 软件仓库、源码包的构建工具及构建平台仍可能变化。Docker 基础镜像固定至 Python 3.12.15 的多平台 manifest digest，编译工具只留在 builder 阶段。

## 首次准备 Compose

1. 复制 `.env.example` 为 `.env`，设置实际用户的正整数 `PUID`/`PGID`（用 `id -u` / `id -g` 查看），设置绝对路径 `SOURCE_DIR` / `TV_DIR` / `MOVIE_DIR`，为 `SECRET_KEY` 生成私有随机值，例如 `python -c "import secrets; print(secrets.token_hex(32))"`。`.env` 已忽略，不提交；缺少密钥或路径时 Compose 直接报错。
2. 手动创建仓库下 `config`、`cache`、`logs`、`work` 目录和媒体目标目录，让指定 UID/GID 对这些目录有读写和遍历权限。源目录只需读取/遍历。不要为方便启动递归改变源媒体所有权或以 root 运行。rootless Docker 的容器 UID 映射与普通 Docker 不同，需按实际映射准备卷权限。Compose 禁止自动创建缺失的宿主 bind 路径。
3. 已有数据按 T04 备份/显式迁移，禁止用新配置覆盖旧配置。首次无数据安装可用下面脚本生成最小配置（密码交互输入，不写进命令历史）：

```bash
python - <<'PY'
import getpass, json
from pathlib import Path
p=Path('config/auto_config.json')
if p.exists():
    raise SystemExit('配置已存在，请保留并核对，禁止覆盖')
password=getpass.getpass('新管理员密码：')
if not password or password == 'admin':
    raise SystemExit('请设置非空、非默认密码')
config={'auth':{'enabled':True,'username':'admin','password':password},
        'source_folders':['/media/source'], 'tv_target_folder':'/media/tv',
        'movie_target_folder':'/media/movies'}
with p.open('x',encoding='utf-8') as f:
    json.dump(config,f,ensure_ascii=False,indent=2)
p.chmod(0o600)
PY
```

文件应属于设置的 UID/GID；使用不同服务用户时由管理员只调整运行目录权限。镜像创建用户时复用已有 GID，已实测 NAS 常用的 UID 1026/GID 100；不会因为基础镜像已有 users 组而失败。默认仅发布到宿主 `127.0.0.1:8000`。需要远程访问时先确认认证开启与网络访问方式，再修改 `BIND_IP`；健康检查公开且只返回存活状态，不代表业务配置可用。

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker inspect "$(docker compose ps -q animeman)" --format '{{.Config.User}} {{.Config.StopTimeout}}'
# 应为所设 UID:GID 以及 -1；否则先修正停止策略。
```

已验证 Docker 28.5.2 / Compose 2.40.3 接受 `stop_grace_period: -1s`（具体实际执行结果见 T15-NOTES）。其他引擎/Compose 版本应同样检查实际 `StopTimeout`；不要仅凭 YAML 解析通过判断。使用 `docker run` 时须显式添加 `--stop-timeout -1`，并按 Compose 配置所有路径、UID/GID 和只读源。

配置、缓存、日志、字幕工作目录分别为 `/app/config`、`/app/cache`、`/app/logs`、`/app/work`。源 bind 强制只读，TV/电影目标可写；`ANIMEMAN_WORK_PATH` 和 `TMPDIR` 指向独立可写 work 卷，不能指向源。修改 `SOURCE_FOLDERS` / `TV_TARGET_FOLDER` / `MOVIE_TARGET_FOLDER` 环境变量后需重启；这些路径在 Web 中只读。软链接的源路径也必须在最终使用媒体的容器中可见。

镜像构建只允许 Python 代码、前端资源和运行锁文件进入 context，并显式复制代码目录。不包含本地 `.env`、配置/缓存/日志、`.git`、测试、node_modules 或媒体。构建期不要额外复制私有文件到允许的源码/资源目录。

## SIGTERM 与宽限超时

收到 SIGTERM/SIGINT 后停止监听，锁定停机状态，设置任务取消事件，拒绝新写请求，等待处理线程和已有 HTTP 线程退出。重复信号或 Web 的重置不能清除停机锁。已通过原子提交完成的处理记录保留，尚未提交的事务按原取消逻辑清理；不会伪造成功记录。

`ANIMEMAN_SHUTDOWN_GRACE` 默认 30 秒，允许 0.01–3600 秒。**按本次用户明确选择，宽限到期仅报告，不强退**：记录 `shutdown_timeout:`，状态中设置 `shutdown_timed_out=true`，继续等线程安全退出，最后以退出码 1 表示发生过超时；正常排空退出码 0。监听已关闭，不能依赖新 HTTP 请求读取这个状态，应监控标准输出/日志。超时等待没有另一个强杀期限，卡住的线程可能使停机一直等待。

Compose 的 `stop_grace_period: -1s` 防止引擎在此等待过程中改发 SIGKILL。使用 `docker compose stop` 或 `docker stop --timeout -1 <container>`；不要传入另一个有限 `-t` 覆盖它。自动运维、宿主关机、容器编排器也须尊重这个选择。外部 SIGKILL、崩溃、断电及存储故障不在该保证内；未据此宣称任何情况下零数据丢失。

Waitress 的线程/连接行为见 [官方参数文档](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html)；Docker 无限等待语义见 [docker stop](https://docs.docker.com/reference/cli/docker/container/stop/)。

## 升级、验证与回滚

停止写任务并等待容器真正退出，再备份配置、完整缓存目录（包括旧格式备份）、版本号和必要日志。保持源只读，用临时样本库运行预览与验证，之后再评估真实库。重建容器保留四个运行卷及目标目录，不执行 `down -v` 或删除目录来解决启动失败。

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python tools/check_dependencies.py
python tools/check_syntax.py
python -m pytest -q --tb=short
npm ci --ignore-scripts
npx playwright install chromium
ANIMEMAN_TEST_PYTHON=python npm run test:ui
python tools/deployment_smoke.py
docker build -t animeman:verification .
python tools/build_context_smoke.py
python tools/deployment_smoke.py --docker animeman:verification
python tools/compose_smoke.py animeman:verification
# Windows runner（启用开发者模式与长路径后）：python tools/windows_smoke.py
```

所有部署探针创建临时合成小文件、虚拟凭据与独立卷，禁止外部 AI/TMDB 请求；Docker 探针只删除自己创建的容器和临时数据。失败会输出服务日志，不以跳过代替通过。不要把真实媒体/配置目录传给探针。

T15 不改业务缓存信封或迁移媒体。撤销 T15 前必须停服务、备份现状，再完整撤回 T15 独立补丁，保留 T00–T14。旧 Flask 入口恢复后没有本卡进程锁/停机保证；旧 Compose 的 root 身份和有限停机策略也会恢复，不宜直接用于真实库。锁文件可保留；仅确认没有活跃进程时才可以归档。业务缓存兼容仍受 T07/T14 等任务约束，不能只换旧代码而忽略已有格式。Windows 和远程 GitHub CI 的实际执行状态须查看交付说明，配置了工作流不等于执行通过。
