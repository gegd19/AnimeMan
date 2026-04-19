#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMDB 搜索增强模块
- 多级查询词生成
- 本地别名映射
- TVmaze 备选查找
- 跨季集数自动查找
"""

import re
import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple

def _get_requests():
    try:
        import requests
        return requests
    except ImportError:
        return None

def _get_config():
    try:
        from . import config_manager
        return config_manager.load_config()
    except Exception:
        return {}

def _get_logger():
    from .logger import get_logger
    return get_logger(__name__)

ALIAS_FILE = Path("tmdb_aliases.json")
_alias_cache: Dict[str, Dict] = {}

def load_aliases() -> Dict[str, Dict]:
    global _alias_cache
    if _alias_cache:
        return _alias_cache
    if ALIAS_FILE.exists():
        try:
            with open(ALIAS_FILE, 'r', encoding='utf-8') as f:
                _alias_cache = json.load(f)
                _alias_cache = {k.lower(): v for k, v in _alias_cache.items()}
        except Exception:
            _alias_cache = {}
    return _alias_cache

def lookup_local_alias(query: str) -> Optional[Dict]:
    aliases = load_aliases()
    key = query.lower().strip()
    return aliases.get(key)

def generate_search_candidates(raw_title: str) -> List[str]:
    candidates = []
    title = raw_title.strip()
    if title:
        candidates.append(title)

    suffixes = [
        r'\s+Majin Boo Hen',
        r'\s+The Final Chapters',
        r'\s+Final Chapters',
        r'\s+Season\s*\d+',
        r'\s+Part\s*\d+',
        r'\s+Arc',
        r'\s+TV Series',
        r'\s*[-–:]\s*Part\s*\d+',
        r'\s*[-–:]\s*Season\s*\d+',
    ]
    for pattern in suffixes:
        cleaned = re.sub(pattern, '', title, flags=re.I).strip()
        if cleaned and cleaned != title and cleaned not in candidates:
            candidates.append(cleaned)

    main_title = re.split(r'[-:–—]', title)[0].strip()
    if main_title and main_title != title and main_title not in candidates:
        candidates.append(main_title)

    year_removed = re.sub(r'\s*[\[\(]?\d{4}[\]\)]?\s*$', '', title).strip()
    if year_removed and year_removed not in candidates:
        candidates.append(year_removed)

    return candidates

def search_tvmaze(query: str) -> Optional[int]:
    requests = _get_requests()
    if not requests:
        return None
    try:
        url = f"https://api.tvmaze.com/search/shows?q={requests.utils.quote(query)}"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None

        show = data[0].get('show', {})
        externals = show.get('externals', {})
        tvdb_id = externals.get('thetvdb')
        imdb_id = externals.get('imdb')

        if tvdb_id:
            return find_tmdb_by_tvdb(tvdb_id)
        if imdb_id:
            return find_tmdb_by_imdb(imdb_id)
    except Exception:
        pass
    return None

def find_tmdb_by_tvdb(tvdb_id: int) -> Optional[int]:
    requests = _get_requests()
    if not requests:
        return None
    try:
        config = _get_config()
        api_key = config.get("tmdb_api", {}).get("api_key")
        if not api_key:
            return None
        url = f"https://api.themoviedb.org/3/find/{tvdb_id}"
        params = {"api_key": api_key, "external_source": "tvdb_id"}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            tv_results = data.get("tv_results", [])
            if tv_results:
                return tv_results[0].get("id")
    except Exception:
        pass
    return None

def find_tmdb_by_imdb(imdb_id: str) -> Optional[int]:
    requests = _get_requests()
    if not requests:
        return None
    try:
        config = _get_config()
        api_key = config.get("tmdb_api", {}).get("api_key")
        if not api_key:
            return None
        url = f"https://api.themoviedb.org/3/find/{imdb_id}"
        params = {"api_key": api_key, "external_source": "imdb_id"}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            tv_results = data.get("tv_results", [])
            if tv_results:
                return tv_results[0].get("id")
    except Exception:
        pass
    return None

def find_episode_across_seasons(
    tmdb_id: int,
    target_episode: int,
    api_key: str,
    language: str = "zh-CN",
    log_func=None,
    proxy: Optional[str] = None
) -> Tuple[Optional[int], Optional[Dict]]:
    try:
        from . import tmdb_client
    except ImportError:
        return None, None

    details = tmdb_client.get_tmdb_details(
        "tv", tmdb_id, api_key, language, log_func, proxy=proxy
    )
    if not details:
        return None, None

    seasons = details.get("seasons", [])
    season_numbers = [s.get("season_number", 0) for s in seasons if s.get("season_number", 0) >= 0]
    season_numbers.sort()

    for season_num in season_numbers:
        if season_num == 0:
            continue
        episodes = tmdb_client.get_tv_season_episodes(
            tmdb_id, season_num, api_key, language, log_func, proxy
        )
        for ep in episodes:
            if ep.get("episode_number") == target_episode:
                return season_num, ep

    if 0 in season_numbers:
        episodes = tmdb_client.get_tv_season_episodes(
            tmdb_id, 0, api_key, language, log_func, proxy
        )
        for ep in episodes:
            if ep.get("episode_number") == target_episode:
                return 0, ep

    return None, None
