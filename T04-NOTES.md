# T04：运行数据路径、Docker 持久化与显式迁移

## 结果与优先级

基线提交仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`。本卡叠加在未提交的 T00–T03 上，沿用 `maintenance/t00-test-foundation`，没有提交、推送或部署，没有迁移真实用户数据。

| 设置 | 含义及优先级 |
|---|---|
| CLI `--config` / `create_app(config_path=...)` / 显式配置函数参数 | 最高优先级，选择一个配置文件 |
| `CONFIG_PATH` | 未显式选择时采用的配置文件路径 |
| 默认配置文件 | 无以上设置时，工作目录中的 `auto_config.json` |
| `CACHE_PATH` | 缓存目录；未设置则保持工作目录中的旧文件名 |
| `LOG_PATH` | 日志目录；未设置则保持工作目录中的 `auto_processor_errors.log` |
| `SOURCE_FOLDERS` | 覆盖配置中的源目录列表；单个路径或 JSON 字符串数组 |
| `TV_TARGET_FOLDER` / `MOVIE_TARGET_FOLDER` | 覆盖对应媒体目标目录 |

路径在调用时解析，未绑定到模块导入时的环境变量值。传入 Web 工厂的配置文件在创建 app 时固定为绝对路径，后台任务使用同一路径。相对环境变量路径以当前工作目录为准；需要跨工作目录/进程保持位置时，请使用绝对路径。

媒体路径环境变量影响有效配置，不静默写回原配置。Web 展示 `environment_managed` 字段，并使相应输入和浏览按钮只读；原样保存其他设置不会覆盖磁盘中的原媒体路径，试图通过 API 修改环境变量管理的路径会返回 400。要通过 Web 管理路径，请从部署环境移除对应变量后重启。

```bash
export CONFIG_PATH=/app/config/auto_config.json
export CACHE_PATH=/app/cache
export LOG_PATH=/app/logs
export SOURCE_FOLDERS='["/media/source one", "/media/source two"]'
export TV_TARGET_FOLDER=/media/tv
export MOVIE_TARGET_FOLDER=/media/movies
```

`SOURCE_FOLDERS=/media/source` 表示一个目录；多个目录必须使用 JSON 数组，不按逗号或冒号切分，避免误拆合法路径和 Windows 盘符。空字符串或 `[]` 表示没有源目录；空的目标目录环境变量会明确报错。

## 文件覆盖范围

`CACHE_PATH` 现已覆盖：

- `auto_processed_cache.json`、`ai_parse_cache.json`。
- `folder_ai_parse_cache.json`、旧 `folder_ai_cache.json`。
- `raw_scan_cache.json`、`ai_preparse_cache.json`。
- `tmdb_search_cache.json`、`media_library_cache.json`、`poster_cache.json`。
- 可选的本地别名映射 `tmdb_aliases.json`（两个搜索模块统一读取位置）。

T01 的缓存备份与主缓存位于同一目录。离线缓存函数若显式传入路径，该参数优先于 CACHE_PATH。配置、缓存、日志写入会创建必要父目录，并在目录错误或读取权限失败时提供错误；原有 JSON 内容校验/损坏恢复的完整治理仍属于 T07/T13。

TMDB、AI 单文件解析、海报和别名的内存缓存会在存储路径变化后重新加载或失效，避免环境变量变化后继续使用旧目录内容。日志通过 setup_logging 明确绑定到当前 LOG_PATH；Web 工厂、启动信息与日志读取 API 使用相同路径。移除了启动入口另行配置的固定工作目录日志文件。

core 包的公共导出保持兼容，改为按需加载，迁移命令不必先初始化处理器和缓存。AI 解析缓存与海报缓存也不再在模块导入时读取磁盘。已有 logger 的对象在 setup_logging 后继续工作，但环境变量不是热更新 API；生产中修改环境请重启服务。

## 旧数据迁移：先预览、备份，再复制

正常读写时，如果新的环境变量目的文件尚不存在、但**当前工作目录**发现对应旧文件，会报 MigrationRequired，避免把旧库误当空库。不扫描整个磁盘；旧数据在其他目录时，必须显式给出 `--legacy-dir`。

先停止写入服务，保留旧文件。使用与新服务一致的目标环境变量运行：

```bash
python -m core.runtime_paths migrate --legacy-dir /旧工作目录
python -m core.runtime_paths migrate --legacy-dir /旧工作目录 --apply
```

第一条仅预览，不创建目的目录或备份；第二条执行。

迁移对象为旧配置、上述所有缓存/别名、日志及其 `.1` 轮转文件，以及旧 T01 备份。操作顺序：检查全部 JSON 是否可解析、源是否为普通文件、目标是否冲突；先在各目的目录的 `.migration-backups` 子目录创建 `<原文件名>.pre-t04-<uuid>.bak`，然后排他创建新文件。原文件保留不动。

新旧目标同时存在且内容不同会拒绝整次迁移，不覆盖任何文件；内容相同视为已存在，重复运行不重复备份或复制。迁移目标若为软链接则拒绝。中途复制失败会撤销本次已创建的目的文件，已完成的备份保留。工具不会合并不同 JSON，也不会替用户选择哪份配置/缓存更正确。

这要求停止服务后迁移，不保证并发服务写入或断电时的事务恢复。没有自动删除旧数据或迁移备份。

## 已有 Docker 容器升级步骤（本轮未实际执行）

原版本的数据可能仍在旧容器 `/app` 根目录，而非挂载卷。先导出旧容器，再重建；不要先执行会删除旧容器的 down/rm。

```bash
# 在项目目录操作；这里的 animeman 是示例容器/服务名称
docker compose stop animeman
umask 077
ANIMEMAN_LEGACY_DIR="$(mktemp -d "$(dirname "$PWD")/animeman-legacy.XXXXXX")"
docker cp animeman:/app/. "$ANIMEMAN_LEGACY_DIR/"

