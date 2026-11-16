# T09：季集号解析与特典扫描

基线仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`。已检查仓库状态、真实函数和祖先/仓库 AGENTS.md（不存在）。本卡仅在 T00–T08 完成状态上修改，没有提交、推送或发布。

## 行为与改动文件

- `core/parser_regex.py`：区分 None 与 0；SxxExxxx、NxEx/数字 x 格式和方括号/中文集号匹配完整数字，季号支持 0–99、集号 1–9999，超长数字不会截取前缀。中文数词支持含“十”的季号，例如十一；年份与画质不作为无标记尾数集号。只有独立 OVA/OAD/SP 等标记才识别特典，不因 Spirit 含 sp 改写季集。无可靠集号的正则结果为 unknown/episode=None，不合成 E01，也不把真实集号替换成用于占位的 1。
- `core/parser_anitopy.py`：保留零季和未知集号，复用完整显式季号提取；保留原有罗马季号和总集数信息，不在检测总集数时强制把 episode 改成 1。
- `core/processor_core.py`：TV 缺少可信季/集号时返回识别失败，交回现有回退/人工处理，不再在核心层补 S01E01。
- `core/processor_utils.py`、`core/processor_runner.py`：主扫描与离线扫描共用路径、扩展名、忽略词和最小大小规则。新增 scan_policy 默认配置于 `core/config_manager.py`。
- 新增 `tests/test_season_scan.py`，更新 README 和本说明。

## 扫描优先级

```json
{"scan_policy":{"include_specials":false,"exclude_patterns":[]}}
```

隐藏路径、符号链接、显式 exclude_patterns、文件名 ignore_patterns 以及扩展名/大小要求先行。exclude_patterns 使用不区分大小写的 glob，可匹配相对源根目录路径或任一目录/文件部分，例如 `OVA`、`*/OVA/*`。已有 ignore_patterns 继续按文件名整词匹配生效，其默认 SP 等值也不会因开启特典而自动删除。

默认特典目录继续排除；include_specials=true 或命中的启用映射可越过这层默认排除。为使仅匹配文件名的映射有机会生效，存在启用映射时扫描可进入特典目录，随后逐文件检查实际映射。禁用映射不放行。菜单、CD、扫描图等其他默认无关路径仍排除，映射不越过显式排除。源根目录本身的名字不作为其下相对路径的目录排除条件。

没有迁移缓存或修改源/目标媒体，配置字段向后兼容。T10 将进一步为解析缓存加入规则版本；本卡不宣称已解决旧 AI 缓存契约问题。

## 验证

首批 19 项修复前为 **17 failed、2 passed**；修复后本卡 **19 passed**，完整 Python **345 passed**（T08 326 + 19），无跳过。覆盖 S00、E123、方括号集号、超长拒绝、Spirit、中文十一季、无集号及默认/映射/显式排除/开关扫描一致性。媒体全部为临时目录小文件，核心缺集号测试阻断 TMDB；测试会话默认阻断网络。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q tests/test_season_scan.py --tb=short
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T09.patch
```

Python AST、差异及独立补丁反向检查通过。未测 Windows、Docker、真实 NAS、真实媒体识别、真实 AI/TMDB 及前端配置编辑；没有增加扫描开关的表单控件，可通过配置文件设置。

## 回滚

`/home/su/outputs/AnimeMan-T09.patch` 相对 T08 完成状态生成。停下写任务后先反向检查，再按需反向应用；后续 T10 必须先撤销，避免覆盖其对同一函数的修改。代码回滚不恢复/删除缓存或媒体；新的 scan_policy 字段可保留。回滚会恢复本卡的默认集号、零季、截断和过滤不一致问题。
