#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器缓存操作：失败缓存保存、旧文件清理
"""

import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from . import cache_manager

LOG_WARNING = "warning"


def save_failed_cache(
    src_path: Path,
    reason: str,
    cache_dict: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> None:
    """记录处理失败的文件到缓存"""
    src_str = str(src_path.resolve())
    with cache_manager.cache_lock:
        cache_dict[src_str] = {
            "target": "",
            "fingerprint": cache_manager.get_file_fingerprint(src_path),
            "media_type": "failed",
            "title": src_path.name,
            "failed_reason": reason,
            "failed_time": time.time()
        }
    if log_func:
        log_func(f"⚠️ 无法自动处理，已记录失败缓存: {src_path.name} ({reason})", LOG_WARNING)


def cleanup_previous_artifacts(src: Path, config: dict) -> None:
    """根据源文件路径，查找并删除之前可能生成的错误文件（链接、NFO、图片）"""
    cache = cache_manager.load_cache()
    src_str = str(src.resolve())
    if src_str not in cache:
        return
    entry = cache[src_str]
    target_path = Path(entry.get("target", ""))
    if not target_path.exists():
        return
    try:
        target_path.unlink()
    except Exception:
        pass

    media_type = entry.get("media_type")
    if media_type == "movie":
        movie_dir = target_path.parent
        (movie_dir / "movie.nfo").unlink(missing_ok=True)
        (movie_dir / "poster.jpg").unlink(missing_ok=True)
        (movie_dir / "fanart.jpg").unlink(missing_ok=True)
    elif media_type == "tv":
        season_dir = target_path.parent
        season_num = entry.get("season")
        episode_num = entry.get("episode")
        for nfo in season_dir.glob(f"* - S{season_num:02d}E{episode_num:02d}*.nfo"):
            nfo.unlink(missing_ok=True)
        for img in season_dir.glob(f"* - S{season_num:02d}E{episode_num:02d}*.jpg"):
            img.unlink(missing_ok=True)
