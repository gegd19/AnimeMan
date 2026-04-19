#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目录浏览 API 路由（安全增强版）
限制可浏览的根目录为配置中的源/目标文件夹及其父级
"""

import platform
from pathlib import Path
from flask import request, jsonify
from core import config_manager

CONFIG_PATH = "auto_config.json"


def get_allowed_roots(config):
    """从配置中提取允许浏览的根目录"""
    roots = set()

    # 源文件夹
    for folder in config.get("source_folders", []):
        p = Path(folder).resolve()
        roots.add(p)
        # 允许其父级（最多向上两级，方便导航到挂载点）
        if p.parent != p:
            roots.add(p.parent)
        if p.parent.parent != p.parent:
            roots.add(p.parent.parent)

    # 剧集目标
    tv_target = config.get("tv_target_folder", "")
    if tv_target:
        p = Path(tv_target).resolve()
        roots.add(p)
        if p.parent != p:
            roots.add(p.parent)
        if p.parent.parent != p.parent:
            roots.add(p.parent.parent)

    # 电影目标
    movie_target = config.get("movie_target_folder", "")
    if movie_target:
        p = Path(movie_target).resolve()
        roots.add(p)
        if p.parent != p:
            roots.add(p.parent)
        if p.parent.parent != p.parent:
            roots.add(p.parent.parent)

    # 字幕默认文件夹
    sub_center = config.get("subtitle_center", {})
    sub_folder = sub_center.get("default_source_folder", "")
    if sub_folder:
        p = Path(sub_folder).resolve()
        roots.add(p)
        if p.parent != p:
            roots.add(p.parent)
        if p.parent.parent != p.parent:
            roots.add(p.parent.parent)

    return list(roots)


def is_path_allowed(request_path: str, allowed_roots: list) -> bool:
    """检查请求的路径是否在允许的根目录范围内"""
    try:
        req = Path(request_path).resolve()
    except Exception:
        return False

    for root in allowed_roots:
        try:
            root_resolved = root.resolve()
            # 检查请求路径是否等于根目录或是其子目录
            if req == root_resolved or root_resolved in req.parents or req.parents == root_resolved.parents:
                # 更精确的判断：req 以 root 开头
                try:
                    req.relative_to(root_resolved)
                    return True
                except ValueError:
                    continue
        except Exception:
            continue
    return False


def register(app):
    @app.route('/api/drives', methods=['GET'])
    def get_drives():
        """返回允许的根目录列表（替代系统盘符）"""
        config = config_manager.load_config(CONFIG_PATH)
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

        config = config_manager.load_config(CONFIG_PATH)
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
                if item.is_dir() and not item.name.startswith('.'):
                    dirs.append({"name": item.name, "path": str(item)})
        except PermissionError:
            pass

        dirs.sort(key=lambda x: x["name"].lower())
        return jsonify({"current": str(base_path), "parent": parent, "dirs": dirs})
