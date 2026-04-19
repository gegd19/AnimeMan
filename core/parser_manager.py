#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一解析入口，管理各种解析器的调用顺序和缓存（含并发锁）"""

import re
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from . import cache_manager
from . import ai_client
from . import folder_ai_cache
from .cache_manager import ai_parse_cache_lock
from .parser_helpers import (
    get_ai_parse_cache_key,
    get_video_files_in_folder,
    clean_parent_dir_name
)
from .parser_anitopy import parse_with_anitopy, ANITOPY_AVAILABLE
from .parser_regex import parse_with_regex
from .offline_ai_preparser import (
    load_ai_preparse_cache,
    parse_folder_on_demand,
    load_raw_cache
)

LOG_INFO = "info"
LOG_SUCCESS = "success"

# 内存缓存
AI_CACHE: Dict[str, Dict] = {}
_ai_parse_persistent_cache = cache_manager.load_ai_parse_cache()

# ========== 优化项13：并发请求锁 ==========
_ongoing_folder_parses = {}
_ongoing_lock = threading.Lock()


def _save_parse_result(cache_key: str, result: Dict[str, Any]):
    with ai_parse_cache_lock:
        AI_CACHE[cache_key] = result.copy()
        _ai_parse_persistent_cache[cache_key] = result.copy()
        cache_manager.save_ai_parse_cache(_ai_parse_persistent_cache)


