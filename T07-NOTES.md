# T07：缓存事务与失败恢复

## 范围与结果

基线仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`。已读取计划书 T07、当前 git 状态和真实读写/重试函数，确认仓库及祖先目录没有 AGENTS.md。本卡叠加于未提交的 T00–T06，没有提交、推送、发布或操作真实媒体。

T05 已修复全量运行不保存结果，T06 已串行化业务写任务；本卡进一步消除内部 worker、AI 文件夹和离线缓存的旧快照覆盖。没有迁移数据库、重构识别算法或同时执行 T08–T15。

## JSON 事务与损坏处理

新增 `core/json_store.py`：同一实际父目录/文件名共享进程内 RLock，事务在锁内完成读取、修改、保存。采用同目录唯一临时文件，序列化后 flush/fsync，再以 os.replace 发布。异常时清理临时文件；原文件不会因序列化或替换失败被截断。新文件默认私有权限，替换现有文件时保留权限。

接入处理缓存、单文件 AI、两类文件夹 AI、离线扫描/预解析、媒体库派生缓存、TMDB 搜索和海报缓存。公共 save_* 保留“显式替换整份文档”的兼容语义，内部按记录更新的调用改为锁内事务。文件夹缓存过期删除也核对当前记录，避免删除并发产生的新记录。媒体库重新生成与保存受处理缓存锁保护。

读取不存在的文件仍返回空对象。已有文件若不是有效 JSON 对象，会保留原文件，先创建 `.corrupt-<内容哈希>.bak`，再报告包含文件和备份路径的 CacheCorruptionError；保存入口同样拒绝覆盖损坏文件。相同损坏内容复用已核实一致的备份，避免状态轮询不断增加副本。模拟模式报告损坏，但不创建备份或其他文件。顶层对象以外的完整业务字段校验仍属 T10/T13。

原始损坏文件的备份用于保留证据，不等于已恢复的有效缓存。需要恢复时先停止服务，保留原文件和备份，选择已知有效的历史数据或人工修复验证后再恢复；本卡不自动清空或猜测修复内容。

## 处理结果按记录提交

runner 深拷贝起始记录，对完成的源文件只提交发生变化的记录，不再用旧的整表快照覆盖其他键。全量运行也保留未扫描记录和其他内部调用已经提交的更新。

真实媒体事务在新产物发布后、返回成功前提交对应缓存记录。缓存提交异常时撤回本次新建的发布文件，保留源文件、旧目标和旧记录。每个已完成结果会落盘，线程全部退出后再排空剩余变化；保留 T06 的有界队列、取消状态和最终计数。模拟不提交记录。

已有成功记录重新处理失败时，保留原有媒体字段与产物，另存 `last_failure` 诊断；成功记录不会被失败占位项替换。失败项及无旧有效记录的异常会记录为 media_type=failed。自动 retry 接口继续保留算法给出的 confidence，未再强设 100。

## 失败策略与兼容

新增 `core/failure_policy.py`。失败记录新增：

- `failure_category`：transient（网络超时、连接故障、HTTP 429/5xx 等）、no_match、invalid_input、conflict。
- `attempt_count`、`last_error`、`failed_time`、`retry_after`。
- `file_fingerprint`、`config_fingerprint`；原有 fingerprint、failed_reason 等字段保留。
- `no_retry=true` 表示人工禁止自动重试，文件或配置变化及全量运行也不会撤销它。用户显式调用单项重试/纠错仍可重新处理。

默认增量整理中，临时失败最多尝试 3 次（包括首次），两次自动重试分别退避 60、120 秒。没有阻塞 worker 等待，也没有新增常驻重试调度器：后续整理任务在 retry_after 到期后才会接受该项。no_match、invalid_input、conflict 在输入不变时不自动重试。文件或相关配置变化会重新评估并开始新的计数；旧失败记录缺少新指纹时会重新评估一次。

运行开始前，如本轮将重新评估旧失败记录，会先把完整处理缓存备份为 `.t07-<内容哈希>.bak`；备份失败则在媒体处理之前退出。没有批量改写历史记录。未扫描、人工禁止重试的项保持原样。

`incremental=false` / `--force-full` 继续作为明确的全量重评操作，可越过普通失败跳过和退避；no_retry=true 仍优先。这样保留 T05 的全量语义。默认增量运行才受自动重试预算约束。

可选配置如下，省略时使用默认值；max_attempts 接受 1–10 的整数，backoff_seconds 接受 1–3600 秒，指数退避上限 3600 秒。非法值报错。

```json
{"failure_retry": {"max_attempts": 3, "backoff_seconds": 60}}
```

文件指纹沿用路径、大小、mtime 与前 1MB 内容哈希，不等同于完整视频内容校验；保留大小/mtime 且仅修改后部内容的变化可能无法检出。配置指纹为 SHA-256，排除认证、并发数、增量/模拟开关、限速和内部回调，包含识别、链接、目标和重试策略等配置。凭据变化会使相关失败重新评估，但不把凭据明文写入指纹字段。新网络失败摘要只记录异常类型/HTTP 状态，避免把含 API key 的 URL 存入失败原因或 last_error。

人工纠错成功写 `confirmed_by_user=true`，没有算法评分时 confidence=null；不把人工确认伪装成算法 100%。历史、缓存及文件夹详情界面显示“人工确认”或“未评分”。缓存列表升降排序均接受 null 并将未评分项置后。既有历史置信度不自动重写，因为无法可靠推断旧 100% 记录的来源。

## 改动文件

- 新增 `core/json_store.py`、`core/failure_policy.py`。
- `core/cache_manager.py`、`core/processor_runner.py`、`core/processor_cache_ops.py`、`core/library_transaction.py`：记录级提交、旧失败备份、策略接入和提交失败保护。
- `core/folder_ai_cache.py`、`core/folder_parser.py`、`core/offline_ai_preparser.py`、`core/parser_manager.py`：文件夹/离线事务，消除旧快照写回。
- `core/media_library_cache.py`、`core/tmdb_cache.py`、`web/routes_config.py`：派生缓存原子读写及损坏诊断。
- `core/ai_client.py`、`core/tmdb_client.py`：保留网络错误分类来源。
- `core/processor_core.py`、`core/processor_folder_ai.py`、`core/processor_search.py`、`core/processor_movie.py`、`core/processor_tv.py`、`core/processor_manual.py`：传播损坏错误、识别失败来源、人工确认字段。
- `web/app.py`、`web/routes_cache.py`、`web/routes_failed.py`：损坏响应、诊断字段、未知评分排序和确认标志。
- `static/js/history.js`、`static/js/processedCache.js`、`static/js/failedCache.js`：人工确认/未评分显示。
- 新增 `tests/test_cache_transactions.py`、`tests/test_failure_recovery.py`、`tests/confidence_ui.cjs`；README 与本说明。

## 验证证据

先编写回归，再最小修复。首批测试暴露固定临时文件残留、离线/媒体库文件截断、损坏缓存静默回退、文件夹并发覆盖、runner 整表覆盖和永久跳过失败项。两条自动 retry 评分兼容测试确认前卡行为已正确，未重复修改这部分算法。后续补充旧缓存备份失败、发布后缓存提交异常、重试预算、旧成功记录诊断及未评分界面的回归。

本卡新增 **53 项 Python 测试**；完整套件 **292 passed**（T06 的 239 + 53），Node **7 passed**（原有 6 + 本卡 1），没有跳过。测试用 Event/Barrier 控制并发，不靠随机 sleep；写入故障使用注入，所有媒体使用临时目录的小文件，AI/TMDB 均 mock，整个 pytest 会话阻断 Requests/socket。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q tests/test_cache_transactions.py tests/test_failure_recovery.py --tb=short
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
node --test tests/config_ui.cjs tests/task_ui.cjs tests/confidence_ui.cjs
node --check static/js/history.js
node --check static/js/processedCache.js
node --check static/js/failedCache.js
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T07.patch
```

