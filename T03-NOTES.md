# T03：认证、密钥脱敏与目录访问边界

## 本卡结果

基线提交为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，本卡在未提交的 T00/T01/T02 之上继续修改，沿用 `maintenance/t00-test-foundation`。没有提交、推送或发布，没有使用真实密钥或媒体。

认证只有一处策略：全局钩子和原有 require_auth 装饰器共用 enforce_auth。关闭认证时无需 Authorization；开启认证时首页、配置、日志、状态、目录浏览、海报和业务 API 均需要正确的 HTTP Basic 凭据。公开端点仅为精确的 healthz 与 Flask static 端点，前缀相似的业务 URL 不再被放行。用户名/密码支持 UTF-8，并使用恒定时间比较。

新增公开 `GET /healthz`，只返回 `{"status":"ok"}`，请求期间不加载业务配置。Dockerfile 与 Compose 健康检查均改用该地址。非静态响应增加 `Cache-Control: no-store`。

认证边界严格检查现有配置 JSON 及认证字段：损坏、类型错误或开启认证但缺少有效凭据时拒绝业务访问，返回 503；健康检查仍可用。这是认证边界的失败保护，未代替 T13 对其他配置的完整校验。

## 密钥 API 契约与前端

配置 GET 递归清空 api_key/password 值，附带 api_key_configured/password_configured 布尔状态；已知占位默认密钥不算已配置。即使已认证也不回传明文密钥。

配置 POST 的省略字段或空字符串表示保留已有密钥；非空字符串表示设置新值。清除必须使用显式的 clear_secrets 列表，例如：

```json
{"clear_secrets": ["tmdb_api.api_key"]}
```

支持 `tmdb_api.api_key`、`ai_parser.api_key`、`ai_plot_enhance.api_key`、`auth.password`。不能同时设置与清除同一密钥；清除 AI Key 同时关闭对应 AI 功能；清除登录密码时必须同时关闭认证。未知清除字段、非法认证类型、会导致空凭据认证的配置都在保存前拒绝。客户端提交的 *_configured 展示字段不会写入配置。

前端密码框保持为空，用 placeholder 显示“已配置，留空保留”。AI 启用检查使用配置状态标志，不再因看不到密钥而自动关闭已配置的解析功能。新增 TMDB、AI、登录密码清除复选框。输入新 AI Key 会更新解析和润色密钥；留空保留各自已保存的值。首次开启尚无密钥的润色功能时，需要输入新 Key，界面会提示。

流式测试默认使用服务端已保存的 ai_parser 密钥，可通过 ai_config_source 选择 ai_plot_enhance；临时输入的新密钥仅用于该请求，不保存。使用已保存密钥时，临时覆盖 provider/base_url 与已保存值不一致会被拒绝，避免把服务端密钥发到请求者临时指定的主机。用户应先保存目标服务配置，再测试。AI/TMDB 测试错误不再直接把上游异常字符串返回页面。

认证修改立即生效，浏览器可能要求重新输入凭据，无需重启服务。HTTP Basic 和配置文件内明文密码的存储方式没有迁移。

## 路径权限

浏览根目录来自显式 source_folders、TV/Movie 目标、字幕默认目录以及可选 browse_roots，不自动加入父目录或祖父目录。根目录处 parent 为 null，界面可返回允许根目录列表。配置中可增加独立浏览范围，例如 `"browse_roots": ["/media"]`；这只授权目录浏览，不授予该范围的媒体读取/字幕改名权限。

全局请求预检在业务函数执行前验证以下路径，整批校验成功后才允许写入或启动后台任务：

- 单项与批量纠错/重试的源文件，以及失败文件夹详情扫描：限制在视频 source_folders。
- 字幕扫描、字幕源文件和批量改名的 old/new 路径：限制在视频源目录或字幕默认源目录。
- 字幕写入目录与目标视频目录项：限制在配置媒体库，且 target_dir 必须等于目标视频所在目录。合法的库内视频软链接可以指向允许源目录；指向其他位置的链接被拒绝。
- 目录浏览、字幕扫描和失败文件夹详情会排除解析后越界的软链接；海报服务校验最终图片仍处于媒体库范围。

