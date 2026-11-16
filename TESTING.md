# 隔离测试（T00）

本次任务只建立测试入口和应用配置注入，不包含 T01–T15 的业务修复。

## 安装与运行

前端回归需要已安装包含 `node:test` 的 Node；测试用内置 VM 和假 DOM/fetch，无 npm 依赖。

在项目根目录使用独立虚拟环境；不要在正在处理媒体的进程里运行 pytest。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --collect-only -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Windows 激活虚拟环境后使用 `python -m pytest`，设置 `PYTHONDONTWRITEBYTECODE=1` 可以避免源码旁生成 Python 字节码。pytest 的缓存插件默认已禁用。

## 隔离机制

- `testpaths=tests` 只收集正式测试。原 `core/test_parser.py` 的三个罗马数字季号演示已迁移到 `tests/test_parser.py`，现在断言媒体类型、季号与集号。
- `tests/conftest.py` 在 **收集测试之前** 切换到会话临时目录，防止导入业务模块时在仓库或用户目录读取缓存、创建日志；结束时关闭应用日志句柄并清理会话目录。单个测试另外通过 `tmp_path` 隔离工作目录。
- 测试覆盖配置、缓存和日志环境变量，并清除常见外部密钥环境变量；配置 fixture 只包含假凭据，源目录列表为空，目标位于临时目录。T04 已接通运行路径环境变量：收集前采用会话隔离，每个用例另外设置 CONFIG_PATH、CACHE_PATH、LOG_PATH 并重新绑定应用日志，避免测试间共用数据。
- 整个测试会话默认阻断 Requests 请求与 socket 连接。需要验证网络分支时，在测试内 monkeypatch 对应客户端返回本地假响应，不解除真实网络限制。
- 网络阻断针对当前 Requests/socket 调用，不是操作系统沙箱；后续测试若涉及外部命令，应 mock subprocess，避免子进程绕过隔离。需要线程时使用可控假线程或同步原语，并在 teardown 等待/清理线程和状态。
- 当前部分模块仍含全局内存缓存；后续修改这些状态的测试必须用 monkeypatch 或 fixture 还原状态。T00 不重构全部缓存生命周期。

## 应用工厂

```python
from web import create_app

app = create_app(config_path="/absolute/path/to/test-config.json")
app.config["TESTING"] = True
client = app.test_client()
```

`config_path` 接受字符串或 Path；显式相对路径在工厂创建时转换为绝对路径。路由在注册时捕获同一配置路径，所以后台线程不依赖 Flask 请求上下文。认证按当前 app 使用该路径；同进程两个 app 可以使用不同配置文件。

不传参数的 `create_app()` 保持原有 `auto_config.json` 工作目录默认行为。请在创建 app 时指定路径，不要在注册路由后修改 `app.config['CONFIG_PATH']`。这项注入只隔离配置文件；缓存、任务状态和海报缓存仍是已有的进程级实现，不能据此在生产中承诺多个独立实例共用同一进程。

## T00 验证记录

- 基线：`f0feb4667f1cf7349e3c60fc85cea6709c895ab7`。
- 本地分支：`maintenance/t00-test-foundation`；未提交、未推送、未发布。
- 环境：Linux，CPython 3.12.15，pytest 9.2.0，Flask 3.1.3，requests 2.34.2，anitopy 2.1.1。完整运行依赖和测试依赖安装在 `/home/su/venvs/animeman-t00`，未更改系统 Python 环境。
- 修复前：12 项中 7 passed、1 failed、4 errors；失败原因均为工厂缺少 `config_path` 参数，明确暴露无法注入隔离配置的问题。
- 修复后增加“收集期日志隔离”和“相对配置路径跨 cwd 保持”两项：`python -m pytest -q` 为 **14 passed**；`--collect-only -q` 为 **14 tests collected**。`git diff --check`、Python AST 语法检查、`uv pip check` 均通过；检查仓库根目录无运行时 JSON、日志或临时文件。
- 覆盖：显式配置读取/保存、认证配置一致性、映射路由、两个 app 的配置独立性、请求结束后后台任务配置传递、默认工厂兼容、相对路径稳定、解析样例、配置/缓存写入位置、收集期日志位置、网络阻断与 mock 响应。
- 未执行：Docker、Windows、真实媒体整理、真实 ffmpeg/字幕调轴、真实 AI/TMDB 请求、其他任务卡的缺陷测试。

## 改动文件清单

- 新增：`pytest.ini`、`requirements-dev.txt`、`TESTING.md`。
- 新增测试：`tests/conftest.py`、`tests/test_app_config.py`、`tests/test_parser.py`、`tests/test_isolation.py`。
- 修改工厂与认证路径：`web/app.py`、`web/auth.py`。
- 修改路由配置路径捕获：`web/routes_browse.py`、`web/routes_cache.py`、`web/routes_config.py`、`web/routes_failed.py`、`web/routes_mapping.py`、`web/routes_offline.py`、`web/routes_subtitle.py`、`web/routes_task.py`。
- 删除已迁移的打印演示：`core/test_parser.py`。

