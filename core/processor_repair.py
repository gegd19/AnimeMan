#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复模式：补全已处理文件的缺失元数据（NFO、图片）
"""

from pathlib import Path
from typing import Dict, Any, Optional, Callable

from . import tmdb_client
from . import nfo_writer
from .processor_utils import wrap_progress_callback

LOG_INFO = "info"
LOG_SUCCESS = "success"


def repair_missing_metadata(
    config: Dict[str, Any],
    cache_dict: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> None:
    """扫描缓存中已处理的文件，补全缺失的 NFO 和图片"""
    wrapped_log = wrap_progress_callback(log_func)

    if wrapped_log:
        wrapped_log("🔧 启动修复模式，检查已处理项目的元数据完整性...", LOG_INFO)

    processed_dirs = set()
    items_to_check = []

    # 从缓存中收集需要检查的项目
    for src_str, entry in cache_dict.items():
        target_path = Path(entry.get("target", ""))
        if not target_path.exists() or entry.get("media_type") == "failed":
            continue
        media_type = entry.get("media_type")
        tmdb_id = entry.get("tmdb_id")
        if not tmdb_id:
            continue

        if media_type == "movie":
            movie_dir = target_path.parent
            dir_key = str(movie_dir)
            if dir_key not in processed_dirs:
                processed_dirs.add(dir_key)
                items_to_check.append(("movie", movie_dir, tmdb_id, entry.get("title"), entry.get("year")))
        else:
            season_dir = target_path.parent
            show_dir = season_dir.parent
            dir_key = str(show_dir)
            if dir_key not in processed_dirs:
                processed_dirs.add(dir_key)
                items_to_check.append(("tv", show_dir, tmdb_id, entry.get("title"), entry.get("year")))

    total = len(items_to_check)
    if wrapped_log:
        wrapped_log(f"🔍 发现 {total} 个需检查的项目", LOG_INFO)

    repaired = 0
    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")
    base_url = config["image_base_url"]

    for item in items_to_check:
        media_type, dir_path, tmdb_id, title, year = item
        # 修正后的调用：按正确顺序传递参数
        details = tmdb_client.get_tmdb_details(
            media_type,
            tmdb_id,
            api_key,
            language=language,
            log_func=wrapped_log,
            include_alternative_titles=True,
            proxy=proxy
        )
        if not details:
            continue

        if media_type == "movie":
            nfo_path = dir_path / "movie.nfo"
            if not nfo_path.exists():
                nfo_writer.write_movie_nfo(dir_path, title, tmdb_id, details.get("overview", ""), year, config, wrapped_log)
                repaired += 1
            if config.get("download_images"):
                poster_path = dir_path / "poster.jpg"
                if not poster_path.exists() and details.get("poster_path"):
                    tmdb_client.download_image(
                        tmdb_client.build_image_url(base_url, details["poster_path"]),
                        poster_path,
                        wrapped_log
                    )
                fanart_path = dir_path / "fanart.jpg"
                if not fanart_path.exists() and details.get("backdrop_path"):
                    tmdb_client.download_image(
                        tmdb_client.build_image_url(base_url, details["backdrop_path"]),
                        fanart_path,
                        wrapped_log
                    )
        else:  # tv
            nfo_path = dir_path / "tvshow.nfo"
            regular_seasons = [s for s in details.get("seasons", []) if s.get("season_number", 0) > 0]
            if not nfo_path.exists():
                nfo_writer.write_tvshow_nfo(dir_path, title, tmdb_id, details.get("overview", ""), year, len(regular_seasons), config, wrapped_log)
                repaired += 1
            if config.get("download_images"):
                poster_path = dir_path / "poster.jpg"
                if not poster_path.exists() and details.get("poster_path"):
                    tmdb_client.download_image(
                        tmdb_client.build_image_url(base_url, details["poster_path"]),
                        poster_path,
                        wrapped_log
                    )
                fanart_path = dir_path / "fanart.jpg"
                if not fanart_path.exists() and details.get("backdrop_path"):
                    tmdb_client.download_image(
                        tmdb_client.build_image_url(base_url, details["backdrop_path"]),
                        fanart_path,
                        wrapped_log
                    )

    if wrapped_log:
        wrapped_log(f"✨ 修复完成，共处理 {repaired} 个项目", LOG_SUCCESS)
