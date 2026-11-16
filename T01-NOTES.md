# T01：链接缓存路径与删除边界

## 范围与结果

基线为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，在上一轮未提交的 T00 测试基座之上继续修改；沿用 `maintenance/t00-test-foundation` 分支。未提交、推送或发布，未操作真实配置或媒体。

自动电影、自动 TV、手动电影、手动 TV、字幕中心共五处缓存写入现在保存库内目录项的绝对路径，解析父目录但保留末级软链接，不再把目标解析成源文件。新增 `source_path`，原缓存键和 `target` 字段名保持兼容。

单项/批量媒体删除和旧产物清理共用边界验证。目标必须位于相应的配置媒体库中；拒绝空路径、根目录、普通目录、源路径、源目录内目标、父目录软链接逃逸和不一致的缓存源字段。合法硬链接不会因与源文件同 inode 而被拒绝。悬空软链接也能按目录项清理。

删除源文件要求请求字段 `delete_source` 为真正布尔值，只有 `true` 才执行；省略时默认 `false`。源文件路径另行校验源目录范围，失败时在删除目标前拒绝操作。单项路径冲突返回 409；批量响应保留 success/failed 计数，并增加逐项 errors。自动/手动处理和自动字幕的目标删除也经过路径检查。

## 旧缓存保护

在删除或纠错前检查将使用的缓存。发现不安全记录时，先以独占新文件创建完整字节备份 `auto_processed_cache.json.t01-<uuid>.bak`，然后原子保存 `needs_reindex=true` 与 `reindex_reason` 标记。异常类型的记录保存在 `legacy_entry` 中。备份文件已加入 .gitignore。

无法确定原目标的记录采用保守隔离：**不猜测、不自动扫描恢复、不删除源文件**。本卡未实现从源目录反推唯一目标的自动修复。明确标记的记录再次请求不会重复创建备份；新发现的不安全记录会单独备份当时缓存。备份失败则不修改缓存、不执行删除。

单项重试/纠错遇到隔离记录返回 409，批量纠错逐项跳过并保留标记。普通失败记录（media_type=failed）不包含旧产物，仍允许正常纠错处理。

重建方法：先检查配置的源/目标根目录并保留备份；通过现有“仅删除缓存”操作移除已确认需要重建的记录，再重新扫描整理。不要使用“删除媒体文件”代替仅删除缓存。若仍有目标冲突，交给 T02 的冲突处理流程，不直接删除文件。

## 改动文件

- 新增 `core/path_safety.py`：目录项路径规范化、源/目标范围检查与安全异常。
- 修改 `core/cache_manager.py`：删除前备份和隔离旧缓存。
- 修改 `core/file_linker.py`：识别已存在的悬空软链接，保留它并返回失败，避免将其当作空位置。
- 修改 `core/processor_movie.py`、`core/processor_tv.py`、`core/processor_manual.py`、`core/subtitle_handler.py`：五处正确写入 target/source_path，以及目标删除边界。
- 修改 `core/processor_cache_ops.py`：验证后清理目标和关联目录项，统一悬空链接处理。
- 修改 `web/routes_media.py`：安全单项/批量删除、布尔值与源范围验证，接入 T00 指定配置路径。
- 修改 `web/routes_cache.py`、`web/routes_failed.py`：纠错/重试的隔离错误响应，批量保留标记。
- 修改 `.gitignore`；新增 `tests/test_link_safety.py` 和本说明。

## 测试证据

环境沿用 T00：Linux、CPython 3.12.15、pytest 9.2.0，虚拟环境 `/home/su/venvs/animeman-t00`。全部媒体来自 tmp_path；TMDB 详情和季集列表返回本地假响应，网络仍受 T00 的会话级阻断。

先添加测试再修复：初始 T01 测试 **23 failed、10 passed**，暴露五条缓存写入路径错误、悬空链接残留、旧缓存缺少保护、非法删除源标志及目录逃逸等问题。随后添加边界案例，T01 共 46 项。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest tests/test_link_safety.py -q
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q
git diff --check
```

全套结果：**60 passed**，其中 T00 为 14 项，T01 为 46 项。覆盖硬链接、软链接、EXDEV 降级、悬空链接的三类清理入口；五条缓存写入链路；错误/畸形旧记录、备份失败与幂等；父目录逃逸；合法/非法源删除；三个单项纠错入口和批量纠错保留结果。

## 兼容、限制与回滚

新字段是增量字段；目标路径的含义修正为库内目录项。安全旧硬链接记录仍可直接使用；不安全软链接旧记录会被隔离，需重建。源/目标目录重叠时，源目录保护优先，可能阻止原来允许的整理/清理，需要先分开配置。

未测：Windows 实机链接、真实跨盘挂载（EXDEV 已模拟）、Docker、真实 ffmpeg/字幕调轴、真实 AI/TMDB，以及其他任务卡的业务行为。路径检查覆盖静态父目录软链接逃逸，不构成对第三方同时恶意替换目录的系统级沙箱。

T02 的目标冲突保护、失败保留旧成果及共享元数据引用判断尚未实施；T06/T07 的并发任务/缓存事务问题仍存在。T01 通过不代表可以跳过其余 P0 项。

独立补丁：`/home/su/outputs/AnimeMan-T01.patch`，只包含 T01，不含 T00。在当前工作区可先用 `git apply --reverse --check /home/su/outputs/AnimeMan-T01.patch` 验证，再由需要回滚的执行者反向应用；不要直接恢复整个仓库，否则会同时丢掉未提交的 T00。

备份仅用于审计、人工恢复和重建，不要自动把错误旧缓存恢复给旧版本执行删除。回滚代码不会自动撤销已经执行的文件删除；本轮仅在临时测试目录执行删除，无真实数据需要恢复。
