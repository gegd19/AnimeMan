# AnimeMan v1.3.2 发布复核

基线：v1.3.1（`ffa3d38`）。仅合入独立新增附件 `animeman-v1_3-fix-batch-resolution.diff`，不重复应用累积包中的两项旧后端修复。输入附件 SHA-256：`776e8fa4c174568b168c513773d0f4b3110fb8329b459a6810eb5b031f6aaf30`。

## 改动与行为

- `static/js/batchCorrection.js`、`static/js/processedCache.js`：`NxM` 季集模式不再从 `640x480`、`1280x720` 等分辨率中截取数字；`1x05` 正确提取为第 5 集。批量智能排序和提取起始集号使用正确的集号。
- 审查补充：已处理缓存的排序调用传入 `{path, name, reason}`，原辅助函数却读取 `src_name`，会在多条选择时对 undefined 调用 match。辅助函数改为使用真实传入的 `name` 字段，不改变原始源路径。
- `tests/shell_ui.cjs`：附件回归验证批量窗口的排序、起始集号；新增真实已处理缓存入口回归，验证勾选后排序、源路径保留、起始集号、无异常且不发写请求。

## 隔离回归与结果

先只加入附件测试，在旧代码上复现排序不生效（输入 17、13、21、14 未变成 13、14、17、21）。应用附件后该测试通过；新增已处理缓存入口测试复现 `Cannot read properties of undefined (reading 'match')`，再做最小字段修正。两项针对性回归最终均通过。

```bash
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t15-locked/bin/python node --test --test-name-pattern='batch correction reads episode numbers past resolutions|processed cache passes selected names' tests/shell_ui.cjs
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t15-locked/bin/python npm run test:ui
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t15-locked/bin/python -m pytest -q --tb=short
node --check static/js/batchCorrection.js
node --check static/js/processedCache.js
node --check tests/shell_ui.cjs
git diff --check
```

- UI 95 项通过，Python 1038 项通过，0 失败、0 跳过；修改的 JS/CJS 语法检查与 diff 检查通过。
- 全部使用临时合成媒体/配置及 mock 接口，不读取真实密钥或用户媒体。新增前端回归无写入请求。
- `core/`、`web/`、依赖锁文件与基线无差异。TMDB 间隔、RateLimiter、HTTP 重试/退避、429 等待、failure_retry 均未改变。
- 未执行真实媒体、真实 AI/TMDB、真实 NAS、Safari/Firefox、手机实机或读屏验证。远端 Linux/Docker/Windows 检查以本提交的 GitHub CI 为准。

## 兼容与回滚

无接口、配置或缓存格式变化，无数据迁移。既有源文件保护、事务、取消、模拟和人工确认语义保持不变。更新前按 DEPLOYMENT.md 停任务、等待写线程真实退出、备份配置/缓存，再更新源码或重建镜像。回滚恢复 v1.3.1 代码或撤回本次提交，不自动删除媒体、覆盖缓存或撤销先前已确认执行的批量操作。

本次仅推送和发布 GitHub 正式版本，不更新或重启本机服务，不发布容器镜像，旧版本标签保持不变。
