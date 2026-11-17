# AnimeMan v1.3.1 发布复核

基线：`8056e79`（v1.3.0 加 README 更新）。两个用户附件内容完全一致，各自包含同样的两项修复，仅合入一次。共同 SHA-256：`1806e28ab0a497022fb04449ff9d02eff0756b813dec3938e087f3faa0d07737`。

## 行为

- `core/parser_manager.py`：分清点分隔的分辨率/位深与小数集号。`S01E02.1080p`、`.2160p`、`.720p`、`.480p`、`.4K`、`.10bit` 可继续本地解析；真正小数集号及多集范围仍待明确映射，不截断成整数集号。
- `core/processor_core.py`：自动识别只命中已核验 TMDB 备用标题、详情包含多个普通季时，无明确季号或标题带续作标记均转人工确认季号。无后续 AI 猜测覆盖此决定。主标题匹配、单普通季以及已确认人工身份路径的原有规则保留；单凭备用标题不建立新的季集换算。
- 相应测试：`tests/test_recognition_numbering.py`、`tests/test_recognition_detail_aliases.py`。
- 额外审查修复：移除附件对小数最多两位的限制，防止 `12.125` 误当普通集；补足续作标记 V/X。未通过跳过测试或强设评分解决失败。

## 验证

先只加入附件测试，旧基线复现 8 个失败（6 个点分隔技术后缀、2 个备用标题季号问题）。原附件修复后相关 50 项通过；再加入 3 位小数和 V/X 回归，在原附件代码上复现 10 个失败。最小修正后相关 60 项通过。

使用锁定 Python 3.12 虚拟环境及现有 Chromium/Playwright：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t15-locked/bin/python -m pytest -q --tb=short
CHROMIUM_PATH=/usr/bin/chromium ANIMEMAN_TEST_PYTHON=/home/su/venvs/animeman-t15-locked/bin/python npm run test:ui
/home/su/venvs/animeman-t15-locked/bin/python tools/check_syntax.py
PYTHONDONTWRITEBYTECODE=1 /home/su/venvs/animeman-t15-locked/bin/python tools/evaluate_recognition_identity.py --output /tmp/animeman-v131-approved-evaluation.json --source-revision 67d9c70
git diff --check
```

- Python 1038 项通过；UI 93 项通过，0 失败、0 跳过；Python 136 文件语法及 diff 检查通过。
- 固定离线样本 AI 开/关 × 冷/热：18 个正确自动处理、31 个待确认、0 个不安全自动处理、0 个运行时错误。原字面 R10 门槛仍因 C46/C49 记为未通过；用户批准的证据条件口径四组均通过，没有改动样本、答案或历史分数。
- 媒体、缓存、配置使用临时目录，AI/TMDB/ffprobe mock，不读取真实密钥和用户媒体。
- `core/tmdb_client.py`、`core/failure_policy.py`、`core/config_manager.py` 与基线无差异；TMDB 间隔、RateLimiter、HTTP 重试/退避、429 等待及 failure_retry 均未改变。

附件说明中有关“200 BT 文件真实 TMDB 运行”的数量不是本次验证结论。该研究集已有错误参考答案，尚未完成逐条真值审核；本版不采用其中的季集值，也不宣称解决其全部错配。

## 兼容、升级与回滚

无依赖、接口或缓存格式迁移。源文件保护、事务、取消、模拟模式及停机等待策略保持原样。已有失败记录不会被自动删除，升级后可按需人工重试；不清空缓存来掩盖问题。

先停任务并等待写线程真实退出，备份配置/缓存后再更新源码或重建镜像。回滚恢复 v1.3.0（需保留新 README 时使用 `8056e79`），或逆序撤回本次两项代码提交；不自动删除媒体、恢复旧规则或覆盖缓存。旧版会重新出现本次修复的问题。

未测真实 AI/TMDB、真实媒体/NAS、Safari/Firefox、手机实机或读屏效果。远端 Linux/Docker/Windows 发布检查以本提交的 GitHub Actions 为准。本次仅推送和发布 GitHub 正式版本，不更新或重启本机服务，不发布容器镜像。
