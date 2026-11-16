#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动修正处理（用户指定 TMDB ID 后重新处理）
包含目标文件覆盖逻辑，解决修改集数时目标已存在的问题
"""

from .failure_policy import note_error
from .json_store import CacheCorruptionError
from .cancellation import check_cancelled, ProcessingCancelled
import time
import os
from pathlib import Path
from .path_safety import absolute_link_path, validate_target_path
from typing import Optional, Callable, Dict, Any

from . import cache_manager
from . import tmdb_client
from . import nfo_writer
from . import file_linker
from . import subtitle_handler
from .media_paths import episode_video_path
from .processor_utils import sanitize_filename, wrap_progress_callback
from .logger import get_logger
from .library_transaction import transactional_media, preview_target

logger = get_logger(__name__)

LOG_SUCCESS = "success"
LOG_ERROR = "error"
LOG_WARNING = "warning"
LOG_INFO = "info"


def _process_with_known_tmdb(
    src: Path,
    config: dict,
    cache_dict: Dict[str, Any],
    log_func: Optional[Callable],
    tmdb_id: int,
    media_type: str,
    season: Optional[int],
    episode: Optional[int]
) -> bool:
    """使用已知的 TMDB ID 进行处理（不经过搜索和解析）"""
    wrapped_log = wrap_progress_callback(log_func)

    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")
    base_url = config["image_base_url"]

    try:
        details = tmdb_client.get_tmdb_details(
            media_type, tmdb_id, api_key, language, wrapped_log,
            include_alternative_titles=True, proxy=proxy
        )
    except ProcessingCancelled:
        raise
    except CacheCorruptionError:
        raise
    except Exception as e:
        note_error(e)
        logger.error(f"获取 TMDB 详情失败 tmdb_id={tmdb_id}: {e}", exc_info=True)
        if wrapped_log:
            wrapped_log(f"❌ 无法获取 TMDB 详情 (tmdb_id={tmdb_id}): {e}", LOG_ERROR)
        return False

    if not details:
        if wrapped_log:
            wrapped_log(f"❌ 无法获取 TMDB 详情 (tmdb_id={tmdb_id})", LOG_ERROR)
        return False

    official_title = details.get("title" if media_type == "movie" else "name") or src.stem
    release_date = details.get("release_date" if media_type == "movie" else "first_air_date") or ""
    official_year = release_date[:4] if release_date else ""

    if media_type == "movie":
        safe_title = sanitize_filename(official_title)
        folder_name = f"{safe_title} ({official_year})" if config.get("add_year_to_folder") and official_year else safe_title
        target_root = Path(config["movie_target_folder"])
        movie_dir = target_root / folder_name
        target_path = movie_dir / f"{folder_name}{src.suffix}"

        if config.get("dry_run"):
            target_path = preview_target(src, target_path, config, media_type)
            if wrapped_log:
                wrapped_log(f"🔍 [模拟] -> {target_path}", LOG_INFO)
            return True

        try:
            movie_dir.mkdir(parents=True, exist_ok=True)
        except ProcessingCancelled:
            raise
        except CacheCorruptionError:
            raise
        except Exception as e:
            note_error(e)
            logger.error(f"创建电影目录失败 {movie_dir}: {e}")
            wrapped_log(f"❌ 创建目录失败: {e}", LOG_ERROR)
            return False

        nfo_writer.write_movie_nfo(movie_dir, official_title, tmdb_id, details.get("overview", ""), official_year, config, wrapped_log)
        if config.get("download_images"):
            if poster := details.get("poster_path"):
                tmdb_client.download_image(tmdb_client.build_image_url(base_url, poster), movie_dir / "poster.jpg", wrapped_log, proxy=proxy)
            if backdrop := details.get("backdrop_path"):
                tmdb_client.download_image(tmdb_client.build_image_url(base_url, backdrop), movie_dir / "fanart.jpg", wrapped_log, proxy=proxy)

        target_path = validate_target_path(src, target_path, config, media_type)

        if not file_linker.create_link(src, target_path, config["link_type"], wrapped_log):
            return False
        if config.get("subtitle", {}).get("enabled", True):
            subtitle_handler.process_subtitles_for_video(src, target_path, movie_dir, config, wrapped_log)

        src_str = str(src.resolve())
        with cache_manager.cache_lock:
            cache_dict[src_str] = {
                "target": str(absolute_link_path(target_path)),
                "source_path": src_str,
                "fingerprint": cache_manager.get_file_fingerprint(src),
                "media_type": "movie",
                "title": official_title,
                "year": official_year,
                "tmdb_id": tmdb_id,
                "confidence": None,
                "confirmed_by_user": True,
                "processed_time": time.time()
            }
        if wrapped_log:
            wrapped_log(f"✅ 手动修正成功: {official_title} ({official_year})", LOG_SUCCESS)
        return True

    else:  # 剧集
        if season is None or episode is None:
            if wrapped_log:
                wrapped_log("❌ 剧集缺少季/集信息", LOG_ERROR)
            return False

        try:
            episodes = tmdb_client.get_tv_season_episodes(tmdb_id, season, api_key, language, wrapped_log, proxy=proxy)
        except ProcessingCancelled:
            raise
        except CacheCorruptionError:
            raise
        except Exception as e:
            note_error(e)
            logger.error(f"获取季集列表失败 tmdb_id={tmdb_id} season={season}: {e}")
            wrapped_log(f"❌ 获取集列表失败: {e}", LOG_ERROR)
            return False

        ep_data = next((ep for ep in episodes if ep.get("episode_number") == episode), None)
        if not ep_data:
            if wrapped_log:
                wrapped_log(f"❌ TMDB 中无 S{season:02d}E{episode:02d} 数据", LOG_ERROR)
            return False

        target_path = episode_video_path(src, config, official_title, official_year,
                                         season, episode, ep_data.get("name"))
        season_dir = target_path.parent
        show_dir = season_dir.parent

        if config.get("dry_run"):
            target_path = preview_target(src, target_path, config, media_type)
            if wrapped_log:
                wrapped_log(f"🔍 [模拟] -> {target_path}", LOG_INFO)
            return True

        try:
            season_dir.mkdir(parents=True, exist_ok=True)
        except ProcessingCancelled:
            raise
        except CacheCorruptionError:
            raise
        except Exception as e:
            note_error(e)
            logger.error(f"创建剧集目录失败 {season_dir}: {e}")
            wrapped_log(f"❌ 创建目录失败: {e}", LOG_ERROR)
            return False

        regular_seasons = [s for s in details.get("seasons", []) if s.get("season_number", 0) > 0]
        nfo_writer.write_tvshow_nfo(show_dir, official_title, tmdb_id, details.get("overview", ""), official_year, len(regular_seasons), config, wrapped_log)
        if config.get("download_images"):
            if poster := details.get("poster_path"):
                tmdb_client.download_image(tmdb_client.build_image_url(base_url, poster), show_dir / "poster.jpg", wrapped_log, proxy=proxy)
            if backdrop := details.get("backdrop_path"):
                tmdb_client.download_image(tmdb_client.build_image_url(base_url, backdrop), show_dir / "fanart.jpg", wrapped_log, proxy=proxy)

        nfo_writer.write_season_nfo(season_dir, season, tmdb_id, wrapped_log)
        nfo_writer.write_episode_nfo(season_dir, ep_data, official_title, season, episode, tmdb_id, config, wrapped_log, video_path=target_path)

        target_path = validate_target_path(src, target_path, config, media_type)

        if not file_linker.create_link(src, target_path, config["link_type"], wrapped_log):
            return False
        if config.get("subtitle", {}).get("enabled", True):
            subtitle_handler.process_subtitles_for_video(src, target_path, season_dir, config, wrapped_log)

        src_str = str(src.resolve())
        with cache_manager.cache_lock:
            cache_dict[src_str] = {
                "target": str(absolute_link_path(target_path)),
                "source_path": src_str,
                "fingerprint": cache_manager.get_file_fingerprint(src),
                "media_type": "tv",
                "title": official_title,
                "season": season,
                "episode": episode,
                "tmdb_id": tmdb_id,
                "confidence": None,
                "confirmed_by_user": True,
                "processed_time": time.time()
            }
        if wrapped_log:
            wrapped_log(f"✅ 手动修正成功: {official_title} S{season:02d}E{episode:02d}", LOG_SUCCESS)
        return True


@transactional_media
def process_video_with_manual_correction(
    src: Path,
    config: dict,
    cache_dict: Dict[str, Any],
    tmdb_id: int,
    media_type: str,
    season: Optional[int],
    episode: Optional[int],
    log_func: Optional[Callable] = None
) -> bool:
    """手动修正入口（供 Web API 调用）"""
    wrapped_log = wrap_progress_callback(log_func)
    try:
        return _process_with_known_tmdb(
            src, config, cache_dict, wrapped_log, tmdb_id, media_type, season, episode
        )
    except ProcessingCancelled:
        raise
    except CacheCorruptionError:
        raise
    except Exception as e:
        note_error(e)
        logger.error(f"手动修正顶层异常 {src}: {e}", exc_info=True)
        if wrapped_log:
            wrapped_log(f"❌ 手动修正异常: {e}", LOG_ERROR)
        return False
