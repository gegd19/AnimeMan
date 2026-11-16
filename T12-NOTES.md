# T12：前端安全渲染与路径传递

## 范围与基线

基线仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`，本卡相对 T11 完成状态实施。执行前核对当前 git 状态、计划书、真实函数、模板加载顺序；仓库与祖先目录没有 AGENTS.md。保留 T00–T11 未提交修改，没有提交、推送、发布或操作真实用户媒体。

T11 后问题仍存在：历史/已处理缓存/失败缓存路径拼入内联事件代码，TMDB 搜索按钮把标题拼进 JavaScript，媒体卡片与剧集详情存在未受保护的属性或文本，字幕目标标题写入 innerHTML。AI 流式错误文本已在前面任务中改成 textContent，本卡保留该保护并补测；没有重复声称修复已经解决的问题。

仅处理 T12 及浏览器验证所需开发依赖。没有修改 Python 后端、模板、配置/缓存格式、删除策略或后续任务卡。静态可信模板与模板中只传常量的操作入口保留。

## 修复行为

1. `app.js` 提供 DOM 节点、文本、按钮、图片、表格提示、分页和 TMDB 结果构建方法。动态文本使用 textContent，标题、图片 src、输入状态和 dataset 使用 DOM 属性；动态事件通过 addEventListener 或已有事件委托处理，参数使用闭包或 DOM dataset。没有新增第二套字符串转义来继续拼接事件代码。原 escapeHtml 导出保留兼容，但动态业务渲染已不再依赖它。
2. 历史记录、已处理缓存、失败聚类/列表/文件夹详情、单/批量 TMDB 搜索、映射规则、媒体选择弹窗、媒体卡片/季面板/单集详情、字幕展示与分页全部移除动态内联事件和不可信 HTML 拼接。目录浏览、离线计数和日志弹窗也采用文本/属性构建。图片加载失败通过监听器隐藏图片。
3. 路径、文件名、标题和对象保持原始值，不先 HTML 转义再传给业务函数。包含单双引号、反斜杠、中文、`&`、`< >` 或类似 `&quot;` 的字符串不会变成额外节点、事件代码或被实体解码改变。媒体选择器把 JSON 字符串通过 dataset 属性赋值，再由原事件委托读取；不拼入 HTML 属性。
4. 所有页面脚本请求接入 `App.fetch`，保留 fetch 的 options、AbortSignal 和原 Response，兼容 JSON 和流式读取。先检查 HTTP 状态再进入业务成功分支：401 提示重新认证，403 提示权限，409 提示操作冲突，500 等服务端错误给出可读提示；JSON message/error 作为文本显示，非 JSON 错误页不被当作 HTML 展示。网络异常提示后继续抛出；主动取消保留 AbortError。没有自动重试写操作。
5. 保留目录向上浏览遇到 403 时回到允许根目录的行为；统一请求检查后新增独立回归，验证该分支不会被抛出的 HTTP 错误截断。
6. 真实首页当前未加载 history.js，相关 DOM 控件也不存在。本卡没有借机新增历史页面；浏览器测试为这个遗留模块单独构建真实 DOM 控件并加载真实脚本。其他测试使用仓库真实 Jinja 模板与加载顺序。

## 改动文件（25 个）

- `static/js/app.js`：DOM 构建、事件、安全错误处理与共享请求检查。
- `static/js/history.js`、`processedCache.js`、`failedCache.js`：记录/缓存安全展示，选择、重试、修正和删除参数原值传递。
- `static/js/correction.js`、`batchCorrection.js`、`mappingRules.js`：安全搜索结果、文件列表和规则操作。
- `static/js/mediaLibrary.js`、`mediaManager.js`：安全媒体对象、卡片、季集展开和详情弹窗。
- `static/js/subtitleCenter.js`：安全字幕标签、目标显示、分页和执行事件。
- `static/js/browse.js`、`offlinePreparser.js`、`task.js`、`config.js`、`aiStream.js`：统一请求检查，相关动态内容/日志渲染。
- `tests/frontend_security.cjs`：新增 30 项真实 Chromium 回归。
- `tests/config_ui.cjs`、`task_ui.cjs`、`confidence_ui.cjs`：加载真实 app.js 依赖，补充 DOM 测试适配，保留原有断言。Toast 收集仍由测试桩负责；HTTP 与注入安全由真实浏览器验证。
- `package.json`、`package-lock.json`：仅开发测试依赖 Playwright 1.62.1，新增 test:ui 命令；`.gitignore` 忽略 node_modules。
- `README.md`、`TESTING.md`、本说明：契约、验证和恢复说明。

## 验证证据

先写首批 15 项浏览器回归，修复前 **14 failed、1 passed**，已有流式错误文本保护保持通过。随后补充批量选择/修正/删除、目录浏览、映射保存、字幕已处理/强制目标、非 JSON/网络错误、流式状态码、离线计数、分页、日志弹窗和 403 兼容回归。测试适配纠正了隐藏弹窗、首页未加载遗留模块和重复缓存键等夹具问题，没有跳过或削弱断言。

最终 30 项浏览器测试在隔离的 T11 完成代码副本上运行，结果为 **25 failed、5 passed**（`/home/su/outputs/animeman-t12-baseline.txt`）；修复后 **30 passed**。未修改真实工作区去重现旧缺陷。通过项保留已有流式文本、目录原值传递、原有季选择、日志转义及 403 返回根目录行为。

最终完整 Python **432 passed**，Node **37 passed**（原有 7 + 新增浏览器 30），没有跳过。所有媒体路径仅为 mock 数据字符串，所有页面 API 全部拦截，不启动后端、不进行真实删除/修正、不使用真实密钥或 AI/TMDB。Python 套件继续使用临时目录和 Requests/socket 阻断。

本机验证命令：

```bash
npm ci --ignore-scripts
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t00/bin/python npm run test:ui
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T12.patch
```

通用安装/浏览器运行方式见 TESTING.md。实际环境：Linux、Python 3.12.15、Node 26.13.1、Playwright 1.62.1、Chromium 157.0.8103.38。所有 JS 语法、Python AST 和差异检查通过。独立补丁在隔离副本正向应用及反向撤回后，涉及文件逐字节恢复至 T11 完成状态。仓库根目录没有生成运行配置、缓存、日志或用户媒体；package.json/package-lock.json 是本次开发依赖清单，不是运行缓存。

## 未测项

未测 Firefox/WebKit、Windows、移动端、真实 NAS/Docker、实际 AI/TMDB、浏览器与真实后端联调、真实 Basic Auth 重新登录交互或生产规模媒体库性能。浏览器测试使用 mock 401 响应验证提示和成功分支阻断，不代表真实浏览器认证凭据缓存已做端到端验证。

只修复本卡覆盖的渲染与请求状态边界，不据此宣称整个应用不存在 XSS 或已经完成 T13 的服务端输入/配置校验。保留静态可信 HTML/模板常量事件，不新增 CSP 或整体前端框架迁移。没有修改字幕批量业务流程、后端清理规则或历史缓存迁移逻辑。

## 兼容与回滚

保留现有 App 模块导出、后端 URL、请求体字段、选择数据格式及页面主要结构。新 DOM 方法和 App.fetch 位于 app.js，业务脚本必须在 app.js 后加载，当前模板顺序满足；单独嵌入业务模块的外部代码需要同样加载 app.js。失败 HTTP 状态现在抛出带 status 的错误，即使错误响应 JSON 伪装成 status=success，也不会报告成功。JSON 200 中的业务错误仍由调用者按既有契约处理。

新增 Node/Playwright 依赖只用于开发测试，不改变 Python 运行依赖、不需要在生产容器执行 npm。没有更改配置或缓存结构，无需迁移、备份或恢复旧缓存。

独立补丁 `/home/su/outputs/AnimeMan-T12.patch` 相对 T11 完成状态生成。停止写任务后先执行反向检查，再按需整卡反向应用；不要只回退 app.js 或只回退调用方，以免混用新旧接口。更新/回滚后强制刷新页面。不要恢复整个仓库，否则会丢失 T00–T11 未提交成果；继续回滚旧卡需按 T12 → T11 → T10 逆序处理。代码回滚不删除/回滚用户媒体和运行缓存；开发 node_modules 即使保留也不参与 Python 运行。