请求越界返回 403，必要路径参数缺失/类型错误返回 400。既有目录配置仍可由经过认证的管理员修改；管理员主动授予的显式浏览根目录有其对应范围。源目录中软链接的范围按实际解析路径判断。

## 改动文件

- `web/auth.py`、`web/app.py`：统一认证、损坏配置拒绝访问、healthz、禁止业务缓存、全局路径预检。
- 新增 `web/config_secrets.py`：脱敏、状态标志、密钥保留/设置/清除与认证保存约束。
- 新增 `web/path_access.py`：按业务入口完整预检源、目标与批量路径。
- `web/routes_config.py`、`web/routes_ai.py`：接入脱敏与保存契约、服务端 AI Key、测试错误脱敏、海报范围及流资源关闭。
- `web/routes_browse.py`：只允许显式根，排除越界软链接。
- `web/routes_failed.py`、`core/subtitle_handler.py`：扫描目录内部时也过滤越界软链接。
- `static/js/config.js`、`static/js/aiStream.js`、`templates/partials/config_panel.html`：配置状态标志、密钥清除控件、AI 测试及提示；流式错误使用 textContent。
- `Dockerfile`、`docker-compose.yml`：健康检查地址改为 healthz。
- 新增 `tests/test_auth_secrets.py`、`tests/test_access_paths.py`、`tests/config_ui.cjs`、`tests/test_config_ui.py`；调整 `tests/test_app_config.py` 以使用登录凭据和非秘密字段验证多 app 配置隔离。

## 验证结果

先增加回归测试：最初 T03 的 55 项为 **29 failed、26 passed**，暴露未认证公开信息、关闭认证仍被拦截、目录越界、密钥回传及服务端测试密钥缺失等问题。

当前完整 Python 测试结果：**147 passed**（之前 89 项，加 T03 58 项；其中一项调用 Node 的两个前端子测试）。独立 Node 测试结果：**2 passed**。没有跳过或删除失败测试。T00 的配置隔离断言调整为已认证、脱敏后的有效契约，继续核对服务器保存值和两个实例的非秘密配置差异。

环境：Linux、CPython 3.12.15、pytest 9.2.0，虚拟环境 `/home/su/venvs/animeman-t00`；前端测试使用系统 Node 与内置 VM/测试运行器，不新增 npm 依赖。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q
node --test tests/config_ui.cjs
node --check static/js/config.js
node --check static/js/aiStream.js
git diff --check
```

Python AST 语法、JavaScript 语法及差异检查均通过。测试涉及认证开关 × 凭据矩阵、健康检查独立性、前缀绕过、密钥脱敏往返、清除契约、损坏配置、已保存 AI Key 使用及禁止临时重定向、错误信息脱敏、路径预检与扫描内部软链接。媒体均为临时文件，外部服务使用 mock，网络默认阻断。前端在假 DOM/fetch 下执行真实 JS 模块。

## 未测与后续

未执行真实浏览器的 Basic 登录对话框、Docker 构建/部署、Windows 路径、真实 NAS 挂载、真实 AI/TMDB 或 ffmpeg。前端 VM 测试不等同于浏览器端到端测试。

T04 尚未接通所有环境变量持久化路径；T06/T07 的完整任务/缓存并发治理、T08 元数据修复、T11 字幕处理安全、T12 全站动态渲染和 T13 全量输入校验仍待执行。路径检查不替代针对恶意第三方并发替换目录的操作系统级隔离。本卡没有改动整个应用的秘密日志治理或密钥文件加密。

## 回滚

独立补丁 `/home/su/outputs/AnimeMan-T03.patch` 只包含相对 T02 完成状态的变更，包含本卡对旧测试的契约更新。先检查：

```bash
git apply --reverse --check /home/su/outputs/AnimeMan-T03.patch
```

需要回滚时再反向应用，保留之前未提交的 T00–T02；多卡按 T03 → T02 → T01 顺序撤销。没有自动迁移真实配置，新增 configured 标志只存在于 API 响应，clear_secrets 控制字段不持久化。回滚会恢复旧版本不安全的公开端点，不能据此认为旧部署仍具备本卡的认证和脱敏保障。
