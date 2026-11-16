#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线 AI 预解析相关 API
"""

import threading
import time
from flask import jsonify
from core.offline_ai_preparser import (
    scan_source_folders,
    save_raw_cache,
    load_raw_cache,
    load_ai_preparse_cache,
    run_ai_preparse, preparse_summary
)
from .auth import require_auth
from . import task_state
from .task_state import request_config
from core.cancellation import check_cancelled, ProcessingCancelled

CONFIG_PATH = "auto_config.json"

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
    config_path = app.config.get("CONFIG_PATH", CONFIG_PATH)

    @app.route('/api/offline/status', methods=['GET'])
    def offline_preparse_status():           # 改名
        raw = load_raw_cache()
        ai_cache = load_ai_preparse_cache()
        total_folders = len(raw)
        total_files = sum(len(v) for v in raw.values())
        cached_folders = len(ai_cache)

        state = task_state.get_task_status()
        return jsonify({
            "total_folders": total_folders,
            "total_files": total_files,
            "cached_folders": cached_folders,
            "scanning": state["running"] and state.get("kind") == "offline_scan",
            "scan_progress": _scan_status["progress"],
            "scan_total": _scan_status["total"],
            "scan_message": _scan_status["message"],
            "parsing": state["running"] and state.get("kind") == "offline_parse",
            "parse_progress": _parse_status["progress"],
            "parse_total": _parse_status["total"],
            "parse_message": _parse_status["message"]
        })

    def start_offline(kind, status, operation):
        def worker(config, callback):
            status.update(running=True, progress=0, total=0, message='处理中...', start_time=time.time())
            try:
                result, total, message = operation(config)
                status.update(progress=total, total=total, message=message)
                callback(total, total, message, 'info')
                return result
            except ProcessingCancelled:
                status['message'] = '任务已取消'
                raise
            except Exception as exc:
                status['message'] = f'任务失败：{exc}'
                raise
            finally:
                status['running'] = False
        task = task_state.launch_task(kind, request_config(config_path), worker, thread_factory=threading.Thread)
        if task is None:
            return jsonify({'status':'error', 'message':'已有写入任务运行或正在停止'}), 409
        return jsonify({'status':'success', 'task_id':task.task_id, 'message':'任务已启动'})

    @app.route('/api/offline/scan', methods=['POST'])
    @require_auth
    def offline_preparse_scan():
        def scan(config):
            raw = scan_source_folders(config)
            check_cancelled()
            save_raw_cache(raw)
            total = len(raw)
            return {'success':total, 'failed':0, 'total':total}, total, f'扫描完成，共 {total} 个文件夹'
        return start_offline('offline_scan', _scan_status, scan)

    @app.route('/api/offline/parse', methods=['POST'])
    @require_auth
    def offline_preparse_parse():
        if not request_config(config_path).get('ai_parser', {}).get('enabled'):
            return jsonify({'status':'error', 'message':'AI 解析未启用'}), 400
        def parse(config):
            result = run_ai_preparse(config)
            summary=preparse_summary(config)
            return summary, summary['total'], f"预解析结束：完整 {summary['success']}/{summary['total']}，未解析文件 {summary['files_unparsed']}"

        return start_offline('offline_parse', _parse_status, parse)
