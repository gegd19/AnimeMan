#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMDB 搜索缓存管理
"""

import json
import hashlib
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any

CACHE_FILE = "tmdb_search_cache.json"
DEFAULT_TTL = 7 * 24 * 3600  # 7天

_cache_lock = threading.RLock()
_cache: Dict[str, Dict[str, Any]] = {}


def _load_cache() -> Dict[str, Dict[str, Any]]:
    global _cache
    path = Path(CACHE_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}
    return _cache


def _save_cache(cache_data: Dict[str, Dict[str, Any]]) -> None:
    temp_file = CACHE_FILE + ".tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    Path(temp_file).replace(CACHE_FILE)


def _make_cache_key(query: str, media_type: str, year: str = "") -> str:
    normalized = f"{query.strip().lower()}|{media_type}|{year or ''}"
    return hashlib.md5(normalized.encode()).hexdigest()


def get_cached_result(query: str, media_type: str, year: str = "", ttl: int = DEFAULT_TTL) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        if not _cache:
            _load_cache()
        key = _make_cache_key(query, media_type, year)
        entry = _cache.get(key)
        if not entry:
            return None

        expires = entry.get('expires_at', 0)
        if time.time() > expires:
            del _cache[key]
            _save_cache(_cache)
            return None

        return entry.get('data')


def set_cached_result(query: str, media_type: str, year: str, data: Dict[str, Any], ttl: int = DEFAULT_TTL) -> None:
    with _cache_lock:
        if not _cache:
            _load_cache()
        key = _make_cache_key(query, media_type, year)
        now = time.time()
        _cache[key] = {
            "data": data,
            "created_at": now,
            "expires_at": now + ttl
        }

        MAX_ENTRIES = 500
        if len(_cache) > MAX_ENTRIES:
            items = sorted(_cache.items(), key=lambda x: x[1].get('created_at', 0))
            for k, _ in items[:int(MAX_ENTRIES * 0.2)]:
                del _cache[k]

        _save_cache(_cache)
