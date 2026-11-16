# T10：AI 输出契约、请求合并与缓存身份

## 范围与基线

基线仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`。本卡依次接在已完成的 T09 后；当前 git 状态和真实函数已核对，仓库及祖先目录没有 AGENTS.md。保留 T00–T09 未提交的改动，没有提交、推送、发布或使用真实用户媒体/密钥。

本次按任务卡的三个子步骤执行：输出校验、同目录请求合并、缓存身份与完整覆盖。复用既有 JSON 原子事务、备份、取消和单写任务机制，没有引入数据库/队列或修改后续任务卡。

## 1. AI 返回值与文件身份

新增 `core/parse_contract.py`。模型 JSON 必须是对象；数组、null、非对象文本、非有限数字和重复字段均可控回退，不从数组中猜测某个对象。支持完整 JSON 和单个 Markdown JSON 代码块；含额外解释、坏结构或重复键的响应会被拒绝。

文件级有效记录要求 media_type=tv/movie、非空且非 Unknown/纯点号的标题。TV 必须有可信 season/episode；十进制数字字符串可转换，季号保留 0，布尔数值、负数、浮点季集、越界值及缺失 TV 集号拒绝。季号范围 0–99、集号 1–9999。年份使用四位数字/数字字符串（1800–2199）或 null；别名必须是字符串数组，文本/纠正字段也校验类型。没有可靠信息返回 unknown 或走现有本地/人工回退，不补 E01。

模型数据只保留允许的元数据字段，不接收模型的 path/target、tmdb_id、confidence 或内部来源标志作为执行依据。文件夹返回的键必须逐字属于本批输入标识；标识由真实输入文件相对目录生成，支持不同子目录下的同名文件，拒绝绝对路径、越界或不在输入中的名字。磁盘路径始终由程序的输入文件和库路径逻辑决定。

文件夹结果逐文件验证；合法行可保留，未知/缺失行进入由真实输入集合计算的 unparsed_files。坏行不被缓存为成功。压缩格式 v2 用默认值与逐文件覆盖保存，title/media_type/year/season、完整单集标题等不再被目录默认值覆盖或截断。

文件夹 AI 改为每批最多 30 个实际文件，按批顺序调用，覆盖全部输入。长剧入口复用该流程，不再从首尾少量样本宏观外推所有集号。未返回的文件显式列为未解析；离线汇总区分完整、部分、已解析和未解析数量，部分文件夹不计为完整成功。另修复原文件夹提示词直接 format JSON 花括号而触发 KeyError 的问题。

## 2. 同目录请求合并与取消

parser_manager 在同一锁区间查找或创建共享请求状态，状态携带 Event、结果和异常。相同缓存命名空间、目录、解析配置和 TMDB 结构上下文的并发调用只由一个 owner 发起请求，等待者取得同一结果或相同失败信息；结果返回副本，异常也复制后传播。

等待默认最多 60 秒，沿用可取消等待；可在 ai_parser.folder_wait_timeout 配置其他秒数。等待超时直接回退，不释放 owner、不发起重复请求。finally 唤醒等待者，只删除仍然属于自己的请求状态。任务作用域保留已完成/失败的请求结果，避免同一批任务的后到文件不断重复无效请求；新任务可按自身状态重新尝试。

实时批量、按需离线和异常文件夹批量入口共用协调器。不同 TMDB 结构提示属于不同输入上下文，不互相复用结果。请求前复制有效配置；取消和缓存损坏继续向上传播，不当作普通解析失败吞掉。

## 3. 缓存内容、规则与持久化

新增 `core/parse_identity.py`、`core/parse_cache.py`，当前规则版本为 t10-v1。身份包含实际文件清单、路径、设备/inode、大小、mtime/ctime 纳秒、前 1MB 内容摘要、AI/本地解析配置、过滤/映射/源目录规则及规则版本。单文件身份也包含相关文件夹上下文，增加邻居文件可使旧单文件结果失效。parse_rules_version 可用于显式调整规则身份；代码规则升级应相应更新 RULE_VERSION。

runner 和 Web 写任务建立作用域，并向线程池传播。一次任务内为解析身份计算的同一文件头只读取一次；目录身份被复用，避免每集重读全目录文件头。完成请求前重新检查文件清单和 stat 版本；单文件结果发布前也检查源版本。请求期间发生变化会拒绝旧结果、停止该文件解析并按可重试错误报告，不给变化后的数据附上旧身份。这里不是对其他进程的文件系统快照锁。

单文件、文件夹、离线及目录元数据缓存统一携带 _schema、identity 和经过验证的 payload。缓存命中也验证业务结构。内存缓存会检查持久文件版本，磁盘损坏不会被旧内存值掩盖；只有持久化成功才更新内存，备份/写入失败不会污染内存命中。

旧无身份记录和旧宏观/有损压缩记录不直接信任，也不自动猜测迁移值。读取时忽略并保留；取得新的可信结果后，在首次升级非空旧缓存或替换旧版本条目前先创建完整 `.t10-<内容哈希>.bak`，然后通过原子事务保存。备份失败阻止迁移。没有强制清空旧键或业务缓存；未知/无效新响应不覆盖旧文件。损坏 JSON 沿用 T07 的保留、备份和报错行为。模拟模式不写任何缓存、备份或配置。

TMDB 文件夹缓存保存 `{id, media_type}`，类型回退 TV→movie 后命中仍查 movie。键包含文件夹内容/配置身份、请求类型、标题、年份、别名、时长提示、语言/相关 TMDB 配置和缓存命名空间；候选选择和结构辅助缓存也加入配置身份与类型。解析规则版本同时纳入失败记录指纹，使规则升级能够重新评估旧的普通失败；no_retry=true 仍优先，保持人工选择。

## 改动文件

- 新增 `core/parse_contract.py`、`core/parse_identity.py`、`core/parse_cache.py`。
- `core/ai_client.py`：对象/字段校验、提示词修复、30 文件分批、取消与网络失败来源。
- `core/parser_manager.py`：共享请求状态、校验后的回退链、版本化单文件缓存。
- `core/folder_ai_cache.py`、`core/folder_parser.py`、`core/offline_ai_preparser.py`：统一身份、无损逐文件结果、旧缓存备份与部分覆盖汇总。
- `core/parser_helpers.py`、`core/processor_helpers.py`：统一文件键，传播取消/存储异常。
- `core/processor_core.py`、`core/processor_folder_ai.py`、`core/processor_search.py`：解析入口合并、逐文件类型保留及 TMDB 类型/策略缓存。
- `core/processor_runner.py`、`web/task_state.py`：任务身份计算作用域及线程传播。
- `core/failure_policy.py`：规则版本进入失败重新评估条件。
- `web/routes_offline.py`：完整/部分文件夹统计，未返回文件不计完整成功。
- 新增 `tests/test_ai_contracts.py`。更新 `tests/test_cache_transactions.py` 和 `tests/test_runtime_paths.py` 的旧夹具：将空 files/仅 title 改为合法元数据，离线并发测试补建真实临时小文件；原有不丢记录、命名空间隔离断言保留，没有跳过测试。
- README 与本说明。

## 验证证据

先写首批 21 项测试，修复前 **19 failed、2 passed**，暴露坏类型直接 setdefault、布尔/负季号、缺集号补一、JSON 提示词错误、覆盖缺项、压缩丢字段、旧身份和 TMDB 回退类型错误。之后补充超时不重复请求、10 线程共享异常、迁移失败不污染内存、持久损坏可见、目录同名文件、源目录边界、请求期间变更、上下文和规则升级等回归。

本卡 **39 项 Python 回归测试**；最终完整 Python **384 passed**（T09 的 345 + T10 39），Node **7 passed**，无跳过。并发测试使用 Event/Barrier；测试媒体为临时目录小文件，所有 AI/TMDB 使用 mock，pytest 会话继续阻断 Requests/socket。仓库没有生成运行配置、缓存、日志或媒体。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q tests/test_ai_contracts.py --tb=short
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
node --test tests/config_ui.cjs tests/task_ui.cjs tests/confidence_ui.cjs
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T10.patch
```

