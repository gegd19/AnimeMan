#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目录浏览 API 路由（安全增强版）
限制可浏览的根目录为显式配置的源、目标、字幕和浏览目录
"""

import platform
from pathlib import Path
from flask import request, jsonify
from core import config_manager

CONFIG_PATH = "auto_config.json"


def get_allowed_roots(config):
    """Only explicit media/subtitle/browse roots grant access, never ancestors."""
    values = list(config.get("source_folders", [])) + list(config.get("browse_roots", []))
    values += [config.get("tv_target_folder"), config.get("movie_target_folder"),
               config.get("subtitle_center", {}).get("default_source_folder")]
    return sorted({Path(value).resolve() for value in values if isinstance(value, str) and value.strip()}, key=str)


def is_path_allowed(request_path: str, allowed_roots: list) -> bool:
    try:
        path = Path(request_path).resolve()
        return any(path == root or root in path.parents for root in allowed_roots)
    except (OSError, ValueError, RuntimeError):
        return False


def register(app):
    config_path = app.config.get("CONFIG_PATH", CONFIG_PATH)

    @app.route('/api/drives', methods=['GET'])
    def get_drives():
        """返回允许的根目录列表（替代系统盘符）"""
        config = config_manager.load_config(config_path)
        allowed = get_allowed_roots(config)
        drives = []
        seen = set()
        for p in allowed:
            if p.exists() and str(p) not in seen:
                seen.add(str(p))
                drives.append({"name": p.name or str(p), "path": str(p)})
        # 按路径排序
        drives.sort(key=lambda x: x["path"])
        return jsonify(drives)

    @app.route('/api/browse', methods=['GET'])
    def browse_directory():
        req_path = request.args.get('path', '')
        if not req_path:
            return jsonify([])

        try:
            base_path = Path(req_path).resolve()
        except Exception:
            return jsonify([])

        config = config_manager.load_config(config_path)
        allowed_roots = get_allowed_roots(config)

        if not is_path_allowed(str(base_path), allowed_roots):
            return jsonify({"error": "禁止访问此目录"}), 403

        if not base_path.exists() or not base_path.is_dir():
            return jsonify([])

        parent = str(base_path.parent) if base_path.parent != base_path else None
        # 检查父目录是否也允许（否则前端隐藏“上一级”按钮）
        if parent and not is_path_allowed(parent, allowed_roots):
            parent = None

        dirs = []
        try:
            for item in base_path.iterdir():
                if item.is_dir() and not item.name.startswith('.') and is_path_allowed(str(item), allowed_roots):
                    dirs.append({"name": item.name, "path": str(item)})
        except PermissionError:
            pass

        dirs.sort(key=lambda x: x["name"].lower())
        return jsonify({"current": str(base_path), "parent": parent, "dirs": dirs})
