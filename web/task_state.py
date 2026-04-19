#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局任务状态管理
供 Web 层共享当前任务的运行状态、进度和日志
支持任务停止标志和强制重置
"""

import threading
import time
from typing import Dict, Any, List
from core.logger import get_logger

task_lock = threading.RLock()

current_task: Dict[str, Any] = {
    "running": False,
    "progress": 0,
    "total": 0,
    "message": "",
    "log": []
}

_stop_requested = False


def progress_callback(current: int, total: int, message: str, level: str = "info"):
    """任务进度回调，由 core 层调用"""
    logger = get_logger(__name__)
    if level == 'error':
        logger.error(message)
    elif level == 'warning':
        logger.warning(message)
    else:
        logger.info(message)

    with task_lock:
        current_task["progress"] = current
        current_task["total"] = total
        current_task["message"] = message
        current_task["log"].append({
            "msg": message,
            "level": level,
            "time": time.time()
        })
        # 保留最近 100 条日志
        if len(current_task["log"]) > 100:
            current_task["log"] = current_task["log"][-100:]


def reset_task_state():
    """重置任务状态（任务结束时调用）"""
    with task_lock:
        current_task["running"] = False
        current_task["progress"] = 0
        current_task["total"] = 0
        current_task["message"] = ""
        # 不清空日志，保留最近一次运行的记录


def get_task_status() -> Dict[str, Any]:
    """获取当前任务状态"""
    with task_lock:
        return {
            "running": current_task["running"],
            "progress": current_task["progress"],
            "total": current_task["total"],
            "message": current_task["message"],
            "log": current_task["log"][-30:]  # 只返回最近 30 条给前端
        }


def set_task_running():
    """设置任务为运行中，并初始化状态"""
    with task_lock:
        current_task["running"] = True
        current_task["progress"] = 0
        current_task["total"] = 0
        current_task["message"] = "准备中..."
        current_task["log"] = []
        global _stop_requested
        _stop_requested = False


def is_task_running() -> bool:
    """检查是否有任务正在运行"""
    with task_lock:
        return current_task["running"]


def should_stop() -> bool:
    """检查是否请求停止任务（供任务循环使用）"""
    with task_lock:
        return _stop_requested


def request_stop():
    """请求停止任务"""
    with task_lock:
        global _stop_requested
        _stop_requested = True


def clear_stop_flag():
    """清除停止标志（任务启动时调用）"""
    with task_lock:
        global _stop_requested
        _stop_requested = False


def force_reset():
    """
    强制重置任务状态，用于清理残留状态（如异常崩溃后）
    不清除日志，但会将 running 设为 False 并清除停止标志
    """
    with task_lock:
        current_task["running"] = False
        current_task["progress"] = 0
        current_task["total"] = 0
        current_task["message"] = ""
        global _stop_requested
        _stop_requested = False