另检查 core/web/tests 全部 Python AST；仓库根目录没有生成运行配置、缓存、日志、临时文件或媒体。环境为 Linux、Python 3.12.15、pytest 9.2.0。

未测 Windows、Docker、真实 NAS/跨盘存储、真实网络/限流、真实媒体/字幕调轴和浏览器端到端交互；前端为 Node VM 与假 DOM/fetch。故障注入验证进程内序列化/替换失败，不宣称覆盖突然断电的所有文件系统持久性行为。锁只协调单进程，多个服务/CLI 进程仍须避免同时写同一库。NFO、解析规则、AI 输出契约和派生缓存身份/失效仍按 T08–T10/T14 执行。

## 回滚

独立补丁 `/home/su/outputs/AnimeMan-T07.patch` 相对 T06 完成状态生成，已通过反向检查。停止所有处理任务后，先执行 `git apply --reverse --check`，再按需反向应用本卡补丁；多卡按 T07 → T06 → T05 倒序撤销，保留前卡未提交的修改。

缓存文件名和顶层 JSON 对象结构保持兼容，新字段为附加字段。回滚代码不会自动恢复或删除缓存、备份或媒体，也不会把 null 人工评分重新设成 100；旧代码的置信度排序不支持 null，如需运行旧代码，应先选定有效备份或另行调整兼容读取。`.t07-*` 是升级前完整快照，恢复会同时撤销该快照之后的处理记录，应在停服后明确选择；`.corrupt-*` 是损坏原件副本，不应直接当作有效缓存恢复。

本轮真实模式写入仅发生在隔离测试目录，无用户媒体需要回滚。代码回滚会恢复旧的缓存覆盖、损坏静默回退和永久跳过等缺陷。