全部 Python AST、差异、独立补丁反向检查通过；另在隔离副本按 T10→T09 撤回并核对涉及文件恢复到 T08 状态。环境沿用 Linux、Python 3.12.15、pytest 9.2.0，无新增第三方依赖。

未测 Windows、Docker、真实 NAS、多进程、真实 AI/TMDB 的响应质量、生产规模性能和浏览器端到端交互。锁/共享请求只在单进程内协调，不能保证模型语义一定正确；类型/输入身份校验不会变成强设 100% 的依据。内容摘要不是全文件哈希，stat/inode/前 1MB 机制也不是防恶意修改的完整性证明。长期服务的真实大目录规模和模型费用仍需集成验证。

## 兼容、迁移与回滚

原 parse_filename、单文件 AI、文件夹 AI、离线和长剧入口的位置参数保留。长剧输出现在使用 files/unparsed_files，不再把 _stats 宏观规则当作每个文件已经解析；外部调用者如依赖旧宏观结构，需要适配。单文件 _save_parse_result 是私有写入口，现在拒绝不完整记录。

文件夹结果可能只有逐文件类型/标题，调用者应读取 files，而不是用目录字段覆盖混合内容。新增结果字段和缓存信封为受控升级，不会自动改名媒体或删除旧缓存。开始应用后首次相关解析可能产生更多 AI 调用；部分覆盖保留未解析集合供本地/单文件/人工回退。

独立补丁 `/home/su/outputs/AnimeMan-T10.patch` 相对 T09 完成状态生成。停下写任务后，先反向检查，再按需反向应用。撤销本轮两卡应依次 T10 → T09，不要直接恢复整个仓库，避免丢失 T00–T08 未提交工作。

代码回滚不会回滚或删除缓存、备份与媒体。旧代码不理解新缓存信封，若要运行旧代码，应先停服并核对具体 `.t10-*` 有效旧快照后再选择恢复对应缓存；恢复快照会撤销其后的派生缓存更新。`.corrupt-*` 保留的是损坏原件，不能当作有效恢复文件。处理结果和用户媒体不应随解析缓存一起盲目恢复。本轮所有实际写入均在隔离测试目录，没有用户媒体需要恢复。
