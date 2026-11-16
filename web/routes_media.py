#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Media removal uses validated library entries, including broken symlinks."""

from core.cancellation import check_cancelled, stop_processing
from pathlib import Path
from flask import request, jsonify
from .task_state import request_config
from core import cache_manager
from core.library_transaction import library_lock
from core.path_safety import UnsafePathError, validate_source_path
from core.processor_cache_ops import remove_cached_artifacts
from .auth import require_auth

CONFIG_PATH = "auto_config.json"


def _remove(src_path, entry, config, delete_source):
    check_cancelled()
    # Validate a requested source deletion before any target or cache change.
    source = validate_source_path(src_path, config) if delete_source else None
    remove_cached_artifacts(Path(src_path), entry, config)
    if source is not None and (source.exists() or source.is_symlink()):
        source.unlink()


def register(app):
    config_path = app.config.get("CONFIG_PATH", CONFIG_PATH)

    @app.route('/api/media/delete', methods=['POST'])
    @require_auth
    def delete_media_item():
        data = request.get_json() or {}
        src_path = data.get('src_path')
        delete_source = data.get('delete_source', False)
        if type(delete_source) is not bool:
            return jsonify({"status": "error", "message": "delete_source 必须为布尔值"}), 400
        if not isinstance(src_path, str) or not src_path:
            return jsonify({"status": "error", "message": "缺少源路径"}), 400
        try:
            config = request_config(config_path)
            with library_lock, cache_manager.cache_lock:
                cache = cache_manager.prepare_cache_for_removal(config)
                entry = cache.get(src_path)
                if entry is None:
                    return jsonify({"status": "error", "message": "缓存中无此记录"}), 404
                _remove(src_path, entry, config, delete_source)
                del cache[src_path]
                cache_manager.save_cache(cache)
            return jsonify({"status": "success"})
        except UnsafePathError as exc:
            return jsonify({"status": "error", "code": "needs_reindex", "message": str(exc)}), 409
        except OSError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 500

    @app.route('/api/media/batch_delete', methods=['POST'])
    @require_auth
    def batch_delete_media_items():
        data = request.get_json() or {}
        src_paths = data.get('src_paths', [])
        delete_source = data.get('delete_source', False)
        if type(delete_source) is not bool:
            return jsonify({"status": "error", "message": "delete_source 必须为布尔值"}), 400
        if not isinstance(src_paths, list) or not src_paths or any(not isinstance(p, str) or not p for p in src_paths):
            return jsonify({"status": "error", "message": "无效的源路径列表"}), 400
        config = request_config(config_path)
        success = 0
        errors = []
        with library_lock, cache_manager.cache_lock:
            cache = cache_manager.prepare_cache_for_removal(config)
            for src_path in src_paths:
                if stop_processing.is_set():
                    break
                entry = cache.get(src_path)
                if entry is None:
                    errors.append({"src_path": src_path, "message": "缓存中无此记录"})
                    continue
                try:
                    _remove(src_path, entry, config, delete_source)
                except (UnsafePathError, OSError) as exc:
                    errors.append({"src_path": src_path, "message": str(exc)})
                    continue
                del cache[src_path]
                success += 1
            cache_manager.save_cache(cache)
        return jsonify({"status": "cancelled" if stop_processing.is_set() else "success", "success": success, "failed": len(errors), "errors": errors})
