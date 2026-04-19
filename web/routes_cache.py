#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
已处理缓存管理 API（支持分页、排序、详细路径、批量删除、单条重试并设100%置信度）
"""

from pathlib import Path
from flask import request, jsonify
from core import cache_manager, config_manager
from .auth import require_auth

CONFIG_PATH = "auto_config.json"


def register(app):
    @app.route('/api/processed_cache', methods=['GET'])
    def get_processed_cache():
        """获取非失败的已处理缓存记录，支持分页和排序"""
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        sort_by = request.args.get('sort', 'processed_time')
        order = request.args.get('order', 'desc')

        cache = cache_manager.load_cache()
        items = []
        for src_str, entry in cache.items():
            if entry.get("media_type") == "failed":
                continue
            src_path = Path(src_str)
            target = Path(entry.get("target", ""))

            parent_dir = src_path.parent.name
            grandparent_dir = src_path.parent.parent.name if src_path.parent.parent != src_path.parent else ""

            items.append({
                "src": src_str,
                "src_name": src_path.name,
                "parent_dir": parent_dir,
                "grandparent_dir": grandparent_dir,
                "target": str(target),
                "target_exists": target.exists(),
                "media_type": entry.get("media_type"),
                "title": entry.get("title", ""),
                "season": entry.get("season"),
                "episode": entry.get("episode"),
                "year": entry.get("year"),
                "tmdb_id": entry.get("tmdb_id"),
                "confidence": entry.get("confidence", 0),
                "processed_time": entry.get("processed_time", 0)
            })

        reverse = (order == 'desc')
        if sort_by == 'confidence':
            items.sort(key=lambda x: x['confidence'], reverse=reverse)
        elif sort_by == 'title':
            items.sort(key=lambda x: x['title'].lower(), reverse=reverse)
        elif sort_by == 'src_name':
            items.sort(key=lambda x: x['src_name'].lower(), reverse=reverse)
        else:
            items.sort(key=lambda x: x['processed_time'], reverse=reverse)

        total = len(items)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_items = items[start:end]

        return jsonify({
            "items": paginated_items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if total else 1
        })

    @app.route('/api/processed_cache/clear', methods=['POST'])
    @require_auth
    def clear_processed_cache():
        """清空所有非失败的已处理缓存"""
        with cache_manager.cache_lock:
            cache = cache_manager.load_cache()
            keys_to_remove = [k for k, v in cache.items() if v.get("media_type") != "failed"]
            for k in keys_to_remove:
                del cache[k]
            cache_manager.save_cache(cache)
        return jsonify({"status": "success", "removed": len(keys_to_remove)})

    @app.route('/api/processed_cache/delete', methods=['POST'])
    @require_auth
    def delete_processed_cache_item():
        """删除单条已处理缓存"""
        data = request.json
        src_path = data.get('src_path')
        if not src_path:
            return jsonify({"status": "error", "message": "缺少源路径"}), 400

        with cache_manager.cache_lock:
            cache = cache_manager.load_cache()
            if src_path in cache:
                del cache[src_path]
                cache_manager.save_cache(cache)
                return jsonify({"status": "success"})
            else:
                return jsonify({"status": "error", "message": "记录不存在"}), 404

    @app.route('/api/processed_cache/batch_delete', methods=['POST'])
    @require_auth
    def batch_delete_processed_cache():
        """批量删除已处理缓存"""
        data = request.json
        src_paths = data.get('src_paths', [])
        if not src_paths:
            return jsonify({"status": "error", "message": "缺少源路径列表"}), 400

        with cache_manager.cache_lock:
            cache = cache_manager.load_cache()
            deleted = 0
            for path in src_paths:
                if path in cache:
                    del cache[path]
                    deleted += 1
            cache_manager.save_cache(cache)
        return jsonify({"status": "success", "deleted": deleted})

    @app.route('/api/processed_cache/retry', methods=['POST'])
    @require_auth
    def retry_processed_cache_item():
        """对已处理的缓存记录重新执行完整处理流程，并将置信度设为 100%"""
        data = request.json
        src_path = data.get('src_path')
        if not src_path:
            return jsonify({"status": "error", "message": "缺少源路径"}), 400

        src = Path(src_path)
        if not src.exists():
            return jsonify({"status": "error", "message": "源文件不存在"}), 404

        config = config_manager.load_config(CONFIG_PATH)

        # 清理旧的目标文件和缓存记录
        from core.processor_cache_ops import cleanup_previous_artifacts
        cleanup_previous_artifacts(src, config)

        with cache_manager.cache_lock:
            cache = cache_manager.load_cache()
            if src_path in cache:
                del cache[src_path]
                cache_manager.save_cache(cache)

        # 日志回调适配（使用 task_state 的进度回调）
        from .task_state import progress_callback
        def log_func(msg, level="info"):
            # 包装为适应 core 层的回调格式
            progress_callback(0, 0, msg, level)

        # 调用核心处理函数
        from core.processor_core import process_video
        temp_cache = {}
        success = process_video(src, config, temp_cache, log_func)

        if success:
            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                cache.update(temp_cache)
                # 强制将新记录的置信度设为 100（代表用户手动确认）
                if src_path in cache:
                    cache[src_path]["confidence"] = 100
                cache_manager.save_cache(cache)
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "重新处理失败，请查看日志"}), 500
