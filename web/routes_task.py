#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务控制相关 API 路由 (run, stop, status, log)
支持强制重置任务状态
"""

import threading
from pathlib import Path
from core.runtime_paths import log_file
from flask import request, jsonify

from core import media_processor
from . import task_state
from flask import g
from .auth import require_auth

CONFIG_PATH = "auto_config.json"
LOG_FILE = "auto_processor_errors.log"


def register(app):
    config_path = app.config.get("CONFIG_PATH", CONFIG_PATH)

    @app.route('/api/run', methods=['POST'])
    @require_auth
    def run_task():
        snapshot = g.request_config
        task = task_state.launch_task('organize', snapshot,
            lambda config, callback: media_processor.run_processor_with_callback(
                config_path, callback, effective_config=config), thread_factory=threading.Thread)
        if task is None:
            return jsonify({"status":"error", "message":"已有写入任务运行或正在停止"}), 409
        return jsonify({"status":"started", "task_id":task.task_id})

    @app.route('/api/stop', methods=['POST'])
    @require_auth
    def stop_task():
        identity = request.args.get('task_id')
        observed_id = task_state.get_task_status()['task_id']
        if identity and identity != observed_id:
            return jsonify({'status':'error', 'message':'任务身份已过期'}), 409
        stopping = task_state.request_stop(identity)
        if request.args.get('force') == '1':
            if not task_state.force_reset(identity or observed_id):
                return jsonify({"status":"stopping", "message":"工作线程尚未退出，不能重置或启动新任务"}), 409
            return jsonify({"status":"reset"})
        return jsonify({"status":"stopping" if stopping else "idle"})

    @app.route('/api/status', methods=['GET'])
    def get_status():
        return jsonify(task_state.get_task_status())

    @app.route('/api/log', methods=['GET'])
    def get_full_log():
        log_path = log_file()
        if not log_path.exists():
            return jsonify({"log": ""})
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-100:]
            return jsonify({"log": "".join(lines)})
        except Exception:
            return jsonify({"log": "无法读取日志文件"})
