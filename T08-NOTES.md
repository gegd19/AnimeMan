# T08：NFO、图片与完整修复流程

## 范围与结果

基线仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支为 `maintenance/t00-test-foundation`。已核对当前 git 状态、任务书 T08 和涉及的实际函数；仓库及祖先目录均没有 AGENTS.md。本卡叠加于未提交的 T00–T07，没有提交、推送、发布或访问真实用户媒体/密钥。

本次仅修改 NFO、图片验证、单集侧车路径及 repair 所需逻辑。复用 T01 路径校验、T02 发布事务、T06 取消上下文和 T07 文件锁/备份；未执行 T09–T15。

## 修复行为

XML 节点现在接收原始文本，由 ElementTree 序列化转义一次。电影、剧集和单集的 title/plot 等字段经过 XML 解析后与原始输入相等，包括 `A & B <特别篇>`、引号和中文。可解析且根元素符合对应 NFO 类型的既有文件保持原样，避免覆盖用户自定义内容。

新增 `core/media_paths.py`，自动整理和人工纠错共用同一单集视频路径生成函数。单集 NFO 使用实际 `video_path.with_suffix('.nfo')`，不再用另一个标题规则重建文件名。添加年份和有/无单集标题的组合均与视频同 stem。repair 使用缓存中已有的视频路径，不重命名、重新链接或改写视频；历史自定义命名也可补齐侧车文件。

repair 遍历每个缓存电影/剧集条目，按剧目录处理共享 tvshow.nfo/图片，按季补 season.nfo，按每集补对应 NFO。详情在本次修复内按媒体类型/ID 复用，季集列表按 ID/季号复用，避免每集重复请求。图片下载在手动纠错和 repair 中均传递配置的 proxy；自动分支继续保留已有代理支持。

repair 返回 repaired/planned/skipped/failed/errors 汇总，runner 转发该结果。模拟修复验证和规划缺失/无效的电影、剧集、季、集 NFO 及图片，不调用写入函数，不生成暂存、备份或缓存变化。

## 原子写入、验证与保护

新增 `core/metadata_io.py`：按最终文件路径加进程内锁，NFO 从验证、可选 AI 润色到发布持有同一把锁，图片从检查到下载/发布持锁。发布事务也使用相同路径锁，既有文件检查和独占创建遇到 FileExistsError 后都会重新验证。

