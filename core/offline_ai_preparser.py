#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线 AI 预解析器（按需触发模式）
用法：
    python -m core.offline_ai_preparser --scan     # 仅扫描生成原始缓存
    python -m core.offline_ai_preparser --parse    # （可选）强制全量预解析
    python -m core.offline_ai_preparser --all      # 扫描+全量解析
优化：长剧集分析时限制文件数量（最多50个）
"""

import json
import time
import argparse
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from . import config_manager
from . import ai_client
from .processor_utils import is_video_file

RAW_CACHE_FILE = "raw_scan_cache.json"
AI_PREPARSE_CACHE_FILE = "ai_preparse_cache.json"
DEFAULT_MAX_FILES_PER_FOLDER = 30
LONG_SERIES_THRESHOLD = 50
MAX_FILES_FOR_LONG_SERIES = 50  # 长剧集分析时最多取 50 个文件


def scan_source_folders(config: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """扫描源文件夹，返回按文件夹分组的文件信息"""
    result = {}
    video_extensions = [ext.lower() for ext in config.get("video_extensions", [])]

    for src_folder in config.get("source_folders", []):
        root = Path(src_folder)
        if not root.exists():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if not is_video_file(file_path, config):
                continue

            folder_key = str(file_path.parent.resolve())
            if folder_key not in result:
                result[folder_key] = []
            result[folder_key].append({
                "path": str(file_path.resolve()),
                "name": file_path.name,
                "size": file_path.stat().st_size
            })

    return dict(sorted(result.items(), key=lambda item: len(item[1]), reverse=True))


def save_raw_cache(data: Dict[str, Any], path: str = RAW_CACHE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_raw_cache(path: str = RAW_CACHE_FILE) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ai_preparse_cache(cache: Dict[str, Any], path: str = AI_PREPARSE_CACHE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def load_ai_preparse_cache(path: str = AI_PREPARSE_CACHE_FILE) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_folder_on_demand(
    folder_path: Path,
    config: Dict[str, Any],
    max_files_per_folder: int = DEFAULT_MAX_FILES_PER_FOLDER,
    log_func: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    按需解析指定文件夹，调用 AI 并更新缓存。
    优化：长剧集分析时限制文件数量
    """
    ai_cache = load_ai_preparse_cache()
    folder_key = str(folder_path.resolve())

    if folder_key in ai_cache:
        if log_func:
            log_func(f"📦 文件夹 AI 缓存已存在，跳过解析: {folder_path.name}", "info")
        return ai_cache[folder_key]["parse_result"]

    raw_data = load_raw_cache()
    files = raw_data.get(folder_key)
    if not files:
        video_files = []
        for ext in config.get("video_extensions", []):
            for f in folder_path.glob(f"*{ext}"):
                if is_video_file(f, config):
                    video_files.append(f)
        if not video_files:
            return None
        files = [{"path": str(f.resolve()), "name": f.name} for f in video_files]

    file_count = len(files)

    if log_func:
        log_func(f"🤖 按需 AI 解析文件夹: {folder_path.name} ({file_count} 个文件)", "info")

    try:
        if file_count >= LONG_SERIES_THRESHOLD:
            if log_func:
                log_func(f"📊 长剧集模式，使用宏观分析", "info")
            # 限制参与分析的文件数量，取首尾各一半，共不超过 MAX_FILES_FOR_LONG_SERIES
            if len(files) > MAX_FILES_FOR_LONG_SERIES:
                half = MAX_FILES_FOR_LONG_SERIES // 2
                sample_files = files[:half] + files[-half:]
            else:
                sample_files = files
            result = ai_client.parse_long_running_series(
                folder_path,
                [Path(f["path"]) for f in sample_files],
                config,
                log_func
            )
        else:
            files_to_analyze = files[:max_files_per_folder]
            result = ai_client.parse_folder_with_ai(
                folder_path,
                [Path(f["path"]) for f in files_to_analyze],
                config,
                log_func
            )

        if result:
            ai_cache[folder_key] = {
                "parse_result": result,
                "updated": time.time(),
                "file_count": file_count
            }
            save_ai_preparse_cache(ai_cache)
            if log_func:
                log_func(f"✅ AI 解析完成: {folder_path.name}", "success")
            return result
        else:
            if log_func:
                log_func(f"⚠️ AI 返回空结果: {folder_path.name}", "warning")
            return None
    except Exception as e:
        if log_func:
            log_func(f"❌ AI 解析失败: {folder_path.name} - {e}", "error")
        return None


def run_ai_preparse(
    config: Dict[str, Any],
    max_files_per_folder: int = DEFAULT_MAX_FILES_PER_FOLDER,
    log_func: Optional[Any] = None
) -> Dict[str, Any]:
    """全量预解析（保留用于可选的全量场景）"""
    raw_data = load_raw_cache()
    if not raw_data:
        if log_func:
            log_func("❌ 未找到 raw_scan_cache.json，请先运行扫描 (--scan)", "error")
        return {}

    ai_cache = load_ai_preparse_cache()
    total_folders = len(raw_data)
    processed = 0
    success = 0

    for folder_path, files in raw_data.items():
        processed += 1
        if folder_path in ai_cache:
            continue
        folder_obj = Path(folder_path)
        result = parse_folder_on_demand(folder_obj, config, max_files_per_folder, log_func)
        if result:
            success += 1
        if processed % 10 == 0:
            save_ai_preparse_cache(ai_cache)

    save_ai_preparse_cache(ai_cache)
    return ai_cache


def main():
    parser = argparse.ArgumentParser(description="离线 AI 预解析工具（按需模式）")
    parser.add_argument("--scan", action="store_true", help="仅扫描源文件夹，生成 raw_scan_cache.json")
    parser.add_argument("--parse", action="store_true", help="全量预解析（可选）")
    parser.add_argument("--all", action="store_true", help="扫描 + 全量解析")
    parser.add_argument("--config", default="auto_config.json", help="配置文件路径")
    args = parser.parse_args()

    config = config_manager.load_config(args.config)

    def console_log(msg, level="info"):
        print(f"[{level.upper()}] {msg}")

    if args.scan or args.all:
        console_log("🔍 开始扫描源文件夹...", "info")
        raw = scan_source_folders(config)
        save_raw_cache(raw)
        total_files = sum(len(v) for v in raw.values())
        console_log(f"✅ 扫描完成，共 {len(raw)} 个文件夹，{total_files} 个视频文件", "success")

    if args.parse or args.all:
        if not config.get("ai_parser", {}).get("enabled"):
            console_log("❌ AI 解析未启用", "error")
            return
        console_log("🤖 开始全量 AI 预解析...", "info")
        run_ai_preparse(config, log_func=console_log)


if __name__ == "__main__":
    main()
