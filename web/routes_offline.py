#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线 AI 预解析相关 API
"""

import threading
import time
from flask import jsonify
from core import config_manager
from core.offline_ai_preparser import (
    scan_source_folders,
    save_raw_cache,
    load_raw_cache,
    load_ai_preparse_cache,
    run_ai_preparse
)
from .auth import require_auth

CONFIG_PATH = "auto_config.json"

_scan_lock = threading.Lock()
_parse_lock = threading.Lock()

_scan_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "message": "",
    "start_time": 0
}

_parse_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "message": "",
    "start_time": 0
}


def register(app):
    @app.route('/api/offline/status', methods=['GET'])
    def offline_preparse_status():           # 改名
        raw = load_raw_cache()
        ai_cache = load_ai_preparse_cache()
        total_folders = len(raw)
        total_files = sum(len(v) for v in raw.values())
        cached_folders = len(ai_cache)

        return jsonify({
            "total_folders": total_folders,
            "total_files": total_files,
            "cached_folders": cached_folders,
            "scanning": _scan_status["running"],
            "scan_progress": _scan_status["progress"],
            "scan_total": _scan_status["total"],
            "scan_message": _scan_status["message"],
            "parsing": _parse_status["running"],
            "parse_progress": _parse_status["progress"],
            "parse_total": _parse_status["total"],
            "parse_message": _parse_status["message"]
        })

    @app.route('/api/offline/scan', methods=['POST'])
    @require_auth
    def offline_preparse_scan():            # 改名
        global _scan_status
        if _scan_lock.locked():
            return jsonify({"status": "error", "message": "已有扫描任务在进行中"}), 409

        def _scan():
            global _scan_status
            with _scan_lock:
                _scan_status["running"] = True
                _scan_status["progress"] = 0
                _scan_status["total"] = 0
                _scan_status["message"] = "正在扫描源文件夹..."
                _scan_status["start_time"] = time.time()

                config = config_manager.load_config(CONFIG_PATH)
                raw = scan_source_folders(config)
                save_raw_cache(raw)

                total_folders = len(raw)
                total_files = sum(len(v) for v in raw.values())
                _scan_status["progress"] = total_folders
                _scan_status["total"] = total_folders
                _scan_status["message"] = f"扫描完成，共 {total_folders} 个文件夹，{total_files} 个视频文件"
                _scan_status["running"] = False

        threading.Thread(target=_scan, daemon=True).start()
        return jsonify({"status": "success", "message": "扫描任务已启动"})

    @app.route('/api/offline/parse', methods=['POST'])
    @require_auth
    def offline_preparse_parse():           # 改名
        global _parse_status
        if _parse_lock.locked():
            return jsonify({"status": "error", "message": "已有解析任务在进行中"}), 409

        config = config_manager.load_config(CONFIG_PATH)
        if not config.get("ai_parser", {}).get("enabled"):
            return jsonify({"status": "error", "message": "AI 解析未启用"}), 400

        def _parse():
            global _parse_status
            with _parse_lock:
                _parse_status["running"] = True
                _parse_status["progress"] = 0
                _parse_status["total"] = 0
                _parse_status["message"] = "正在准备预解析..."
                _parse_status["start_time"] = time.time()

                result = run_ai_preparse(config)
                total = len(load_raw_cache())
                success = len(result)
                _parse_status["progress"] = total
                _parse_status["total"] = total
                _parse_status["message"] = f"预解析完成，成功 {success}/{total} 个文件夹"
                _parse_status["running"] = False

        threading.Thread(target=_parse, daemon=True).start()
        return jsonify({"status": "success", "message": "预解析任务已启动"})