def _generate_episode_info_from_macro_rules(
    file_path: Path,
    rules: Dict[str, Any],
    stats: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[Dict[str, Any]]:
    """根据宏观规则为单个文件生成本地解析信息"""
    filename = file_path.name

    ep_num = None
    match = re.search(r'第\s*(\d{1,4})\s*[集話话]', filename)
    if match:
        ep_num = int(match.group(1))
    else:
        match = re.search(r'[Ss]\d{1,2}[Ee](\d{1,4})|(\d{1,3})[xX](\d{1,3})', filename)
        if match:
            ep_num = int(match.group(1) or match.group(3))
        else:
            match = re.search(r'\b(\d{1,4})\b', Path(filename).stem)
            if match:
                num = int(match.group(1))
                if 1 <= num <= 2000:
                    ep_num = num
    if ep_num is None:
        return None

    media_type = "tv"
    title = rules.get("folder_title") or stats.get("folder_name", "")
    year = rules.get("year")

    episode_numbering = rules.get("episode_numbering", "absolute")
    season = 1
    episode = ep_num

    if episode_numbering == "season_based" and "season_mapping" in rules:
        for sea_str, rng in rules["season_mapping"].items():
            s = int(sea_str)
            if rng["start_ep"] <= ep_num <= rng["end_ep"]:
                season = s
                episode = ep_num - rng["start_ep"] + 1
                break

    return {
        "media_type": media_type,
        "title": title,
        "search_title": title,
        "year": year,
        "season": season,
        "episode": episode,
        "episode_title": "",
        "alternative_titles": [],
        "year_guess": year,
        "corrected_season": None,
        "corrected_episode": None,
        "_parser": "offline_ai_macro",
        "explicit_season": season,
        "total_episode": ep_num if episode_numbering == "absolute" else None
    }


def _extract_file_info_from_offline_cache(file_path: Path, parse_result: Dict, log_func=None) -> Optional[Dict]:
    """从离线预解析缓存中提取当前文件的信息"""
    filename = file_path.name

    if "files" in parse_result:
        if filename in parse_result["files"]:
            info = parse_result["files"][filename].copy()
            if log_func:
                log_func(f"📦 命中离线精确缓存: {filename}", "info")
            return info

    if "_stats" in parse_result:
        return _generate_episode_info_from_macro_rules(
            file_path, parse_result, parse_result["_stats"], log_func
        )
    return None


def _get_or_wait_folder_parse(folder_path: Path, config: Dict, log_func) -> Optional[Dict]:
    """获取文件夹解析结果，若已有线程在处理则等待其完成（最多60秒）"""
    folder_key = str(folder_path.resolve())
    event = None

    with _ongoing_lock:
        if folder_key in _ongoing_folder_parses:
            event = _ongoing_folder_parses[folder_key]

    if event:
        if event.wait(timeout=60):
            return folder_ai_cache.get_cached_folder_parse(folder_path, config)
        else:
            if log_func:
                log_func(f"⚠️ 等待文件夹 AI 解析超时，使用本地回退", "warning")
            return None

    event = threading.Event()
    with _ongoing_lock:
        _ongoing_folder_parses[folder_key] = event

    try:
        video_files = get_video_files_in_folder(folder_path, config["video_extensions"])
        result = ai_client.parse_folder_with_ai(folder_path, video_files, config, log_func)
        if result:
            folder_ai_cache.save_folder_parse_result(folder_path, result, config)
        return result
    except Exception as e:
        if log_func:
            log_func(f"❌ 文件夹 AI 解析异常: {e}", "error")
        return None
    finally:
        with _ongoing_lock:
            if folder_key in _ongoing_folder_parses:
                del _ongoing_folder_parses[folder_key]
        event.set()


def parse_filename(
    file_path: Path,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Dict[str, Any]:
    folder = file_path.parent
    parent_dir = folder.name
    ai_cfg = config.get("ai_parser", {})

    cache_key = get_ai_parse_cache_key(str(file_path), config)

    # 优先检查离线预解析缓存
    if ai_cfg.get("enabled"):
        offline_cache = load_ai_preparse_cache()
        folder_key = str(folder.resolve())
        if folder_key in offline_cache:
            cached_entry = offline_cache[folder_key]
            parse_result = cached_entry.get("parse_result", {})
            file_info = _extract_file_info_from_offline_cache(file_path, parse_result, log_func)
            if file_info:
                file_info.setdefault("search_title", file_info.get("title"))
                file_info.setdefault("alternative_titles", [])
                file_info.setdefault("year_guess", file_info.get("year"))
                file_info["_from_offline_ai"] = True
                _save_parse_result(cache_key, file_info)
                if log_func:
                    log_func(f"📦 命中离线预解析缓存: {file_path.name}", LOG_INFO)
                return file_info

    # 1. 实时文件夹批量缓存
    if ai_cfg.get("enabled"):
        cached_folder = folder_ai_cache.get_cached_folder_parse(folder, config)
        if cached_folder and "files" in cached_folder:
            file_info = cached_folder["files"].get(file_path.name)
            if file_info:
                result = file_info.copy()
                result.setdefault("search_title", result.get("title"))
                result.setdefault("alternative_titles", [])
                result.setdefault("year_guess", result.get("year"))
                result.setdefault("corrected_season", None)
                result.setdefault("corrected_episode", None)
                result.setdefault("explicit_season", result.get("season", 1))
                result.setdefault("total_episode", None)
                result["_from_folder_cache"] = True
                if log_func:
                    log_func(f"📁 使用文件夹缓存解析: {file_path.name} -> {result.get('title')} S{result.get('season', 1):02d}E{result.get('episode', 1):02d}", LOG_INFO)
                return result

    # 2. 单文件 AI 缓存
    with ai_parse_cache_lock:
        if cache_key in AI_CACHE:
            return AI_CACHE[cache_key].copy()
        if cache_key in _ai_parse_persistent_cache:
            result = _ai_parse_persistent_cache[cache_key].copy()
            AI_CACHE[cache_key] = result
            return result

    # 3. 实时批量 AI（使用并发锁）
    if ai_cfg.get("enabled") and ai_cfg.get("batch_folder_enabled", True):
        video_files = get_video_files_in_folder(folder, config["video_extensions"])
        if len(video_files) >= 2:
            if log_func:
                log_func(f"🤖 触发实时批量 AI 解析: {parent_dir}", LOG_INFO)
            folder_result = _get_or_wait_folder_parse(folder, config, log_func)
            if folder_result:
                file_info = folder_result.get("files", {}).get(file_path.name)
                if file_info:
                    result = file_info.copy()
                    result.setdefault("search_title", result.get("title"))
                    result.setdefault("alternative_titles", [])
                    result.setdefault("year_guess", result.get("year"))
                    result.setdefault("corrected_season", None)
                    result.setdefault("corrected_episode", None)
                    result.setdefault("explicit_season", result.get("season", 1))
                    result.setdefault("total_episode", None)
                    result["_from_folder_cache"] = True
                    _save_parse_result(cache_key, result)
                    return result

    # 4. anitopy
    anime_result = None
    if config.get("anime_parser", {}).get("enabled") and ANITOPY_AVAILABLE:
        anime_result = parse_with_anitopy(file_path.name, parent_dir, log_func)
        if anime_result.get("_anitopy_success"):
            _save_parse_result(cache_key, anime_result)
            return anime_result
        elif not config.get("anime_parser", {}).get("fallback_to_regex", True):
            return {"media_type": "unknown"}

    # 5. 按需离线 AI 预解析缓存
    if ai_cfg.get("enabled"):
        raw_data = load_raw_cache()
        folder_key = str(folder.resolve())
        if folder_key in raw_data:
            if log_func:
                log_func(f"💡 anitopy 失败，触发按需 AI 解析: {parent_dir}", LOG_INFO)
            parse_result = parse_folder_on_demand(folder, config, log_func=log_func)
            if parse_result:
                file_info = _extract_file_info_from_offline_cache(file_path, parse_result, log_func)
                if file_info:
                    file_info.setdefault("search_title", file_info.get("title"))
                    file_info.setdefault("alternative_titles", [])
                    file_info.setdefault("year_guess", file_info.get("year"))
                    file_info["_from_offline_ai"] = True
                    _save_parse_result(cache_key, file_info)
                    if log_func:
                        log_func(f"📦 离线 AI 按需解析成功: {file_path.name}", LOG_INFO)
                    return file_info

    # 6. 单文件 AI 解析
    if ai_cfg.get("enabled"):
        ai_result = ai_client.parse_filename_with_ai(
            file_path, config, log_func,
            anitopy_hint=anime_result
        )
        if ai_result.get("media_type") in ("movie", "tv"):
            _save_parse_result(cache_key, ai_result)
            return ai_result

    # 7. 正则回退
    regex_result = parse_with_regex(file_path.name, parent_dir)
    _save_parse_result(cache_key, regex_result)
    return regex_result
