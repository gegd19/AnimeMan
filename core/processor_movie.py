#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电影处理分支（整合版）
包含置信度阈值等
- 代理支持：所有 TMDB 请求（含图片下载）均传递 proxy 参数
"""

from .failure_policy import note_error
from .json_store import CacheCorruptionError
from .cancellation import check_cancelled, ProcessingCancelled
import os
import time
from pathlib import Path
from .path_safety import absolute_link_path, validate_target_path
from typing import Dict, Optional, Callable

from . import cache_manager, tmdb_client, nfo_writer, file_linker, subtitle_handler
from .processor_helpers import extract_all_alternative_titles
from .processor_utils import sanitize_filename
from .processor_cache_ops import save_failed_cache
from .constants import MIN_FINAL_CONFIDENCE
from .logger import get_logger
from .library_transaction import transactional_media, preview_target

logger = get_logger(__name__)

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"


@transactional_media
def process_movie_branch(
    src: Path,
    config: dict,
    cache_dict: dict,
    log_func: Optional[Callable],
    official_title: str,
    official_year: str,
    tmdb_id: int,
    details: Dict,
    confidence: int
) -> bool:
    """处理电影文件"""
    if confidence < MIN_FINAL_CONFIDENCE:
        save_failed_cache(src, f"置信度过低 ({confidence}% < {MIN_FINAL_CONFIDENCE}%)", cache_dict, log_func)
        return False

    try:
        # 获取代理配置
        proxy = config.get("tmdb_api", {}).get("proxy")
        base_url = config["image_base_url"]

        safe_title = sanitize_filename(official_title)
        folder_name = f"{safe_title} ({official_year})" if config.get("add_year_to_folder") and official_year else safe_title
        target_root = Path(config["movie_target_folder"])
        movie_dir = target_root / folder_name

        target_path = movie_dir / f"{folder_name}{src.suffix}"
        if config.get("dry_run"):
            target_path = preview_target(src, target_path, config, "movie")
            if log_func:
                log_func(f"🔍 [模拟] -> {target_path}", LOG_INFO)
            return True

        nfo_writer.write_movie_nfo(movie_dir, official_title, tmdb_id, details.get("overview", ""), official_year, config, log_func)

        if config.get("download_images"):
            if poster := details.get("poster_path"):
                tmdb_client.download_image(
                    tmdb_client.build_image_url(base_url, poster),
                    movie_dir / "poster.jpg",
                    log_func,
                    proxy=proxy
                )
            if backdrop := details.get("backdrop_path"):
                tmdb_client.download_image(
                    tmdb_client.build_image_url(base_url, backdrop),
                    movie_dir / "fanart.jpg",
                    log_func,
                    proxy=proxy
                )

        target_path = validate_target_path(src, target_path, config, "movie")

        if not file_linker.create_link(src, target_path, config["link_type"], log_func):
            return False
        src_str = str(src.resolve())
        confidence = min(max(confidence, 0), 100)
        alt_titles = extract_all_alternative_titles(details, official_title)

        with cache_manager.cache_lock:
            cache_dict[src_str] = {
                "target": str(absolute_link_path(target_path)),
                "source_path": src_str,
                "fingerprint": cache_manager.get_file_fingerprint(src),
                "fingerprint_strong": cache_manager.get_file_fingerprint_strong(src),
                "media_type": "movie",
                "title": official_title,
                "year": official_year,
                "tmdb_id": tmdb_id,
                "confidence": confidence,
                **({"score_origin": config["_recognition_score"]["origin"],
                    "score_evidence": list(config["_recognition_score"]["evidence"]),
                    "score_conflicts": list(config["_recognition_score"]["conflicts"])}
                   if "_recognition_score" in config else {}),
                "processed_time": time.time(),
                "alternative_titles": alt_titles
            }

        if config.get("subtitle", {}).get("enabled", True):
            subtitle_handler.process_subtitles_for_video(src, target_path, movie_dir, config, log_func)

        if log_func:
            label = "人工指定" if config.get("_recognition_score", {}).get("origin") == "manual_mapping" else f"匹配评分: {confidence}"
            log_func(f"💾 缓存已保存 ({label})", LOG_SUCCESS)
        return True
    except ProcessingCancelled:
        raise
    except CacheCorruptionError:
        raise
    except Exception as e:
        note_error(e)
        logger.error(f"电影分支处理失败 {src}: {e}", exc_info=True)
        save_failed_cache(src, f"处理异常: {e}", cache_dict, log_func)
        return False
