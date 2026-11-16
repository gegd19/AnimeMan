# T13：输入与配置有效性

## 范围与基线

基线为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`。本卡相对 T12 完成状态实施；执行前核对当前 git 状态、计划书、真实函数与调用链，仓库及祖先目录没有 AGENTS.md。保留 T00–T12 未提交修改，没有提交、推送、发布或操作真实用户媒体。

T12 后仍存在默认值浅复制、通用配置读取损坏 JSON 后回退、配置/映射读改写之间竞争、分页与请求类型缺少系统校验等问题。认证入口原有的损坏配置拒绝策略保留并统一到通用加载器；没有把已存在的保护当作本卡新增成果。只执行 T13 及其请求、配置与原子 JSON 存储依赖，没有修改前端、模板、媒体删除策略、缓存格式或 T14/T15。

## 修复行为

### 请求入口

- `core/validation.py` 提供不强制类型转换的公共校验；`web/validation.py` 在路径访问、写任务获取和业务处理前检查完整请求。JSON 顶层必须是对象，拒绝 null/数组/字符串/布尔顶层、坏 JSON、重复键、非有限数值、NUL/无效 Unicode、过深结构及过大数组。
- 不消费请求体的运行/停止/清空等入口仍允许空请求体；如果显式提供请求体，必须是 JSON 对象。DELETE 映射入口同样检查显式请求体，避免非法 JSON 被忽略后仍执行删除。认证通过后，已有写任务的 409 优先级继续保留；请求空闲时才继续校验和尝试原子获取写任务，未削弱任务互斥。
- 请求上限 4 MiB、嵌套最多 32 层、数组最多 1000 项。路径字符串非空、最多 8192 字符，不修剪或重新编码合法原值。扩展名列表最多 64 项。分页 page=1–1000000、per_page=1–200，拒绝负数、零、浮点、文字数字、重复查询参数与未知排序枚举。历史接口只接受实际实现的 processed_time/src_name 排序。
- 修正/映射使用整数 TMDB ID（1–2147483647）、季号 0–99、集号 1–9999；布尔值不能冒充整数。单文件 TV 修正必须有季/集信息；批量 TV 保留 season=null 自动换算，起始集号与步长均为 1–9999。movie 可用 null 季集值和空的起始集号/步长；电影工作线程不进行 TV 集号运算。阈值为 0–100 有限数值，delete_source/auto_sync 等必须是真正布尔值。
- 字幕执行先检查所有项的结构、目标与开关；整批校验通过后才可能执行第一项。没有通过跳过坏项、吞异常或设置虚假置信度通过测试。
- 校验错误统一为 JSON 400（invalid_request），过大请求 413；不存在的映射记录 404、重复关键词 409。既有单条媒体/缓存缺记录 404、任务/目标冲突 409 和批量逐项统计契约保留。AI 临时配置同样校验类型、数值和提示词格式，在返回流式响应前拒绝错误格式。

### 配置加载与保存

- 每次递归合并默认配置都深复制，返回值不会共享嵌套列表、字典或默认映射。有效部分配置仍可加载；未知扩展键保留，但必须满足 JSON 类型、编码、深度和大小要求。已知业务字段按模式校验。
- 真正不存在的配置仍保留首次安装创建默认文件的行为；create_if_missing=False 不创建文件。已有文件的损坏 JSON、重复键、错误结构/数值不会被当作空配置。已有悬空配置链接也会拒绝默认回退并保留链接。认证已启用的磁盘配置必须显式包含非空凭据，不从默认 admin 字段补足。
- 可读取的无效原件保留，生成按内容散列命名的 `.t13-invalid-*.bak`，权限 0600；同样内容不反复复制。随后抛出 ConfigError，业务访问返回 503，healthz 仍可用。不可读取的文件/链接返回错误，不伪造空备份。对损坏现有文件的保存同样拒绝覆盖。
- 配置先验证完整合并结果，再使用既有 json_store 的唯一临时文件、fsync 和原子 replace 发布，失败清理临时文件且保留旧文件。序列化后的字节数也必须不超过 4 MiB，避免保存成功却无法重新加载。既有文件权限沿用；未新增配置/缓存格式迁移。
- `update_config` 把读取、深复制修改、全量校验与发布放在同一进程锁/路径锁内。配置 API 及映射增改删使用该事务，避免两个同时到达的补丁互相覆盖。映射更新使用存储配置，不会把环境覆盖路径写回文件；空密钥保留、显式清除、环境只读和运行中配置快照契约继续保留。
- AI 缺少有效密钥时原有的运行时解析回退仍只作用于返回副本，不写回文件；认证损坏不会采用此类回退。

主要配置边界如下，完整实现见 core/validation.py：

| 字段 | 允许值 |
|---|---|
| max_workers | 真正整数 1–32 |
| link_type | hard/symlink |
| subtitle_center.link_mode | hard/symlink/copy |
| AI provider | 当前支持的 deepseek/openai/zhipu/qwen |
| AI temperature / max_tokens | 有限数值 0–2 / 整数 1–131072 |
| AI timeout / folder_wait_timeout | 1–600 秒 / 0.001–600 秒 |
| subtitle.sync_timeout | 整数 1–3600 秒 |
| subtitle_center.auto_match_threshold | 有限数值 0–100 |
| failure_retry | 沿用已有 max_attempts=1–10、backoff_seconds=1–3600 |
| prompt_template | title/original_plot 占位符；禁止格式宽度、属性访问与错误花括号，字面花括号使用双花括号 |

## 改动文件（15 个）

- 新增 `core/validation.py`、`web/validation.py`：共享值/配置模式、严格 JSON 与请求入口校验。
- `core/config_manager.py`：深复制合并、损坏与缺失分离、备份、完整验证和原子配置事务。
- `core/special_mapping.py`：复用严格规则校验，拒绝负季集、布尔数值和错误开关。
- `web/app.py`、`web/auth.py`：请求/错误入口、统一配置加载与认证拒绝策略。
- `web/routes_cache.py`：使用已校验的分页整数。
- `web/routes_config.py`、`web/routes_mapping.py`：锁内配置更新、错误状态与环境覆盖保护。
- `web/routes_failed.py`：电影批量请求保留空的 TV 专属参数，跳过 TV 运算；这是对照前端合法请求新增的最小依赖修复。
- 新增 `tests/test_input_validation.py`：206 项隔离回归。
- `tests/test_link_safety.py`：既有危险旧记录测试补充合法 movie 类型，使其在严格输入契约下继续验证 409、源文件保留和 needs_reindex；原断言保留，没有改成接受 400 或跳过。
- `README.md`、`TESTING.md`、本说明：契约、验证、兼容和恢复。

## 验证证据

先写首批 168 项回归，修复前 **154 failed、14 passed**。修复后补充请求重复键/非有限数值、搜索查询、可选配置与编码、保存后可加载上限、深嵌套、写入故障、私有坏配置备份、环境与映射更新、精确数组边界、秘密保留、提示词格式、悬空配置链接、历史排序与 DELETE 请求体等用例。格式宽度测试曾触发 MemoryError，随后改成小输入验证同一格式限制，不依赖巨量内存申请暴露问题。

最终 206 项回归在隔离的 T12 完成代码副本上运行为 **186 failed、20 passed**，结果位于 `/home/su/outputs/animeman-t13-baseline.txt`；本卡修复后全部通过。没有修改真实工作区去复现旧缺陷，也没有调用真实 AI/TMDB。提示词网络分支显式 mock，媒体只用 pytest 临时目录小文件/路径字符串，沿用会话级 Requests/socket 阻断。

最终完整 Python **638 passed**（T12 的 432 + 本卡 206），Node **37 passed**（含 T12 的 30 项 Chromium 回归），没有跳过。所有 Python AST、差异与独立补丁反向检查通过；隔离副本正向应用及反向撤回后，涉及文件逐字节恢复到 T12 完成状态。仓库根目录没有生成运行配置、缓存、日志或用户媒体。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short tests/test_input_validation.py
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t00/bin/python npm run test:ui
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T13.patch
```

