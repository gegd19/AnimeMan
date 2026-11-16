# T05：CLI 覆盖参数、模拟运行与全量语义

## 修改结果

基线提交为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`；本卡继续叠加在未提交的 T00–T04 上，分支仍为 `maintenance/t00-test-foundation`。本轮没有提交、推送、发布或操作真实媒体。

CLI 不再先改一份内存配置再让 runner 重新读取而丢失参数。`run_processor_with_callback` 新增可选关键字 `config_overrides`，CLI 的 `--dry-run` 和 `--force-full` 通过它传递；Web 继续使用同一入口及已保存的配置。覆盖只存在于本次有效配置，不写回 JSON。

`--force-full` 只禁用增量跳过：扫描到的成功/失败项都会重新评估；原有缓存仍加载，未扫描项目不会被清空。实际处理完成后会保存结果，修复模式也不会因关闭 incremental 而读到空缓存。这完成了全量结果保存的必要部分；T07 的记录级事务、并发更新和失败分类仍未实现。

## 模拟模式契约

模拟允许读取文件、读取既有缓存、运行只读识别、查询外部 API 和输出日志；可能调用 AI/TMDB，因此不是离线模式，也不保证不会产生 API 费用。

模拟处理禁止：

- 创建或替换媒体链接、目标目录及整理暂存目录。
- 写入 NFO、下载落盘图片、同步/复制/链接字幕或改名字幕。
- 保存处理、AI、文件夹、离线、TMDB、媒体库和海报缓存，或因缓存过期而改写磁盘。
- 因缺少配置而自动生成默认配置，或为旧缓存创建隔离标记/备份。
- 在纠错完成后删除旧目标或元数据。

目标边界、不同文件冲突和危险旧缓存检查仍然生效，不因模拟而放行。冲突可通过 API 返回 `target_conflict`/409；模拟不修改原冲突记录。

这些约束适用于整理、修复、手动纠错/重试及关联字幕操作。用户显式保存配置、删除缓存、执行独立离线缓存扫描或调用迁移工具属于另外的管理操作，不因配置中的 dry_run 自动变成只读。管理员设置模拟开关本身当然仍需保存配置。

## 实现与入口

新增 `core/execution_mode.py`，通过 ContextVar 管理作用域内的只读状态，退出后恢复；嵌套调用不能关闭父级只读状态。runner 为每个线程任务分别复制上下文，避免只读标志在线程池丢失。核心单文件处理、修复与字幕入口也会从 config 启用该作用域。

电影、TV 和手动处理分支在写入元数据、目录或链接之前生成并校验目标计划。T02 的事务包装器在模拟时直接进入只读规划分支，不创建 `.animeman-stage-*`，日志使用真实目标路径。修复模式只输出当前修复逻辑能够补全的文件清单。

缓存保存函数增加只读保护，AI/TMDB 选择结果不会在模拟时存入新缓存；过期查询也不会写回磁盘。配置加载增加 `create_if_missing` 参数，CLI 模拟和 runner 对缺失配置采用只读默认值。NFO、链接与图片写入点也有作用域内的保护，正常模式行为保持。

模拟纠错不调用 T01 的旧缓存迁移/隔离或旧产物清理。字幕中心的整理、同步和重命名在模拟时不执行写入，API 区分 `processed/success` 实际数量、`planned` 计划数量，并返回 `dry_run`。界面使用“模拟完成”提示；AI 字幕组合入库在收到改名预览后停止，不再拿尚未创建的新名字继续执行入库。

## 使用

```bash
python main.py --config /path/to/auto_config.json --dry-run
python main.py --config /path/to/auto_config.json --force-full
python main.py --config /path/to/auto_config.json --dry-run --force-full --repair
```

通过库调用：

```python
run_processor_with_callback(config_path, callback,
    config_overrides={"dry_run": True, "incremental": False})