## 兼容与回滚

没有迁移配置或缓存格式，没有操作用户媒体。可通过回退本次差异恢复原工厂、路由、认证配置路径读取方式及旧解析演示；新增的 pytest 配置、测试目录、开发依赖和本说明也可一并撤销。虚拟环境是独立目录，可单独移除。业务安全缺陷仍应按计划书继续修复，T00 的测试通过不代表后续任务已完成。

## 前端浏览器回归（T12）

前端开发依赖独立记录在 `package.json` 与 `package-lock.json`，不进入 Python 运行依赖。使用能导入 Jinja2 的 Python 和 Node，在仓库根目录运行：

```bash
npm ci --ignore-scripts
npx playwright install chromium
ANIMEMAN_TEST_PYTHON=/absolute/path/to/venv/bin/python npm run test:ui
```

已有兼容的 Chromium 时可以通过 `CHROMIUM_PATH=/absolute/path/to/chromium` 指定，无需再次下载浏览器。默认 Python 为 python3；若复用外部 Playwright 安装，可设置 `PLAYWRIGHT_MODULE` 为该模块路径。没有可用浏览器或依赖时测试直接失败，不静默跳过。

`npm run test:ui` 执行原有 7 项 Node VM 回归和新增 30 项真实 Chromium 回归。浏览器测试通过 Jinja2 渲染真实模板、加载真实页面脚本，所有页面请求均先拦截；API 用 mock 响应，非测试源请求中止。删除、重试、修正仅核对请求体，不启动后端服务、不访问真实媒体/密钥、不调用真实 AI/TMDB。首页未使用的遗留 history.js 单独创建真实 DOM 控件并加载测试，没有为此新增产品页面。

新增用例覆盖特殊路径和 HTML 实体原值传递、动态文本/属性注入、勾选与批量删除、单/批量修正、媒体季与单集、字幕目标、映射保存、目录浏览、分页、日志弹窗，以及 401/409/500、非 JSON 错误页和网络异常。页面级请求拦截不是操作系统网络沙箱；Firefox、WebKit、移动端、真实服务端和部署环境仍需另外集成验证。

## 输入与配置回归（T13）

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short tests/test_input_validation.py
```

新增 206 项，最终完整 Python 638 项通过；Node 37 项通过。覆盖请求体/查询参数类型与范围、重复字段、布尔与数值边界、整批预检、配置默认值独立性、损坏配置拒绝/备份、原子保存失败与并发补丁、环境覆盖保护、提示词格式和悬空配置链接。媒体与配置只在临时目录，AI/TMDB mock；没有跳过既有断言。详细限制、错误状态和恢复说明见 T13-NOTES.md。

## 派生缓存与类型身份回归（T14）

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short tests/test_derived_cache.py
```

新增 38 项 Python 与 1 项真实浏览器回归，完整 Python 676、Node 38 项通过。覆盖电影/TV 同 ID 海报、旧地址歧义、明确删除与离线目标、修正后的来源版本、旧帧备份、失败/取消完整发布、预览无写入、跨类型缓存路径、命名空间、图片格式及并发快照。所有视频/图片都为临时假数据，浏览器后端请求全部 mock，无真实媒体/密钥/API。兼容与回滚见 T14-NOTES.md。

## 部署与最终验证（T15）

新增 15 项部署回归：参数拒绝、独占进程锁、未知文件/符号链接保护、CLI 配置创建前加锁、停机闩锁、超时继续等待，以及真实 HTTP 的取消/持久化/重启。完整 Python **691 passed**，Node **38 passed**，均无跳过。锁定环境 Python 3.12.15、pytest 9.2.0、Waitress 3.0.2；完整版本见 constraints.txt 与散列锁文件。

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python tools/check_dependencies.py
python tools/check_syntax.py
python -m pytest -q --tb=short
python tools/deployment_smoke.py
# 已构建镜像后，必须实际运行这些 Docker 检查；无 Docker 时直接报错。
python tools/build_context_smoke.py
python tools/deployment_smoke.py --docker animeman:verification
python tools/compose_smoke.py animeman:verification
```

本机实际通过 Docker 28.5.2 rootless 的镜像构建、18 类上下文排除、两种写任务 SIGTERM 场景和 Compose 2.40.3 生产入口。检查认证、健康状态、单任务/单进程互斥、容器删除重建持久化、源只读及内容保留、已提交产物保留、未提交产物清理、实际 StopTimeout=-1；另实测自定义 UID 1026/GID 100 的构建与 Compose 启动，覆盖基础镜像组冲突。宽限超时按用户明确选择报告并继续等待，最终安全退出码为 1。

`.github/workflows/ci.yml` 包含 Linux Python/JS/浏览器、Docker/Compose 和 Windows 链接/长路径探针；actionlint 1.7.7 静态校验通过。**未推送，远程 GitHub Actions 未执行；本机无 Windows，Windows 探针尚未执行**。没有将 CI 配置完成写成 CI 实跑成功。部署、权限和停机细则见 DEPLOYMENT.md；证据与回滚见 T15-NOTES.md。