环境沿用 Linux、Python 3.12.15、pytest 9.2.0；未新增第三方依赖。本卡没有改动前端或模板。

## 未测项与限制

未测 Windows、真实 NAS/Docker、多进程/外部编辑器同时改写配置、断电恢复、真实 AI/TMDB 或真实部署中的 Basic Auth 重新登录。原子性与配置读改写锁保证限定为当前单进程与本地测试文件系统，不据此承诺共享 NAS 或多个 WSGI worker 的事务一致性。

已知业务字段验证不等于外部提供商一定支持某个模型、网络地址一定可达或所有未知扩展键都有业务语义。批量媒体/字幕执行阶段的逐项失败契约没有整体改成跨文件事务；本卡负责输入先验校验，不重做删除或字幕事务。T14 派生缓存/海报身份和 T15 部署/CI 尚未执行。

## 兼容、修复配置与回滚

load_config/save_config 原位置参数和环境路径优先级保留，配置仍是 JSON 对象。合法部分配置可读取；成功保存会补齐默认字段，未知 JSON 扩展键保留。API 仍保留已有秘密字段语义和请求字段，新增严格边界会拒绝旧客户端发送的数字字符串、字符串布尔、越界参数或错误嵌套结构；客户端应提交真正 JSON 数字和布尔。映射不存在/重复现在分别返回 404/409，历史接口不再默默忽略未实现的排序字段。

业务配置损坏时 API 会拒绝访问，需停止写任务，由管理员修复原文件或恢复独立的有效备份后再重试。`.t13-invalid-*` 保存的是无效原件，供诊断或逐字恢复现场，不是可直接投入运行的有效配置版本；不要盲目恢复后当作问题已经修复。悬空配置链接应修复其指向，程序不会自动替换成默认认证关闭的文件。

独立补丁 `/home/su/outputs/AnimeMan-T13.patch` 相对 T12 完成状态生成。停止写任务后先反向检查，再按需整卡反向应用；不要只删除新校验模块或只回退调用方。不要恢复整个仓库，以免丢失 T00–T12 未提交成果；撤回旧卡按 T13 → T12 → T11 的逆序。没有格式迁移需要回滚，代码回滚不删除用户媒体、配置或坏原件备份；回到旧代码会重新引入宽松输入与损坏配置回退风险。本轮所有实际数据写入均在隔离临时目录，没有真实配置/媒体需要恢复。
