#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单文件核心处理流程（主入口）
已拆分为多个子模块：
- constants.py：全局常量
- processor_helpers.py：通用辅助函数
- processor_search.py：TMDB搜索与AI辅助选择
- processor_movie.py：电影处理分支
- processor_tv.py：剧集处理分支
- processor_folder_ai.py：文件夹级AI批量解析
"""

import re
import time
import threading
import os
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple

from . import cache_manager
from . import tmdb_client
from . import nfo_writer
from . import file_linker
from . import subtitle_handler
from . import video_info
from . import ai_client

from .constants import *
from .processor_helpers import (
    apply_special_mapping, parse_filename_info, compute_confidence,
    prepare_search_query, extract_all_alternative_titles, build_season_indicators
)
from .processor_search import search_tmdb_with_fallback
from .processor_movie import process_movie_branch
from .processor_tv import process_tv_branch
from .processor_folder_ai import try_folder_ai_batch
from .processor_utils import sanitize_filename, wrap_progress_callback
from .processor_cache_ops import save_failed_cache
from .logger import get_logger

logger = get_logger(__name__)

stop_processing = threading.Event()

SEASON_INDICATORS = build_season_indicators(30)

# 文件夹级 TMDB 缓存（成功匹配结果缓存）
_folder_tmdb_cache: Dict[Tuple[str, str], int] = {}
_folder_tmdb_cache_lock = threading.RLock()


def process_video(
    src: Path,
    config: Dict[str, Any],
    cache_dict: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> bool:
    wrapped_log = wrap_progress_callback(log_func)

    if stop_processing.is_set():
        if wrapped_log:
            wrapped_log(f"⏹️ 收到停止信号，跳过: {src.name}", LOG_WARNING)
        return False

    try:
        force_tmdb_id, force_media_type, force_season, force_episode = apply_special_mapping(src, config, wrapped_log)
        info = parse_filename_info(src, config, wrapped_log, force_tmdb_id, force_media_type, force_season, force_episode)

        # 文件夹级 AI 批量解析
        updated_info = try_folder_ai_batch(src, config, info, force_tmdb_id, wrapped_log)
        if updated_info:
            info = updated_info

        def try_process_with_info(current_info: Dict, confidence_start: int):
            media_type = current_info.get("media_type")
            title = current_info.get("title") or ""
            if not title or title == "Unknown" or media_type not in ("movie", "tv"):
                return (False, None, None, None, None, None, confidence_start, current_info)

            if media_type == "tv":
                if current_info.get("season") is None:
                    current_info["season"] = 1
                if current_info.get("episode") is None:
                    current_info["episode"] = 1

            confidence = confidence_start
            local_duration = video_info.get_video_duration(src)
            duration_hint = None
            if local_duration is not None:
                if wrapped_log:
                    wrapped_log(f"⏱️ 视频时长: {local_duration:.1f} 分钟", LOG_INFO)
                if media_type == "movie" and local_duration < 40:
                    duration_hint = "tv"
                    confidence -= 15
                    if wrapped_log:
                        wrapped_log(f"⚠️ 识别为电影但时长仅 {local_duration:.1f} 分钟，可能是剧集/OVA", LOG_WARNING)
                elif media_type == "tv" and local_duration > 90:
                    duration_hint = "movie"
                    confidence -= 15
                    if wrapped_log:
                        wrapped_log(f"⚠️ 识别为剧集但时长达 {local_duration:.1f} 分钟，可能是电影", LOG_WARNING)
                elif media_type == "tv" and local_duration < 5:
                    confidence -= 20
                    if wrapped_log:
                        wrapped_log(f"⚠️ 视频时长极短 ({local_duration:.1f} 分钟)，可能是特典/预告", LOG_WARNING)

            title_orig, search_title, search_year, alt_titles = prepare_search_query(current_info, TECH_NOISE_WORDS)

            if "tmdb_id" in current_info and current_info["tmdb_id"]:
                tmdb_id = current_info["tmdb_id"]
                media_type = current_info["media_type"]
                if wrapped_log:
                    wrapped_log(f"🎯 使用映射规则指定的 TMDB ID: {tmdb_id} ({media_type})", LOG_SUCCESS)
                tmdb_result = {"id": tmdb_id}
                candidate_count = 0
            else:
                # 文件夹级 TMDB 缓存
                folder_key = str(src.parent.resolve())
                cache_key = (folder_key, search_title)
                with _folder_tmdb_cache_lock:
                    cached_tmdb_id = _folder_tmdb_cache.get(cache_key)

                if cached_tmdb_id:
                    tmdb_result = {"id": cached_tmdb_id}
                    candidate_count = 0
                    if wrapped_log:
                        wrapped_log(f"📦 命中文件夹TMDB缓存: ID {cached_tmdb_id}", LOG_INFO)
                else:
                    tmdb_result, media_type, candidate_count = search_tmdb_with_fallback(
                        media_type, search_title, search_year, alt_titles, config, wrapped_log,
                        src=src, duration_hint=duration_hint, title_for_attempts=title_orig,
                        base_confidence=confidence
                    )
                    if tmdb_result:
                        tmdb_id = tmdb_result.get("id")
                        if tmdb_id:
                            with _folder_tmdb_cache_lock:
                                _folder_tmdb_cache[cache_key] = tmdb_id

                if not tmdb_result:
                    return (False, None, None, None, None, None, confidence, current_info)

                if candidate_count > 1:
                    confidence -= 5
                    if wrapped_log:
                        wrapped_log(f"⚠️ 搜索返回 {candidate_count} 个候选结果，置信度降低 5%", LOG_WARNING)

            tmdb_id = tmdb_result["id"]
            api_key = config["tmdb_api"]["api_key"]
            language = config["tmdb_api"].get("language", "zh-CN")
            proxy = config.get("tmdb_api", {}).get("proxy")
            details = tmdb_client.get_tmdb_details(
                media_type=media_type, tmdb_id=tmdb_id, api_key=api_key,
                language=language, log_func=wrapped_log, include_alternative_titles=True, proxy=proxy
            )
            if not details:
                return (False, None, None, None, None, None, confidence, current_info)

            if media_type == "movie":
                official_title = details.get("title")
            else:
                official_title = details.get("name") or details.get("original_name")
            if not official_title:
                official_title = title_orig
                if wrapped_log:
                    wrapped_log(f"⚠️ TMDB 无标题，使用解析标题: {title_orig}", LOG_WARNING)
            official_title = official_title.strip() if official_title else title_orig

            release_date = details.get("release_date" if media_type == "movie" else "first_air_date") or ""
            official_year = release_date[:4] if release_date else search_year or ""

            # 时长验证
            if local_duration is not None:
                tmdb_runtime = None
                if media_type == "movie":
                    tmdb_runtime = details.get("runtime")
                else:
                    episode_run_time = details.get("episode_run_time", [])
                    if episode_run_time:
                        tmdb_runtime = episode_run_time[0]
                if tmdb_runtime:
                    diff = abs(local_duration - tmdb_runtime)
                    if diff > MAX_DURATION_DIFF_MINUTES:
                        if wrapped_log:
                            wrapped_log(f"❌ 时长差异过大 ({diff:.0f} 分钟 > {MAX_DURATION_DIFF_MINUTES})，匹配失败", LOG_ERROR)
                        return (False, None, None, None, None, None, confidence, current_info)
                    elif diff <= 10:
                        confidence += 10
                        if wrapped_log:
                            wrapped_log(f"✅ 时长精确匹配，置信度 +10", LOG_SUCCESS)
                    elif diff <= 20:
                        confidence += 5
                        if wrapped_log:
                            wrapped_log(f"👍 时长基本匹配，置信度 +5", LOG_INFO)
                    else:
                        confidence -= 5
                        if wrapped_log:
                            wrapped_log(f"⚠️ 时长差异较大，置信度 -5", LOG_WARNING)

            return (True, details, media_type, tmdb_id, official_title, official_year, confidence, current_info)

        initial_confidence = compute_confidence(info, force_tmdb_id is not None)
        if info.get("_from_folder_ai_batch"):
            initial_confidence = max(initial_confidence, 85)
        success, details, media_type, tmdb_id, official_title, official_year, confidence, final_info = try_process_with_info(info, initial_confidence)

        # 强制 AI 解析
        force_ai_due_to_season = False
        if not success and info.get("_parser") == "anitopy" and info.get("season") == 1:
            combined_text = f"{src.name} {src.parent.name}".lower()
            if any(ind in combined_text for ind in SEASON_INDICATORS):
                force_ai_due_to_season = True
                if wrapped_log:
                    wrapped_log(f"⚠️ 检测到季号标识但 anitopy 解析为 S01，强制使用 AI 解析", LOG_WARNING)

        if (force_ai_due_to_season or (not success and info.get("_parser") == "anitopy")) and config.get("ai_parser", {}).get("enabled"):
            if not force_ai_due_to_season:
                if wrapped_log:
                    wrapped_log(f"⚠️ anitopy 解析后 TMDB 搜索失败，尝试使用 AI 重新解析...", LOG_WARNING)
            ai_info = ai_client.parse_filename_with_ai(src, config, wrapped_log)
            if ai_info.get("media_type") in ("movie", "tv"):
                ai_info["_from_ai"] = True
                success, details, media_type, tmdb_id, official_title, official_year, confidence, final_info = try_process_with_info(
                    ai_info, 80
                )
                if success:
                    info = ai_info
                    if wrapped_log:
                        wrapped_log(f"✅ AI 解析成功，继续处理", LOG_SUCCESS)

        if not success:
            save_failed_cache(src, "TMDB 搜索无结果或详情获取失败", cache_dict, wrapped_log)
            return False

        if wrapped_log:
            if media_type == "movie":
                wrapped_log(f"🎬 识别为电影: {official_title} ({official_year or '未知'})", LOG_SUCCESS)
            else:
                wrapped_log(f"📺 识别为剧集: {official_title} S{final_info['season']:02d}E{final_info['episode']:02d}", LOG_SUCCESS)

        if media_type == "movie":
            return process_movie_branch(src, config, cache_dict, wrapped_log, official_title, official_year, tmdb_id, details, confidence)
        else:
            return process_tv_branch(src, config, cache_dict, wrapped_log, official_title, official_year, tmdb_id, details, final_info, confidence)

    except Exception as e:
        logger.error(f"process_video 顶层异常 {src}: {e}", exc_info=True)
        save_failed_cache(src, f"未知异常: {e}", cache_dict, wrapped_log)
        return False
