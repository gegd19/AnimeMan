#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电影处理分支（整合版）
包含置信度阈值等
- 代理支持：所有 TMDB 请求（含图片下载）均传递 proxy 参数
"""

import os
import time
from pathlib import Path
from typing import Dict, Optional, Callable

from . import cache_manager, tmdb_client, nfo_writer, file_linker, subtitle_handler
from .processor_helpers import extract_all_alternative_titles
from .processor_utils import sanitize_filename
from .processor_cache_ops import save_failed_cache
from .constants import MIN_FINAL_CONFIDENCE
from .logger import get_logger

logger = get_logger(__name__)

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"


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

        target_path = movie_dir / f"{folder_name}{src.suffix}"
        if config.get("dry_run"):
            if log_func:
                log_func(f"🔍 [模拟] -> {target_path}", LOG_INFO)
            return True

        if target_path.exists():
            try:
                src_str = str(src).replace('\\\\?\\', '')
                tgt_str = str(target_path).replace('\\\\?\\', '')
                if os.path.samefile(src_str, tgt_str):
                    if log_func:
                        log_func(f"🔗 目标已存在且指向同一文件，跳过链接创建", LOG_INFO)
                else:
                    target_path.unlink()
                    if log_func:
                        log_func(f"🗑️ 已删除已存在的不同目标文件: {target_path.name}", LOG_WARNING)
            except Exception as e:
                logger.error(f"处理已存在目标文件失败 {target_path}: {e}")
                save_failed_cache(src, f"处理已存在目标文件失败: {e}", cache_dict, log_func)
                return False

        if not target_path.exists():
            if not file_linker.create_link(src, target_path, config["link_type"], log_func):
                save_failed_cache(src, "链接创建失败", cache_dict, log_func)
                return False
        src_str = str(src.resolve())
        confidence = min(max(confidence, 0), 100)
        alt_titles = extract_all_alternative_titles(details, official_title)

        with cache_manager.cache_lock:
            cache_dict[src_str] = {
                "target": str(target_path.resolve()),
                "fingerprint": cache_manager.get_file_fingerprint(src),
                "fingerprint_strong": cache_manager.get_file_fingerprint_strong(src),
                "media_type": "movie",
                "title": official_title,
                "year": official_year,
                "tmdb_id": tmdb_id,
                "confidence": confidence,
                "processed_time": time.time(),
                "alternative_titles": alt_titles
            }

        if config.get("subtitle", {}).get("enabled", True):
            subtitle_handler.process_subtitles_for_video(src, target_path, movie_dir, config, log_func)

        if log_func:
            log_func(f"💾 缓存已保存 (准确率: {confidence}%)", LOG_SUCCESS)
        return True
    except Exception as e:
        logger.error(f"电影分支处理失败 {src}: {e}", exc_info=True)
        save_failed_cache(src, f"处理异常: {e}", cache_dict, log_func)
        return False
