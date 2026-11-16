#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器缓存操作：失败缓存保存、旧文件清理
"""

import time
from pathlib import Path
from .execution_mode import is_preview, execution_scope
from typing import Dict, Any, Optional, Callable

from . import cache_manager
from .failure_policy import make_failure

LOG_WARNING = "warning"


def save_failed_cache(
    src_path: Path,
    reason: str,
    cache_dict: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> None:
    """记录处理失败的文件到缓存"""
    if is_preview():
        return
    src_str = str(src_path.resolve())
    with cache_manager.cache_lock:
        if cache_dict.get(src_str, {}).get("target") and cache_dict[src_str].get("media_type") != "failed":
            return
        cache_dict[src_str] = make_failure(src_path, reason)
    if log_func:
        log_func(f"⚠️ 无法自动处理，已记录失败缓存: {src_path.name} ({reason})", LOG_WARNING)


@execution_scope
def remove_cached_artifacts(src: Path, entry: dict, config: dict, previous=False, references=None):
    """Delete only an unreferenced target and explicitly owned artifacts.

    Legacy records without ownership manifests leave metadata for manual review.
    """
    from .path_safety import absolute_link_path, validate_cached_target, validate_target_path
    from .library_transaction import library_lock

    with library_lock:
        target = validate_cached_target(src, entry, config)
        if is_preview(config):
            return
        others = references if references is not None else cache_manager.load_cache()
        entries = [value for key, value in others.items()
                   if isinstance(value, dict) and value.get("target")
                   and not (key == str(src.resolve()) and value.get("target") == entry.get("target"))]
        other_targets = [absolute_link_path(value["target"]) for value in entries]
        candidates = [] if target in other_targets else [target]
        for artifact in entry.get("artifacts", []):
            path = validate_target_path(src, artifact, config, entry.get("media_type"))
            # Never collect shared metadata while another version/episode still
            # lives beneath its directory. Unknown ownership stays untouched.
            if path == target or any(path.parent in other.parents for other in other_targets):
                continue
            if any(str(path) in value.get("artifacts", []) for value in entries):
                continue
            candidates.append(path)
        paths = [validate_target_path(src, path, config, entry.get("media_type")) for path in candidates]
        for path in dict.fromkeys(paths):
            path = validate_target_path(src, path, config, entry.get("media_type"))
            if path.exists() or path.is_symlink():
                path.unlink()


@execution_scope
def cleanup_previous_artifacts(src: Path, config: dict) -> None:
    """Reject ambiguous legacy records before deleting any prior artifacts."""
    from .library_transaction import library_lock
    with library_lock, cache_manager.cache_lock:
        src_str = str(src.resolve())
        cache = cache_manager.prepare_cache_for_removal(config, sources={src_str})
        entry = cache.get(src_str)
        if entry is None or entry.get("media_type") == "failed":
            return
        remove_cached_artifacts(src, entry, config, previous=True)