```

旧的两个位置参数以及 repair_mode 调用保持兼容。已有 `dry_run=true` 的配置仍生效；CLI 传入的标志只覆盖对应字段，未传标志不会强制把配置中的模拟开关关闭。

## 改动文件

- 新增 `core/execution_mode.py`。
- `main.py`、`core/config_manager.py`、`core/processor_runner.py`：CLI 参数传递、缺失配置只读、全量缓存语义和线程上下文。
- `core/library_transaction.py`、`core/processor_core.py`、`core/processor_movie.py`、`core/processor_tv.py`、`core/processor_manual.py`、`core/processor_repair.py`：模拟规划、冲突判断、纠错前后零业务写入。
- `core/processor_cache_ops.py`、`core/cache_manager.py`、`core/parser_manager.py`、`core/folder_ai_cache.py`、`core/folder_parser.py`、`core/offline_ai_preparser.py`、`core/tmdb_cache.py`、`core/media_library_cache.py`、`core/processor_folder_ai.py`、`core/processor_search.py`、`web/routes_config.py`：缓存与相关内存结果写入保护。
- `core/nfo_writer.py`、`core/file_linker.py`、`core/tmdb_client.py`、`core/subtitle_handler.py`：元数据、链接、图片、字幕写入边界。
- `web/routes_failed.py`、`web/routes_cache.py`、`web/routes_subtitle.py`：模拟响应与计数。
- `static/js/correction.js`、`static/js/history.js`、`static/js/subtitleCenter.js`：计划提示与组合流程停止。
- 新增 `tests/test_dry_run.py`；更新 `tests/config_ui.cjs`；更新 README 与本说明。

## 验证证据

先写测试，最初 T05 的 **14 项全部失败**：暴露参数未传递、元数据写入、暂存目录创建、修复忽略有效缓存及纠错改写缓存等问题。

当前 T05 共 28 项，完整 Python 结果为 **206 passed**（之前 178 + T05 28）；Node 前端为 **4 passed**，其中模拟重试提示为本卡新增子测试。没有跳过测试或吞掉异常来使测试通过。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q
node --test tests/config_ui.cjs
node --check static/js/subtitleCenter.js
node --check static/js/history.js
node --check static/js/correction.js
git diff --check
```

Python AST 语法、JavaScript 语法及差异检查通过。环境为 Linux、CPython 3.12.15、pytest 9.2.0，沿用独立虚拟环境。

关键验证：

- CLI 三种标志组合确实传入 runner，配置文件保持原样。
- 四条电影/TV 自动和手动分支的预览不会调用元数据/字幕写入函数，不创建目标或暂存目录。
- 使用真实文件名解析器走 CLI 模拟主流程，TMDB 和时长探测使用 mock，配置、缓存与媒体树快照保持一致。
- 线程池内试图保存处理缓存和解析缓存时被只读作用域阻止；七类缓存保存和 TMDB 过期处理不修改磁盘。
- `--dry-run --force-full --repair` 仍读取已有电影/TV 缓存，能规划缺失元数据且无写入。
- 配置不存在时不创建文件；模拟纠错不备份/隔离旧记录；字幕同步不启动子进程；Web 纠错、字幕改名及目标冲突保持业务目录快照不变。
- 实际全量处理重新处理文件、保存新记录，并保留未扫描历史。

所有媒体均为临时小文件；外部 API 使用 mock，测试会话默认阻断真实网络。快照排除明确允许变化的日志目录，不排除配置、缓存、源或目标目录。

## 未测、边界与后续

未测 Windows、Docker、真实 NAS 卷、真实 AI/TMDB、真实字幕调轴及浏览器端到端交互；前端测试使用 Node 假 DOM/fetch。

只读标志由受控调用链和受控线程传播，不是阻止任意第三方 Python 代码写磁盘的系统沙箱。日志仍可能创建文件或目录。模拟不证明实际运行时权限、跨盘链接和网络都可成功。

修复能力仍按现有实现覆盖 movie/tvshow NFO 和图片；季/单集元数据补全、NFO 命名与转义仍属 T08。字幕覆盖、调轴源文件保护和批量改名冲突仍属 T11。T06 的取消/状态互斥、T07 的全量事务治理仍待执行。

## 回滚

独立补丁 `/home/su/outputs/AnimeMan-T05.patch` 相对 T04 完成状态生成。先执行检查，需要回滚时再反向应用：

```bash
git apply --reverse --check /home/su/outputs/AnimeMan-T05.patch
```

按 T05 → T04 → T03 的倒序撤销多卡；不要恢复整个仓库而丢失前几卡尚未提交的改动。没有迁移或改写真实配置/缓存结构。回滚后旧的模拟写入和 CLI 参数丢失问题会重新出现。本轮只在隔离测试目录执行真实模式验证，无真实媒体需要恢复。
