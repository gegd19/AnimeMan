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
from .runtime_paths import cache_file
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
_alias_path = None

def load_aliases() -> Dict[str, Dict]:
    global _alias_cache, _alias_path
    path = cache_file(ALIAS_FILE.name)
    if path == _alias_path:
        return _alias_cache
    _alias_path = path
    _alias_cache = {}
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _alias_cache = json.load(f)
                _alias_cache = {k.lower(): v for k, v in _alias_cache.items()}
        except OSError:
            _alias_path = None
            raise
        except Exception:
            _alias_cache = {}
    return _alias_cache

def lookup_local_alias(query: str) -> Optional[Dict]:
    aliases = load_aliases()
    key = query.lower().strip()
    return aliases.get(key)

def generate_search_candidates(raw_title: str) -> List[str]:
    """Preserve semantic title tokens; only strip well-known technical tags."""
    from .constants import TECH_NOISE_WORDS
    if not isinstance(raw_title, str) or not raw_title.strip():
        return []
    title = raw_title.strip()
    cleaned = title
    for word in sorted(TECH_NOISE_WORDS, key=len, reverse=True):
        cleaned = re.sub(r'(?<!\w)' + re.escape(word) + r'(?!\w)', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\[\s*\]|\(\s*\)', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return [title, cleaned] if cleaned and cleaned != title else [title]


def search_tvmaze(query: str, config=None) -> Optional[int]:
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
            return find_tmdb_by_tvdb(tvdb_id, config=config)
        if imdb_id:
            return find_tmdb_by_imdb(imdb_id, config=config)
    except Exception:
        pass
    return None

def find_tmdb_by_tvdb(tvdb_id: int, config=None) -> Optional[int]:
    requests = _get_requests()
    if not requests:
        return None
    try:
        config = _get_config() if config is None else config
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

def find_tmdb_by_imdb(imdb_id: str, config=None) -> Optional[int]:
    requests = _get_requests()
    if not requests:
        return None
    try:
        config = _get_config() if config is None else config
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

    matches = []
    for season_num in season_numbers:
        if season_num == 0:
            continue
        episodes = tmdb_client.get_tv_season_episodes(
            tmdb_id, season_num, api_key, language, log_func, proxy
        )
        # An empty response may be a failed request; uniqueness cannot be proved.
        if not episodes:
            return None, None
        matches.extend((season_num, ep) for ep in episodes
                       if ep.get("episode_number") == target_episode)
        if len(matches) > 1:
            return None, None
    return matches[0] if len(matches) == 1 else (None, None)
