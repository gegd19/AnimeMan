# 界面美化说明（ui/visual-refresh）

基线：`v1.0.0` / `7581e03d30221160cc6648d3261b79a10c2ddc54`。本次只改前端呈现；没有推送、没有发布、没有移动 `v1.0.0` 标签。

> 第 1–7 节保留原作者交付时的记录；其中未推送、环境差异和未测状态属于当时状态。锁定环境复核和发布准备见第 8 节。

## 1. 设计方向：「作画台」

风格来自动画制作本身：定位纸、透写台、彩色铅笔。

| 元素 | 取值 | 用途 |
| --- | --- | --- |
| 台面 | `#E8EFF3` | 页面底色，带一点蓝的浅灰 |
| 纸张 | `#FFFFFF` | 内容区；平放，只用 1px 细线，不加阴影 |
| 石墨 | `#1B222B` / `#4E5967` | 正文与次要文字 |
| 蓝铅 | `#1769AA` | 可操作、选中、进行中 |
| 朱铅 | `#B93127` | 只用于破坏性操作和失败 |
| 定位孔蓝 | `#A4DDED` | 仅装饰：缺图占位里的三个定位孔 |

- **任务条是唯一的"招牌"**：进度条画成律表（timesheet）刻度尺，在所有页面顶部常驻；其余部分保持安静。
- 阴影只给浮起来的东西（弹窗、提示、气泡）。圆角 4px（纸张、输入框）和 8px（浮层）两级。
- 去掉了界面里的装饰性 emoji，图标改为内嵌在 CSS 里的线条 SVG；状态一律有文字（启用/停用、存在/缺失、成功/失败），不单靠颜色或符号。
- 只用系统字体和 data URI，没有新增任何外部资源、依赖或构建步骤。
- 深色主题与浅色共用同一套变量；默认跟随系统，可在「设置 → 外观」或侧栏底部切换。

正文对比度（浅色/深色）最低 4.53:1，按 `static/style.css` 中的变量计算。

## 2. 信息组织

原来所有功能平铺在一个长页面里（手机上约 12000px 高）。现在分为五个页面，任务状态独立出来常驻：

| 位置 | 内容 |
| --- | --- |
| 任务条（始终可见） | 状态文字、进度、开始/停止、模拟运行标记 |
| 工作台 | 首次引导、任务日志、本次运行、失败缓存 / 已处理缓存入口 |
| 媒体库 | 电影 / 剧集、季集展开、过滤排序、批量修正与删除 |
| 字幕 | 扫描与自动匹配、强制匹配、AI 匹配、结果表 |
| 工具 | 特辑映射规则、离线 AI 预解析、AI 简介润色测试 |
| 设置 | 路径、处理方式、TMDB、识别与 AI、字幕、访问认证、外观，底部固定「保存配置」 |

桌面端是左侧栏，900px 以下变成底部标签栏（同一份 DOM）。所有页面始终渲染在 DOM 里，导航只切换 `hidden`，所以表单值、勾选和任务状态在切换时不会丢；弹窗移到页面外层，不会被隐藏的页面遮住。地址栏带 `#library` 这类锚点，刷新后停留在原页面。

## 3. 有变化的交互

| 变化 | 说明 |
| --- | --- |
| 导航 | 新增；见上。「快速配置」改为跳到「设置」页 |
| 纯通知类 `alert()` → Toast | 例如"已设置路径""关键词不能为空"。**所有 `confirm()` 确认框原样保留** |
| Toast | 改为 CSS 类；错误/警告默认停留 6 秒并带 `role="alert"`，点击可关闭 |
| 清空日志 | 以前清空后 1 秒就被下一次轮询填回；现在只清空本页显示，之后只出现新日志。完整日志不受影响 |
| 日志滚动 | 日志无变化时不重建节点；只有原本停在底部时才自动跟随 |
| 弹窗 | 有名称（`role="dialog"` + `aria-labelledby`）、打开时焦点进入、Tab 在弹窗内循环、Escape 关闭最上层、关闭后焦点回到触发按钮；关闭按钮是真正的 `<button>` |
| 键盘 | 目录行、选择器里的剧集/季标题、季展开、集标题现在可以用键盘操作；TMDB 搜索框回车即搜索 |
| 展开季列表 | 展开后滚动到季面板（面板仍追加在网格之后） |
| 集详情气泡 | 位置限制在视口内 |
| 空媒体库 | 显示下一步提示，而不是两块空白 |
| 手机 | 已处理缓存表和字幕结果表改为逐条卡片；弹窗全屏；触屏下控件高度 44px |
| viewport | 去掉了 `maximum-scale=1.0`，不再限制缩放 |