# 构建含 T04 的新镜像，用同一 Compose 环境和持久化卷运行一次性迁移
docker compose build animeman
docker compose run --rm --no-deps -v "$ANIMEMAN_LEGACY_DIR:/legacy:ro" animeman \
  python -m core.runtime_paths migrate --legacy-dir /legacy

# 核对预览，确保没有新旧文件冲突，再应用
docker compose run --rm --no-deps -v "$ANIMEMAN_LEGACY_DIR:/legacy:ro" animeman \
  python -m core.runtime_paths migrate --legacy-dir /legacy --apply

# 迁移成功且检查持久化卷后，再替换旧容器
docker compose up -d --force-recreate animeman
```

示例把旧数据导出到项目的同级新目录，避免备份进入 Docker 构建上下文；该父目录需要可写。保留 ANIMEMAN_LEGACY_DIR 指向的目录和卷内备份供核对。若已有卷中有不同配置，迁移会停止，应先人工比较并选择保留版本。代码包、旧容器和原始数据仍需保留到升级验证完成。新的 config/cache/logs 卷必须对容器用户可写。

## 改动文件

- 新增 `core/runtime_paths.py`：统一路径解析、环境覆盖、旧数据检测、迁移函数及 CLI。
- `core/config_manager.py`、`core/__init__.py`：配置优先级、运行时覆盖、按需导出；`main.py`、`core/offline_ai_preparser.py` 接通 CLI 选择。
- `core/cache_manager.py`、`core/folder_ai_cache.py`、`core/folder_parser.py`、`core/tmdb_cache.py`、`core/media_library_cache.py`、`core/offline_ai_preparser.py`：缓存实际读写与父目录创建。
- `core/parser_manager.py`、`core/processor_search.py`、`core/search_enhancer.py`：随缓存路径切换重载；辅助 TMDB 查询沿用调用者传入的有效配置。
- `core/logger.py`、`web_app.py`、`web/routes_task.py`：日志统一路径与绑定。
- `web/app.py`、`web/auth.py`、`web/routes_config.py`：配置路径初始化、海报缓存路径、环境管理字段及保存保护。
- `static/js/config.js`、`templates/partials/config_panel.html`、`tests/config_ui.cjs`：环境管理路径只读和界面验证。
- `tests/conftest.py`、`tests/test_isolation.py`：环境变量真正生效后仍保持逐测试隔离；新增 `tests/test_runtime_paths.py`。
- `README.md`、`TESTING.md`、`docker-compose.yml`、`.gitignore` 与本说明：使用方式、升级步骤、持久化与迁移备份忽略规则。

## 验证与限制

先添加测试：初始 T04 的 18 项为 **17 failed、1 passed**。随后补充 Web 配置往返、显式缓存路径、迁移失败/软链接拒绝、权限重复错误、独立迁移 CLI、新进程重读和辅助查询配置测试，T04 共 31 项。

完整结果：**178 passed**（之前 147 + T04 31）；Node 前端 **3 passed**，其中环境管理路径只读为本卡新增子测试。未跳过测试。Python AST、JavaScript 语法、git diff 检查通过。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q
node --test tests/config_ui.cjs
node --check static/js/config.js
git diff --check
```

环境为 Linux、CPython 3.12.15、pytest 9.2.0，使用既有独立虚拟环境。全部数据来自临时目录。新进程在另一个 cwd 中成功读取持久化配置和缓存，并写入指定日志目录；迁移 CLI 的预览不会初始化处理器或生成运行文件。

**未测**：实际 Docker 构建/容器重建、Windows 实机路径、真实 NAS 卷权限和挂载、进程崩溃/断电恢复、真实媒体与外部 API。容器集成验证仍按计划在 T15 执行；新进程持久化测试不能替代实际 Docker 集成。T05 的 dry-run/force-full 传递问题仍未处理。

## 回滚

独立补丁 `/home/su/outputs/AnimeMan-T04.patch` 只包含相对 T03 完成状态的改动。先检查：

```bash
git apply --reverse --check /home/su/outputs/AnimeMan-T04.patch
```

需要时再反向应用，保留未提交的 T00–T03；多卡按时间倒序回滚。代码回滚不会自动把卷中的新数据复制回旧容器/旧工作目录。迁移保留了旧源文件和备份，但若新版本已经产生更新，应停止写入后比较数据再选择恢复；不得覆盖更新或恢复不安全旧 target 供旧版本执行删除。

本轮没有执行真实数据迁移或容器操作，只有临时目录测试数据。
