#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务控制相关 API 路由 (run, stop, status, log)
支持强制重置任务状态
"""

import threading
from pathlib import Path
from flask import request, jsonify

from core import media_processor
from .task_state import (
    progress_callback,
    reset_task_state,
    set_task_running,
    is_task_running,
    get_task_status,
    request_stop,
    force_reset
)
from .auth import require_auth

CONFIG_PATH = "auto_config.json"
LOG_FILE = "auto_processor_errors.log"


def register(app):
    @app.route('/api/run', methods=['POST'])
    @require_auth
    def run_task():
        if is_task_running():
            return jsonify({"status": "error", "message": "已有任务在运行中"}), 400

        set_task_running()

        def task_wrapper():
            try:
                media_processor.stop_processing.clear()
                media_processor.run_processor_with_callback(CONFIG_PATH, progress_callback)
            except Exception as e:
                progress_callback(0, 0, f"任务异常: {e}", "error")
            finally:
                reset_task_state()

        threading.Thread(target=task_wrapper, daemon=False).start()
        return jsonify({"status": "started"})

    @app.route('/api/stop', methods=['POST'])
    @require_auth
    def stop_task():
        """
        停止任务：
        - 正常停止：设置停止请求标志，由任务循环自行检查并退出
        - 强制重置：当 force=1 时，直接清理任务状态（用于任务卡死时）
        """
        force = request.args.get('force', '0') == '1'

        if force or not is_task_running():
            # 强制重置状态，清理残留
            force_reset()
            media_processor.stop_processing.set()  # 确保核心处理器也收到停止信号
            progress_callback(0, 0, "任务状态已强制重置", "warning")
            return jsonify({"status": "reset", "message": "任务状态已强制重置"})

        # 正常停止流程
        media_processor.stop_processing.set()
        request_stop()
        progress_callback(0, 0, "正在停止任务...", "warning")
        return jsonify({"status": "stopping"})

    @app.route('/api/status', methods=['GET'])
    def get_status():
        return jsonify(get_task_status())

    @app.route('/api/log', methods=['GET'])
    def get_full_log():
        log_path = Path(LOG_FILE)
        if not log_path.exists():
            return jsonify({"log": ""})
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-100:]
            return jsonify({"log": "".join(lines)})
        except Exception:
            return jsonify({"log": "无法读取日志文件"})
