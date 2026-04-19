#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存管理模块
处理文件处理缓存和 AI 解析缓存的读写、指纹计算
"""

import json
import hashlib
import threading
from pathlib import Path
from typing import Dict, Any

CACHE_FILE = "auto_processed_cache.json"
AI_PARSE_CACHE_FILE = "ai_parse_cache.json"

cache_lock = threading.RLock()
ai_parse_cache_lock = threading.RLock()


def load_cache() -> Dict[str, Any]:
    with cache_lock:
        cache_path = Path(CACHE_FILE)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


def save_cache(cache: Dict[str, Any]):
    with cache_lock:
        temp_file = CACHE_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        Path(temp_file).replace(CACHE_FILE)


def get_file_fingerprint(filepath: Path) -> str:
    try:
        stat = filepath.stat()
        raw = f"{str(filepath.resolve())}|{stat.st_size}|{stat.st_mtime}"
        return hashlib.md5(raw.encode()).hexdigest()
    except Exception:
        return ""


def get_file_fingerprint_strong(filepath: Path) -> str:
    try:
        stat = filepath.stat()
        base = f"{str(filepath.resolve())}|{stat.st_size}|{stat.st_mtime}"
        with open(filepath, 'rb') as f:
            chunk = f.read(1024 * 1024)
            content_hash = hashlib.md5(chunk).hexdigest()
        return hashlib.md5(f"{base}|{content_hash}".encode()).hexdigest()
    except Exception:
        return ""


def is_already_processed(src: Path, cache_entry: Dict, config: Dict) -> bool:
    target_str = cache_entry.get("target", "")
    if not target_str:
        return False
    target = Path(target_str)
    if not target.exists():
        return False

    current_fp = get_file_fingerprint(src)
    cached_fp = cache_entry.get("fingerprint")
    if current_fp != cached_fp:
        return False

    try:
        import os
        # ========== 优化项15：统一去除 \\?\ 前缀 ==========
        src_str = str(src).replace('\\\\?\\', '')
        target_str_clean = str(target).replace('\\\\?\\', '')
        if config.get("link_type") == "hard":
            return os.path.samefile(src_str, target_str_clean)
        else:
            return Path(target_str_clean).resolve() == Path(src_str).resolve()
    except Exception:
        return False


def load_ai_parse_cache() -> Dict[str, Any]:
    with ai_parse_cache_lock:
        cache_path = Path(AI_PARSE_CACHE_FILE)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


def save_ai_parse_cache(cache: Dict[str, Any]):
    with ai_parse_cache_lock:
        temp_file = AI_PARSE_CACHE_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        Path(temp_file).replace(AI_PARSE_CACHE_FILE)
