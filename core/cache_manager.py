#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存管理模块
处理文件处理缓存和 AI 解析缓存的读写、指纹计算
"""

from .json_store import read_json, write_json, update_json, backup_json, CacheCorruptionError
import json
import hashlib
import threading
import uuid
from pathlib import Path
from .execution_mode import skip_preview_write, is_preview, execution_scope
from .runtime_paths import cache_file, writable
from typing import Dict, Any

CACHE_FILE = "auto_processed_cache.json"
AI_PARSE_CACHE_FILE = "ai_parse_cache.json"

cache_lock = threading.RLock()
ai_parse_cache_lock = threading.RLock()


def load_cache() -> Dict[str, Any]:
    with cache_lock:
        return read_json(cache_file(CACHE_FILE))


@skip_preview_write
def save_cache(cache: Dict[str, Any]):
    with cache_lock:
        from .derived_cache import invalidate
        path = cache_file(CACHE_FILE)
        write_json(path, cache)
        invalidate(path)


@execution_scope
def prepare_cache_for_removal(config, sources=None):
    """Back up and quarantine unsafe legacy records before destructive actions.

    Never infer a library path from a source path: ambiguity requires reindexing.
    The caller may already hold cache_lock (an RLock).
    """
    if is_preview():
        return load_cache()
    from .path_safety import UnsafePathError, validate_cached_target

    with cache_lock:
        cache = load_cache()
        changed = False
        for src, entry in list(cache.items()):
            if sources is not None and src not in sources:
                continue
            if not isinstance(entry, dict):
                cache[src] = {"legacy_entry": entry, "needs_reindex": True,
                              "reindex_reason": "无效的旧缓存记录"}
                changed = True
                continue
            if entry.get("media_type") == "failed" or entry.get("needs_reindex"):
                continue
            try:
                validate_cached_target(src, entry, config)
            except UnsafePathError as exc:
                entry["needs_reindex"] = True
                entry["reindex_reason"] = str(exc)
                changed = True
        if changed:
            original = cache_file(CACHE_FILE)
            backup = original.with_name(original.name + ".t01-" + uuid.uuid4().hex + ".bak")
            # Exclusive creation and a complete backup precede the atomic save.
            with backup.open("xb") as stream:
                stream.write(original.read_bytes())
            save_cache(cache)
        return cache


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
        return read_json(cache_file(AI_PARSE_CACHE_FILE))


@skip_preview_write
def save_ai_parse_cache(cache: Dict[str, Any]):
    with ai_parse_cache_lock:
        write_json(cache_file(AI_PARSE_CACHE_FILE), cache)


@skip_preview_write
def update_records(changes):
    with cache_lock:
        from .derived_cache import invalidate
        path = cache_file(CACHE_FILE)
        updated = update_json(path, lambda current: current.update(changes))
        invalidate(path)
        return updated


@skip_preview_write
def update_ai_parse_records(changes):
    with ai_parse_cache_lock:
        return update_json(cache_file(AI_PARSE_CACHE_FILE), lambda current: current.update(changes))


@skip_preview_write
def backup_legacy_failures(sources):
    """Back up once before this run replaces any pre-policy failed records."""
    with cache_lock:
        current = load_cache()
        if any(isinstance(current.get(str(src)), dict)
               and current[str(src)].get('media_type') == 'failed'
               and not current[str(src)].get('config_fingerprint') for src in sources):
            return backup_json(cache_file(CACHE_FILE))