## 4. 没有改变的东西

- 没有修改 `core/`、`web/`、缓存格式、依赖、锁文件、`.dockerignore`、Dockerfile、CI。
- 接口请求和请求体不变：密钥留空保留 / `clear_secrets` 显式清除、`environment_managed` 只读、`/api/stop?task_id=…`（从不发送 `force=1`）、`delete_source:false`、原始路径与缓存键、`dry_run` 文案、人工确认 / 未评分、`/media_poster/<type>/<id>`。
- 既有 `id`、表单值、`data-*`、`App.*` 公共方法全部保留。用脚本比对了 v1.0.0 与现在渲染出的首页：原有 id 一个不少、没有重复 id；内联事件只少了一个，即「媒体详情」弹窗关闭按钮上的 `App.MediaManager.closeDetailModal()`——这个函数在 v1.0.0 里并不存在（该弹窗也没有任何代码会打开），现在由 `shell.js` 的通用关闭处理代替。
- 任务状态与按钮禁用逻辑不变。`task.js` / `config.js` 只增加了两个可选的展示回调（`App.onTaskStatus`、`App.onConfigLoaded`），由 `shell.js` 用来更新任务条；它们不发请求、不改状态。
- `history.js` 仍是未接入首页的兼容模块；`partials/partials.html` 仍未被引用，均未处理。
- `App.init()` 与 `scripts.html` 里对 `App.MediaManager.init()` 的两次调用保持原样，没有新增重复请求、事件或轮询。`App.Shell.init()` 可重复调用且不发请求。
- localStorage 只新增 `animeman.theme`；不保存配置、路径或密钥。

## 5. 改动文件

- `static/style.css`：整体重写为变量化的样式系统。
- `static/js/shell.js`（新）：导航、主题、弹窗键盘与焦点、任务条展示同步。
- `static/js/*.js`：把内联颜色/emoji 换成 CSS 类和文字；通知类 alert 改 Toast；上表列出的小交互。
- `templates/index.html`、`templates/partials/*.html`、`templates/partials/modals/*.html`：新骨架与语义化标记；`templates/partials/nav.html`（新）。
- `tests/shell_ui.cjs`（新，16 项）、`tests/ui_preview.cjs`（新，截图工具，不属于测试）、`tests/frontend_security.cjs`（+14 行）、`package.json`（把 `shell_ui.cjs` 加入 `test:ui`）。

新增文件都落在 `.dockerignore` 现有白名单内（`static/js/*.js`、`templates/partials/*.html`），后缀仍只有 `.py/.html/.js/.css`，所以打包规则和烟测脚本不需要改。

### 测试适配

`tests/frontend_security.cjs` 只加了一个 `openView()` 辅助函数和 8 处调用：在操作媒体库、字幕、工具页里的控件之前，先真实点击导航并等待页面可见。**没有删除、放宽或跳过任何原有断言**，也没有使用强制点击或直接改可见性。

## 6. 验证

环境：Node 22.23.4、Playwright 1.63.0、Chrome for Testing 153.0.8010.12、Python 3.13.18。**不是**文档锁定的 Python 3.12.15 / Node 26.13.1 / Playwright 1.62.1，且本环境无法安装依赖。

```bash
find static/js tests -name '*.js' -o -name '*.cjs' | xargs -n1 node --check     # 通过
python tools/check_syntax.py                                                    # 98 files PASS
PLAYWRIGHT_MODULE=… CHROMIUM_PATH=… npm run test:ui                              # 54 通过，0 失败，0 跳过
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q --tb=short                         # 685 通过，6 失败（见下）
git diff --check                                                                 # 干净
node tests/ui_preview.cjs <目录>                                                 # 47 张截图；无整页横向溢出，无意外控制台错误
```

- 另用 Flask 测试客户端在临时空配置目录下请求了真实应用：`GET /` 返回 200，页面引用的 `style.css` 和 15 个脚本（含新增的 `shell.js`）全部 200。
- Node：原有 38 项（31 浏览器 + 7 VM）全部通过，新增 16 项浏览器用例。
- Python 的 6 项失败在未改动的基线上同样失败，原因是本环境缺少 `anitopy` 和 `waitress`（`test_parser` ×3、`test_season_scan` ×1、`test_deployment` ×2），与界面无关。**需要在锁定环境里重跑才能确认 691 项全绿。**

### 未测

