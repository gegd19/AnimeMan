#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕中心 API 路由（含目录上下文传递）
包含本地字幕扫描匹配、AI 匹配入库与批量重命名
"""

from pathlib import Path
from flask import request, jsonify
from core import subtitle_handler, config_manager
from core.cache_manager import load_cache
from .task_state import progress_callback

CONFIG_PATH = "auto_config.json"


def _wrap_callback(cb):
    """将 progress_callback(current, total, msg, level) 包装为可同时处理两参数和四参数的 log_func。"""
    if cb is None:
        return None

    def wrapped(*args):
        if len(args) == 1:
            cb(0, 0, args[0], "info")
        elif len(args) == 2:
            cb(0, 0, args[0], args[1])
        elif len(args) == 4:
            cb(*args)
        else:
            cb(0, 0, str(args), "info")
    return wrapped


def register(app):
    @app.route('/api/subtitle/scan', methods=['POST'])
    def scan_subtitle_folder():
        """扫描本地字幕文件夹（返回结果已包含目录上下文）"""
        data = request.json or {}
        folder = data.get('folder', '')
        if not folder:
            config = config_manager.load_config(CONFIG_PATH)
            folder = config.get("subtitle_center", {}).get("default_source_folder", "")
        if not folder:
            return jsonify({"error": "未指定字幕文件夹"}), 400

        try:
            config = config_manager.load_config(CONFIG_PATH)
            subs = subtitle_handler.scan_subtitle_folder(folder, config)
            return jsonify({"subtitles": subs, "folder": folder})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/subtitle/match', methods=['POST'])
    def match_subtitles():
        """本地字幕与媒体库模糊匹配（传递目录上下文提升准确率）"""
        data = request.json
        subtitles = data.get('subtitles', [])
        threshold = data.get('threshold', 60)

        config = config_manager.load_config(CONFIG_PATH)
        library = subtitle_handler.get_media_library_from_cache(config)

        results = []
        for sub in subtitles:
            context_dirs = [sub.get("parent_dir", ""), sub.get("grandparent_dir", "")]
            context_dirs = [d for d in context_dirs if d]
            candidates = subtitle_handler.match_subtitle_to_media(
                sub['name'], library, threshold, context_dirs
            )
            results.append({
                "subtitle": sub,
                "candidates": candidates,
                "best_match": candidates[0] if candidates else None
            })

        return jsonify({"results": results, "library_size": len(library.get("movies", [])) + len(library.get("tv_shows", []))})

    @app.route('/api/subtitle/execute', methods=['POST'])
    def execute_subtitle():
        """执行本地字幕整理（同步、重命名、移动/链接）"""
        data = request.json
        items = data.get('items', [])

        config = config_manager.load_config(CONFIG_PATH)
        wrapped_log = _wrap_callback(progress_callback)
        success = 0
        for item in items:
            if subtitle_handler.execute_subtitle_organization(
                item['subtitle_path'],
                item['target_media'],
                config,
                item.get('auto_sync', False),
                wrapped_log
            ):
                success += 1

        return jsonify({"status": "success", "processed": success, "total": len(items)})

    @app.route('/api/media/library', methods=['GET'])
    def get_media_library():
        """获取已入库媒体库列表（用于字幕手动选择）"""
        config = config_manager.load_config(CONFIG_PATH)
        library = subtitle_handler.get_media_library_from_cache(config)
        return jsonify(library)

    @app.route('/api/subtitle/ai_match', methods=['POST'])
    def ai_match_subtitles():
        """AI 将字幕文件匹配到指定剧集（需提供 show_info）"""
        data = request.json
        files = data.get('files', [])
        show_info = data.get('show_info', {})
        if not files or not show_info:
            return jsonify({"error": "缺少必要参数"}), 400

        config = config_manager.load_config(CONFIG_PATH)
        wrapped_log = _wrap_callback(progress_callback)
        results = subtitle_handler.ai_match_subtitles_to_show(files, show_info, config, wrapped_log)
        return jsonify({"results": results})

    @app.route('/api/subtitle/batch_rename', methods=['POST'])
    def batch_rename_subtitles():
        """批量重命名字幕文件"""
        data = request.json
        renames = data.get('renames', [])
        if not renames:
            return jsonify({"error": "无重命名项"}), 400

        wrapped_log = _wrap_callback(progress_callback)
        result = subtitle_handler.batch_rename_subtitles(renames, wrapped_log)
        return jsonify({"status": "success", "success": result["success"], "failed": result["failed"]})

    # ---------- 新增：AI 解析字幕文件名（用于分组优化） ----------
    @app.route('/api/subtitle/ai_parse', methods=['POST'])
    def ai_parse_subtitles():
        """AI 解析字幕文件名（单文件或多文件），返回解析结果"""
        data = request.json
        files = data.get('files', [])
        if not files:
            return jsonify({"error": "缺少文件列表"}), 400

        config = config_manager.load_config(CONFIG_PATH)
        wrapped_log = _wrap_callback(progress_callback)
        parsed = subtitle_handler.ai_parse_subtitle_files(files, config, wrapped_log)
        return jsonify({"results": parsed})

    # ---------- 新增：单字幕匹配接口（用于 AI 分组优化） ----------
    @app.route('/api/subtitle/match_single', methods=['POST'])
    def match_single_subtitle():
        """为单个字幕进行媒体库匹配，支持强制标题（用于 AI 分组后批量匹配）"""
        data = request.json
        sub = data.get('subtitle', {})
        threshold = data.get('threshold', 60)
        force_title = data.get('force_title')

        if not sub:
            return jsonify({"error": "缺少字幕信息"}), 400

        config = config_manager.load_config(CONFIG_PATH)
        library = subtitle_handler.get_media_library_from_cache(config)

        match_name = force_title if force_title else sub.get('name', '')
        context_dirs = [sub.get("parent_dir", ""), sub.get("grandparent_dir", "")]
        context_dirs = [d for d in context_dirs if d]

        candidates = subtitle_handler.match_subtitle_to_media(
            match_name, library, threshold, context_dirs
        )

        return jsonify({
            "best_match": candidates[0] if candidates else None,
            "candidates": candidates
        })
