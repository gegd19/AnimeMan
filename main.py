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
setup_logging()

logging.basicConfig(
    filename="auto_processor_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from core import load_config
from core.media_processor import run_processor_with_callback, stop_processing


def main():
    parser = argparse.ArgumentParser(description='AnimeMan 全自动入库工具')
    parser.add_argument('--config', default='auto_config.json', help='配置文件路径')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，不实际创建链接')
    parser.add_argument('--force-full', action='store_true', help='强制全量处理，忽略增量缓存')
    parser.add_argument('--repair', action='store_true', help='修复模式：补全缺失的 NFO 和图片')
    parser.add_argument('--test-tmdb', action='store_true', help='测试 TMDB 连通性')
    args = parser.parse_args()

    if args.test_tmdb:
        config = load_config(args.config)
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

    config = load_config(args.config)
    if args.dry_run:
        config['dry_run'] = True
    if args.force_full:
        config['incremental'] = False

    def console_log(cur, tot, msg, level):
        print(f"[{level.upper()}] {msg}")

    try:
        run_processor_with_callback(args.config, console_log, repair_mode=args.repair)
    except KeyboardInterrupt:
        print("\n⏹️ 收到中断信号，正在安全停止任务...")
        stop_processing.set()  # 通知处理器停止
        print("✅ 任务已停止，缓存已保存。")
        sys.exit(0)


if __name__ == '__main__':
    main()