| 项目 | 原因 | 后续命令 |
| --- | --- | --- |
| 锁定环境下的完整 Python 回归 | 无法安装 `requirements-dev.lock` | `python -m pytest -q --tb=short` |
| `tools/check_dependencies.py` | 同上 | `python tools/check_dependencies.py` |
| Docker 构建与三个烟测 | 本机没有运行中的 Docker 守护进程 | `docker build -t animeman:ui-review . && python tools/build_context_smoke.py && python tools/deployment_smoke.py --docker animeman:ui-review && python tools/compose_smoke.py animeman:ui-review` |
| GitHub Actions（Linux / 容器 / Windows） | 未推送 | 推送分支后由 CI 执行 |
| 真实设备：iOS Safari、Android Chrome、Firefox | 只在桌面 Chromium 中用视口和触屏模拟验证 | 手动检查 |
| 读屏软件 | 只验证了语义和焦点行为，没有用 VoiceOver / NVDA 实际朗读 | 手动检查 |
| 真实后端联调 | 按交接要求，全部使用 mock API 和合成数据 | 在隔离的测试配置上手动走一遍 |

截图全部来自 `tests/ui_preview.cjs` 的合成数据（虚构片名、SVG 假海报、`*.invalid` 地址），没有真实密钥、路径或媒体。

## 7. 回滚

撤回本次提交即可，不需要迁移或清理：

```bash
git revert <本次提交>        # 或直接不合并 ui/visual-refresh 分支
```

回滚只影响 `static/`、`templates/`、`tests/`、`package.json` 和本说明文件；不涉及缓存、配置和运行目录，不触碰任何媒体。浏览器里残留的 `animeman.theme` 对旧界面没有影响。不要对已有工作区使用 `reset --hard` 或 `clean -fdx`。


## 8. 发布前复核（v1.1.0）

原补丁已在独立工作副本、v1.0.0 基线上应用，并保留作者署名单独提交；没有改动 core/、web/、依赖锁、Dockerfile、打包规则或 CI 配置。

### 发现并修复的提示问题

原任务条“模拟运行”徽标及“本次运行 → 运行方式”读取最新 `/api/config`，但正在执行的任务使用启动时的冻结配置。正式任务运行中保存模拟配置，会让页面错误暗示该任务已经不再写文件。

先增加真实浏览器回归，验证在任务仍运行时保存 dry_run；原实现因仍显示“模拟运行”而失败。最小修复仅调整展示：徽标改为“已保存：模拟”，任务概览字段改为“已保存配置”，并说明正在执行的任务仍使用启动时配置。没有猜测当前任务模式，也没有改变后台任务配置。

375px 回归进一步发现徽标会挤压状态文字，已允许任务状态区域换行，确保“运行中”仍完整可见。新增用例同时断言任务仍忙、启动按钮禁用、保存配置没有发起运行或停止请求。

### 锁定环境与检查

- Python 3.12.15、Node 26.13.1、Playwright 1.62.1、Chromium 157.0.8103.38。
- 完整 Python 691 项通过；前端 55 项通过（原有 38 + 原补丁 16 + 审查追加 1），无跳过。
- 实际 Jinja 渲染比对原有 DOM ID；核对敏感请求体、只读路径、确认操作、类型海报与安全文本渲染。
- 生成并人工抽查桌面/手机、浅色/深色和弹窗截图；47 个合成场景无整页横向溢出、无意外控制台错误。手机与桌面的部分表格使用局部滚动，不据此宣称全设备可访问性认证。
- 生产镜像构建、构建上下文排除、Docker 双停机场景、Compose 非 root/只读源/无限停机等待检查均执行；具体结果以本次发布提交的 CI 和随附复核报告为准。
- 首次交付时的 6 个 Python 失败在完整锁定环境中没有复现。

```bash
npm ci --ignore-scripts
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t15-locked/bin/python -m pytest -q --tb=short
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t15-locked/bin/python npm run test:ui
python tools/check_dependencies.py
python tools/check_syntax.py
find static/js tests -name '*.js' -o -name '*.cjs' | xargs -n1 node --check
git diff --check
```

Python/Node 的实际安装和锁文件依照项目既有要求，以上绝对路径仅记录本机环境。全部媒体与 API 数据仍为临时合成或 mock；没有使用真实密钥/媒体，也没有执行真实库迁移。iOS Safari、Android 实机、Firefox、读屏软件及真实 NAS 环境仍未验证。

发布使用新版本 v1.1.0，保留 v1.0.0 标签。撤回时完整回退 v1.0.0 到 v1.1.0 的全部 UI 提交（原补丁与审查修复分别提交），保留业务数据和运行卷；浏览器主题偏好可保留，不需要清空配置或缓存。
