#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志配置（含自动轮转清理）
使用 RotatingFileHandler 实现日志文件自动轮转，防止无限增长。
单文件最大 10MB，保留 1 个备份，总占用空间 ≤ 20MB。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = Path("auto_processor_errors.log")

# 单例模式确保只配置一次
_logger_configured = False


def setup_logging():
    """配置全局日志，使用 RotatingFileHandler 自动清理旧日志"""
    global _logger_configured
    if _logger_configured:
        return

    # 创建 logger
    logger = logging.getLogger('emby_auto')
    logger.setLevel(logging.INFO)

    # 自动轮转文件处理器：单文件最大 10MB，保留 1 个备份
    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=1,              # 保留一个备份文件 .log.1
        encoding='utf-8'
    )
    file_handler.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # 控制台处理器（可选，便于调试）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _logger_configured = True


def get_logger(name=None):
    """获取已配置的 logger"""
    setup_logging()
    return logging.getLogger('emby_auto')
