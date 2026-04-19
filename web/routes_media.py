#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体库管理 API（删除已处理文件等）
"""

import shutil
from pathlib import Path
from flask import request, jsonify
from core import cache_manager, config_manager
from .auth import require_auth

CONFIG_PATH = "auto_config.json"


def register(app):
    @app.route('/api/media/delete', methods=['POST'])
    @require_auth
    def delete_media_item():
        """删除单个已处理文件（目标链接/文件），并清理缓存"""
        data = request.json
        src_path = data.get('src_path')
        delete_source = data.get('delete_source', False)

        if not src_path:
            return jsonify({"status": "error", "message": "缺少源路径"}), 400

        try:
            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                entry = cache.get(src_path)
                if not entry:
                    return jsonify({"status": "error", "message": "缓存中无此记录"}), 404

                target = Path(entry.get("target", ""))
                media_type = entry.get("media_type")

                if target.exists():
                    target.unlink()

                if media_type == "movie":
                    movie_dir = target.parent
                    for sub in movie_dir.glob(f"{target.stem}.*"):
                        if sub.suffix.lower() in ['.ass', '.ssa', '.srt', '.vtt']:
                            sub.unlink()
                    (target.parent / "movie.nfo").unlink(missing_ok=True)
                elif media_type == "tv":
                    season_dir = target.parent
                    for sub in season_dir.glob(f"{target.stem}.*"):
                        if sub.suffix.lower() in ['.ass', '.ssa', '.srt', '.vtt']:
                            sub.unlink()
                    for nfo in target.parent.glob(f"{target.stem}*.nfo"):
                        nfo.unlink(missing_ok=True)

                del cache[src_path]
                cache_manager.save_cache(cache)

                if delete_source:
                    src = Path(src_path)
                    if src.exists():
                        src.unlink()

                return jsonify({"status": "success"})

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/media/batch_delete', methods=['POST'])
    @require_auth
    def batch_delete_media_items():
        """批量删除已处理文件"""
        data = request.json
        src_paths = data.get('src_paths', [])
        delete_source = data.get('delete_source', False)

        if not src_paths:
            return jsonify({"status": "error", "message": "无文件路径"}), 400

        success = 0
        failed = 0
        with cache_manager.cache_lock:
            cache = cache_manager.load_cache()
            for src_path in src_paths:
                try:
                    entry = cache.get(src_path)
                    if not entry:
                        failed += 1
                        continue

                    target = Path(entry.get("target", ""))
                    media_type = entry.get("media_type")

                    if target.exists():
                        target.unlink()

                    if media_type == "movie":
                        movie_dir = target.parent
                        for sub in movie_dir.glob(f"{target.stem}.*"):
                            if sub.suffix.lower() in ['.ass', '.ssa', '.srt', '.vtt']:
                                sub.unlink()
                        (target.parent / "movie.nfo").unlink(missing_ok=True)
                    elif media_type == "tv":
                        season_dir = target.parent
                        for sub in season_dir.glob(f"{target.stem}.*"):
                            if sub.suffix.lower() in ['.ass', '.ssa', '.srt', '.vtt']:
                                sub.unlink()
                        for nfo in target.parent.glob(f"{target.stem}*.nfo"):
                            nfo.unlink(missing_ok=True)

                    del cache[src_path]

                    if delete_source:
                        src = Path(src_path)
                        if src.exists():
                            src.unlink()

                    success += 1
                except Exception:
                    failed += 1

            cache_manager.save_cache(cache)

        return jsonify({"status": "success", "success": success, "failed": failed})
