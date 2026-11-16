#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AnimeMan 命令行入口
"""

import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.logger import setup_logging
from core.runtime_paths import config_file, cache_file
from core.process_lock import process_guard
from contextlib import nullcontext
setup_logging()


from core import load_config
from core.media_processor import run_processor_with_callback, stop_processing


def main():
    parser = argparse.ArgumentParser(description='AnimeMan 全自动入库工具')
    parser.add_argument('--config', default=None, help='配置文件路径')
    parser.add_argument('--dry-run', action='store_true', help='只生成整理计划，不写媒体、配置或缓存；可能调用外部 API')
    parser.add_argument('--force-full', action='store_true', help='强制全量处理，忽略增量缓存')
    parser.add_argument('--repair', action='store_true', help='修复模式：补全缺失的 NFO 和图片')
    parser.add_argument('--test-tmdb', action='store_true', help='测试 TMDB 连通性')
    args = parser.parse_args()
    args.config = str(config_file(args.config))
    guard = nullcontext() if args.dry_run else process_guard(cache_file('.animeman-server.lock', check_legacy=False))
    with guard:
        return _run_cli(args)


def _run_cli(args):

    if args.test_tmdb:
        config = load_config(args.config, create_if_missing=not args.dry_run)
        api_key = config["tmdb_api"].get("api_key")
        if not api_key:
            print("❌ TMDB API Key 未配置")
            return
        from core.tmdb_client import create_session
        try:
            url = "https://api.themoviedb.org/3/configuration"
            resp = create_session().get(url, params={"api_key": api_key}, timeout=10)
            if resp.status_code == 200:
                print("✅ TMDB 连接正常")
            else:
                print(f"❌ TMDB 连接失败: HTTP {resp.status_code}")
        except Exception as e:
            print(f"❌ 连接异常: {e}")
        return

    overrides = {}
    if args.dry_run:
        overrides['dry_run'] = True
    if args.force_full:
        overrides['incremental'] = False

    def console_log(cur, tot, msg, level):
        print(f"[{level.upper()}] {msg}")

    try:
        run_processor_with_callback(args.config, console_log, repair_mode=args.repair,
                                    config_overrides=overrides)
    except KeyboardInterrupt:
        print("\n⏹️ 收到中断信号，正在安全停止任务...")
        stop_processing.set()  # 通知处理器停止
        print("✅ 任务已停止，缓存已保存。")
        sys.exit(0)


if __name__ == '__main__':
    main()
