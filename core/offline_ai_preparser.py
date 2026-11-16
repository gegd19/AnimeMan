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

from .json_store import read_json, write_json, update_json, CacheCorruptionError
from .cancellation import check_cancelled, ProcessingCancelled
import json
import time
import argparse
import re
from pathlib import Path
from .execution_mode import skip_preview_write,is_preview
from .runtime_paths import cache_file, config_file, writable
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
            check_cancelled()
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


@skip_preview_write
def save_raw_cache(data: Dict[str, Any], path=None):
    check_cancelled()
    path = Path(path).absolute() if path is not None else cache_file(RAW_CACHE_FILE)
    write_json(path, data)


def load_raw_cache(path=None) -> Dict[str, Any]:
    return read_json(Path(path).absolute() if path is not None else cache_file(RAW_CACHE_FILE))


@skip_preview_write
def save_ai_preparse_cache(cache: Dict[str, Any], path=None):
    check_cancelled()
    path = Path(path).absolute() if path is not None else cache_file(AI_PREPARSE_CACHE_FILE)
    write_json(path, cache)


def load_ai_preparse_cache(path=None) -> Dict[str, Any]:
    return read_json(Path(path).absolute() if path is not None else cache_file(AI_PREPARSE_CACHE_FILE))


def get_cached_preparse(folder_path,config):
    from . import parse_identity
    from .parse_contract import normalize_folder
    identity,files=parse_identity.folder_snapshot(folder_path,config)
    entry=load_ai_preparse_cache().get(str(Path(folder_path).resolve()),{})
    if not isinstance(entry,dict) or entry.get('_schema')!=parse_identity.RULE_VERSION or entry.get('identity')!=identity:return None
    return normalize_folder(entry.get('parse_result'),folder_path,files) or None


def parse_folder_on_demand(folder_path,config,max_files_per_folder=DEFAULT_MAX_FILES_PER_FOLDER,log_func=None):
    from . import parse_identity,parser_manager
    from .parse_cache import update_record
    from .parse_contract import normalize_folder
    check_cancelled();folder_path=Path(folder_path)
    with parse_identity.identity_scope():
        cached=get_cached_preparse(folder_path,config)
        if cached:return cached
        identity,files=parse_identity.folder_snapshot(folder_path,config)
        if not files:return None
        result=parser_manager._get_or_wait_folder_parse(folder_path,config,log_func)
        result=normalize_folder(result,folder_path,files)
        if not result:return None
        if not is_preview():
            check_cancelled()
            update_record(cache_file(AI_PREPARSE_CACHE_FILE),str(folder_path.resolve()),{
                '_schema':parse_identity.RULE_VERSION,'identity':identity,'parse_result':result,
                'updated':time.time(),'file_count':len(files)})
        return result


def run_ai_preparse(config,max_files_per_folder=DEFAULT_MAX_FILES_PER_FOLDER,log_func=None):
    from .parse_identity import identity_scope
    with identity_scope():
        for folder in load_raw_cache():
            check_cancelled()
            parse_folder_on_demand(Path(folder),config,max_files_per_folder,log_func)
        return load_ai_preparse_cache()


def preparse_summary(config):
    from .parse_identity import identity_scope
    complete=partial=parsed=unparsed=0
    raw=load_raw_cache()
    with identity_scope():
        for folder,listed in raw.items():
            result=get_cached_preparse(Path(folder),config)
            if result:
                parsed+=len(result['files']);unparsed+=len(result['unparsed_files'])
                if result['unparsed_files']:partial+=1
                else:complete+=1
            else:unparsed+=len(listed)
    return {'success':complete,'failed':len(raw)-complete,'total':len(raw),'partial':partial,
            'files_parsed':parsed,'files_unparsed':unparsed}


def main():
    parser = argparse.ArgumentParser(description="离线 AI 预解析工具（按需模式）")
    parser.add_argument("--scan", action="store_true", help="仅扫描源文件夹，生成 raw_scan_cache.json")
    parser.add_argument("--parse", action="store_true", help="全量预解析（可选）")
    parser.add_argument("--all", action="store_true", help="扫描 + 全量解析")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args()

    args.config = str(config_file(args.config))
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
