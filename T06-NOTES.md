# T06：任务互斥、停止与身份隔离

## 范围与结果

基线仍为 `f0feb4667f1cf7349e3c60fc85cea6709c895ab7`，分支 `maintenance/t00-test-foundation`；修改叠加在未提交的 T00–T05 上。已检查当前 git 状态、任务涉及的真实函数和仓库及祖先目录的 AGENTS.md（不存在）。本轮只执行 T06 及接通取消、互斥所需的入口，没有提交、推送或发布。

`web/task_state.py` 现在在同一把锁下领取写任务名额，分配独立 task_id、停止 Event、配置快照与线程句柄。自动整理、批量纠错、离线扫描/解析和海报刷新通过统一入口启动；单项纠错/重试、媒体删除、处理缓存增删和字幕写入通过请求作用域领取同一个名额。冲突返回 409。读请求及配置保存仍可执行，已有任务继续使用启动时的配置快照。

状态包含 idle、running、stopping、completed、failed、cancelled。进度、日志和完成回调绑定任务 ID；过期回调、完成和带旧 ID 的停止/重置不会改变新任务。后台线程即便已经设置 done，只要仍然存活就继续占用名额。同步请求在操作与响应处理完成后释放，异常时由 teardown 兜底释放。

停止只设置本任务的 Event。`force=1` 对活线程或未完成的同步任务返回 409，保持 stopping；只清理已确认无工作线程的残留状态。前端取消双击强制重置，停止后保持运行按钮禁用、继续轮询，结束后保留计数和日志。状态消息按文本显示。

## 取消与持久化边界

新增 `core/cancellation.py`，用 ContextVar 传递取消上下文；每次线程池提交分别复制上下文。保留 stop_processing 的 set/clear/is_set/wait 接口兼容旧调用，但管理任务的 Event 不会被 clear 撤销。独立旧式库调用如需重复运行，应在任务作用域外主动清理自己的旧停止信号。

扫描逐项检查取消，扫描期间的停止不会被重新 clear。文件夹解析等待每 0.1 秒检查一次；TMDB 限速和 429 等待可以被 Event 唤醒。AI 请求开始前、响应后，以及元数据、图片、链接、字幕提交点检查取消。取消作为独立异常向外传播，不记为识别失败。

整理队列最多保留 `2 * max_workers` 个 future。收到停止后停止补充、取消未开始的工作，等待并收集所有已开始 worker 的结果，再保存最终处理缓存。保留每 10 个成功项的周期保存。返回成功、失败、已处理、总数、取消标志及最多 10 项错误摘要；取消结果与成功完成分开。批量纠错在后续条目取消时保留前面成功项的计数。

T02 的暂存事务在发布前、每个产物发布前和缓存提交前检查取消。尚未提交的取消撤回本次新建的发布文件，保留旧目标、旧缓存与源文件；已经持久化的条目完成必要清理。批量媒体删除以一个条目为边界，完成该条目的删除与缓存变更后再停止后续条目，防止已删除文件仍留在旧缓存里。原有源文件保护和旧缓存备份规则继续生效。

已经进入的 Requests 调用、ffmpeg/ffsubsync 子进程与单个文件系统操作仍需等待返回或现有超时；不强杀线程。等待期间状态保持 stopping，服务器拒绝新写任务。本卡未实现跨进程锁，生产环境仍须由一个写进程管理同一媒体库；多个 CLI/服务进程的协调属于后续部署工作。

## 改动文件

- 新增 `core/cancellation.py`：独立取消上下文、兼容停止信号、可取消等待。
- `web/task_state.py`、`web/routes_task.py`、`web/app.py`：原子任务领取、身份、生命周期、同步请求名额与状态接口。
- `web/routes_failed.py`、`web/routes_cache.py`、`web/routes_media.py`、`web/routes_subtitle.py`：配置快照、纠错计数、删除取消边界、取消异常传播。
- `web/routes_offline.py`、`web/routes_config.py`：后台任务统一入口与状态收尾。
- `core/processor_runner.py`、`core/processor_core.py`：有界提交、停止扫描/补充、排空结果与最终保存。
- `core/library_transaction.py`、`core/processor_movie.py`、`core/processor_tv.py`、`core/processor_manual.py`：发布与纠错提交检查、取消传播。
- `core/ai_client.py`、`core/parser_manager.py`、`core/tmdb_client.py`、`core/offline_ai_preparser.py`：请求与等待取消检查。
- `core/file_linker.py`、`core/nfo_writer.py`、`core/processor_repair.py`、`core/subtitle_handler.py`：写入及逐项处理边界。
- `static/js/task.js`：停止期间按钮与轮询、终态计数。
- 新增 `tests/test_task_lifecycle.py`、`tests/task_ui.cjs`；更新 `tests/test_app_config.py` 的 runner mock 以接受快照参数。
- README 和本说明。

## 测试证据

首批 18 项回归测试在修复前全部失败，暴露任务领取不原子、活线程被强制释放、扫描取消丢失、配置快照缺失和写入入口不互斥。随后补充后台入口、旧停止身份、同步操作阻塞、线程启动失败、退出尾声、发布后回滚、批量删除保存与纠错计数等测试；新补充的缺陷均先复现再修复。

T06 为 **33 项 Python 回归测试**。完整套件 **239 passed**（T05 的 206 + 本卡 33），Node **6 passed**（原有 4 + 任务界面 2），无跳过测试。事件与 Barrier 控制并发时序，没有随机 sleep。线程测试均有释放、等待和状态清理。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q tests/test_task_lifecycle.py --tb=short
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t00/bin/python -m pytest -q --tb=short
node --test tests/config_ui.cjs tests/task_ui.cjs
node --check static/js/task.js
git diff --check
git apply --reverse --check /home/su/outputs/AnimeMan-T06.patch
```

Linux、Python 3.12.15、pytest 9.2.0。另检查所有 core/web/tests Python 的 AST。媒体全部为临时目录内的小文件，AI/TMDB 均 mock；整个 pytest 会话阻断真实 Requests/socket。仓库根目录没有生成运行配置、缓存、日志或媒体。

未测 Windows、Docker/进程重启、真实 NAS/跨盘介质、真实 AI/TMDB、真实字幕调轴以及浏览器端到端交互；前端使用 Node VM、假 DOM 和 fetch。缓存原子事务、离线缓存旧快照覆盖、AI 输出有效性、字幕覆盖和源字幕调轴保护继续按 T07/T10/T11 处理，本卡不宣称修复这些既有问题。

## 兼容与回滚

旧 runner 位置参数、repair_mode 和 T05 的 config_overrides 仍可用，新增可选 effective_config 供 Web 传入启动快照；不会把快照写回配置。原有状态字段保留，新增 task_id/status/kind/result。停止接口仍支持不带 ID 的旧客户端，建议新客户端携带 task_id；force=1 的活任务响应从立即重置改为 409。离线启动仍返回 success，海报刷新和纠错仍返回 started，额外带任务 ID；并发冲突统一 409。

没有数据格式迁移，没有写入真实配置、缓存或媒体。独立补丁 `/home/su/outputs/AnimeMan-T06.patch` 相对于 T05 完成状态生成，已通过反向检查。需要回滚时先确认没有运行任务，执行 `git apply --reverse --check`，再反向应用本卡补丁；多卡应按 T06 → T05 → T04 的倒序撤销，避免覆盖前卡的未提交工作。回滚会恢复旧的并发与停止缺陷。