NFO 需要能够解析且根元素匹配 movie/tvshow/season/episodedetails；空文件、截断 XML 和错误根元素不再因 exists 而被当作有效。图片使用新增依赖 `Pillow>=12,<14` 验证结构并重新打开加载像素，拒绝空响应、HTML 错误页和截断图片。实现遵循 [Pillow Image 接口文档](https://pillow.readthedocs.io/en/stable/reference/Image.html)：open 是延迟读取，不能仅把成功识别头部当作已解码成功。

元数据先写入同目录唯一临时文件，flush/fsync、验证成功且未取消后才 os.replace 发布。失败清理临时文件，保留原路径原内容；新文件遵循 umask，替换既有文件保留其权限。替换无效旧文件之前创建 `.t08-<内容哈希>.bak`，相同内容可复用核实一致的备份。备份失败会阻止替换。

普通整理保持 T02 不覆盖既有产物的策略：发布同名元数据时检查有效性，遇到无效旧 NFO/图片则拒绝该次提交、撤回本次新建产物并提示先运行 --repair。显式 repair 或直接 NFO 写入才会在备份后替换无效文件。图片下载失败返回失败并保留原状；图片是可选元数据，不代表视频整理一定随之失败。

repair 校验缓存目标和每个侧车文件的库目录边界，拒绝目标等于源路径、源目录内目标、逃逸路径和需要重建的记录。侧车文件若与源/视频同 inode，拒绝替换；无效侧车符号链接也不自动替换。缺少可信季/集号或 TMDB 缺少对应单集时，停止该条目的相关子步骤并列出错误，不推断 S01E01、不创建占位 NFO。其他安全条目可以继续修复。

## 兼容与限制

NFO 写入函数原有位置参数保持可用；write_episode_nfo 新增可选关键字 video_path，仓库内部自动、人工和修复入口全部传入实际路径。只有目录的旧式外部调用无法得知实际视频名，仍按共享规则生成不含已知年份的默认名字，建议传入 video_path。写入函数现在返回是否实际写入的布尔值，旧调用可继续忽略返回值。

不会批量重写已可解析的旧 NFO，包括历史上已经双重转义的文本，也不会删除旧的错名单集 NFO。需要重建这类旧文件时，应先停下相关写任务、保留备份，再明确选择移开哪份旧 NFO 后执行 repair。本卡不猜测哪些旧文件可以删除，不迁移缓存或修改历史所有权清单；无明确所有权的旧元数据清理仍遵循 T02 的保守策略。

依赖已安装在既有独立虚拟环境，实际验证版本为 Pillow 13.0.0。其他安装环境需要重新安装 requirements.txt；Docker 构建会通过现有流程安装该新增依赖，本次没有构建或发布镜像。

文件锁只协调同一进程，多个服务/CLI 进程仍应避免同时写同一个库。原子替换和故障注入测试不等于已经验证断电/NAS 文件系统的全部持久性行为。

## 改动文件

- 新增 `core/media_paths.py`、`core/metadata_io.py`。
- `core/nfo_writer.py`：原始 XML 文本、同名校验、单集实际路径、锁与原子写入。
- `core/processor_tv.py`、`core/processor_manual.py`：共用单集路径、传入实际视频路径、人工图片代理。
- `core/processor_repair.py`、`core/processor_runner.py`：完整逐集修复、路径保护、模拟规划和结果汇总。
- `core/tmdb_client.py`：图片解码验证、缓存有效性检查和原子发布。
- `core/library_transaction.py`：同名元数据验证、发布竞争复检及路径锁。
- `requirements.txt`：Pillow 依赖。
- 新增 `tests/test_metadata_repair.py`；README 和本说明。

## 测试与验证

先编写首批 22 项回归：修复前 **20 failed、2 passed**，分别暴露重复转义、含年份/无标题命名不一致、缺少季/集修复、漏传代理、无效缓存被跳过和非原子写入。随后补充源路径/inode 冲突、发布竞争、序列化/替换/备份失败、取消、模拟与符号链接修复保护。

T08 共 **34 项 Python 回归测试**，完整套件 **326 passed**（T07 的 292 + 34），Node **7 passed**。没有跳过测试，也没有真实 AI/TMDB 请求。所有媒体均为临时目录内的小文件；图片为测试内构造的 1×1 PNG；AI 润色被禁用或 mock，整个 pytest 会话阻断 Requests/socket。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q tests/test_metadata_repair.py --tb=short
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
node --test tests/config_ui.cjs tests/task_ui.cjs tests/confidence_ui.cjs
uv pip check --python /home/su/venvs/animeman-t00/bin/python
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T08.patch
```

另检查 core/web/tests 全部 Python AST。仓库根目录没有生成运行配置、缓存、日志、临时文件或媒体。环境为 Linux、Python 3.12.15、pytest 9.2.0、Pillow 13.0.0；依赖一致性检查通过。

未测 Windows、Docker、真实 NAS/跨盘存储、真实 Emby/Jellyfin 媒体扫描、真实代理/AI/TMDB、真实媒体和字幕调轴，以及浏览器端到端交互。图片解码验证测试使用 PNG；真实 JPEG/WebP 等格式和各种部署平台仍需集成验证。

## 使用与回滚

在只有一个写进程访问同一媒体库的前提下运行修复：

```bash
python main.py --config /path/to/auto_config.json --repair --dry-run
python main.py --config /path/to/auto_config.json --repair
```

独立补丁 `/home/su/outputs/AnimeMan-T08.patch` 相对于 T07 完成状态生成，已通过反向检查。停止所有写任务后，先执行反向检查，再按需反向应用本卡补丁；多卡按 T08 → T07 → T06 倒序撤销，避免丢失前卡未提交修改。

代码回滚不自动回滚元数据文件，不删除备份、视频或缓存。若要恢复被替换的旧无效元数据，应停服后核对具体路径和 `.t08-*` 备份再选择恢复；这些备份保留的是替换前内容，可能仍然无效。新建的正确同名单集 NFO 不应未经核对批量删除。Pillow 可以继续保留在独立虚拟环境，回滚后不再由代码使用；不要修改系统 Python。

本轮真实写入仅发生在隔离测试目录，无用户媒体需要恢复。回滚会重新引入本卡修复的转义、命名、修复缺项和半文件缓存问题。
