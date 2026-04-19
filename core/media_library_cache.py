#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体库元数据缓存
加速前端加载，避免每次遍历处理缓存和检查文件
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List

from . import cache_manager

MEDIA_LIBRARY_CACHE_FILE = "media_library_cache.json"


def generate_media_library_cache() -> Dict[str, Any]:
    """根据处理缓存生成媒体库元数据缓存"""
    processed = cache_manager.load_cache()
    movies = []
    tv_shows_dict = {}

    for src_str, entry in processed.items():
        if entry.get("media_type") == "failed":
            continue

        target = Path(entry.get("target", ""))
        if not target.exists():
            continue

        media_type = entry.get("media_type")
        title = entry.get("title", "")
        year = entry.get("year", "")
        tmdb_id = entry.get("tmdb_id")

        if media_type == "movie":
            movie_dir = target.parent
            poster_exists = (movie_dir / "poster.jpg").exists() or (movie_dir / "fanart.jpg").exists()
            movies.append({
                "cache_key": src_str,
                "media_type": "movie",
                "title": title,
                "year": year,
                "target_path": str(target),
                "target_dir": str(movie_dir),
                "tmdb_id": tmdb_id,
                "poster_exists": poster_exists,
                "alternative_titles": entry.get("alternative_titles", [title] if title else [])
            })
        elif media_type == "tv":
            season = entry.get("season", 1)
            episode = entry.get("episode", 1)
            if tmdb_id not in tv_shows_dict:
                show_dir = target.parent.parent
                poster_exists = (show_dir / "poster.jpg").exists() or (show_dir / "fanart.jpg").exists()
                tv_shows_dict[tmdb_id] = {
                    "tmdb_id": tmdb_id,
                    "title": title,
                    "year": year,
                    "poster_exists": poster_exists,
                    "seasons": {},
                    "alternative_titles": entry.get("alternative_titles", [title] if title else [])
                }
            show = tv_shows_dict[tmdb_id]
            if season not in show["seasons"]:
                show["seasons"][season] = {
                    "season_number": season,
                    "episodes": []
                }
            show["seasons"][season]["episodes"].append({
                "episode": episode,
                "title": entry.get("episode_title") or f"第 {episode} 集",
                "target_path": str(target),
                "target_dir": str(target.parent),
                "cache_key": src_str,
            })

    tv_shows = []
    for show in tv_shows_dict.values():
        for season_data in show["seasons"].values():
            season_data["episodes"].sort(key=lambda x: x["episode"])
        show["seasons"] = dict(sorted(show["seasons"].items()))
        tv_shows.append(show)

    cache_data = {
        "movies": movies,
        "tv_shows": tv_shows,
        "updated": time.time()
    }
    return cache_data


def save_media_library_cache(cache_data: Dict[str, Any]) -> None:
    """保存媒体库缓存到文件"""
    with open(MEDIA_LIBRARY_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def load_media_library_cache() -> Dict[str, Any]:
    """加载媒体库缓存"""
    path = Path(MEDIA_LIBRARY_CACHE_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def update_media_library_cache() -> Dict[str, Any]:
    """更新并返回媒体库缓存"""
    cache = generate_media_library_cache()
    save_media_library_cache(cache)
    return cache
