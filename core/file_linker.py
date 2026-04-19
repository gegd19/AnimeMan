#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件链接模块
跨平台创建硬链接或符号链接，处理各种异常降级，Windows 权限不足时给出友好提示
"""

import os
import platform
from pathlib import Path
from typing import Optional, Callable

# 日志级别常量（避免循环导入）
LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_ERROR = "error"
LOG_WARNING = "warning"


def get_long_path(path: Path) -> str:
    """Windows 下返回长路径格式"""
    if platform.system() == "Windows":
        abs_path = str(path.resolve())
        if not abs_path.startswith("\\\\?\\"):
            return "\\\\?\\" + abs_path
        return abs_path
    return str(path)


def create_link(
    src: Path,
    dst: Path,
    link_type: str,
    log_func: Optional[Callable] = None
) -> bool:
    """
    创建链接（硬链接或符号链接），失败时自动尝试降级。
    Windows 下因权限不足导致符号链接失败时，提示用户开启开发者模式。
    """
    if dst.exists():
        try:
            if os.path.samefile(str(src), str(dst)):
                if log_func:
                    log_func(0, 0, f"🔗 链接已存在: {dst.name}", LOG_INFO)
                return True
        except Exception:
            pass

        if log_func:
            log_func(0, 0, f"⚠️ 目标文件已存在且非链接: {dst}", LOG_WARNING)
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        if link_type == "symlink":
            os.symlink(src, dst)
        else:
            os.link(get_long_path(src), get_long_path(dst))
        if log_func:
            log_func(0, 0, f"✅ 链接创建成功 ({link_type})", LOG_SUCCESS)
        return True

    except OSError as e:
        is_cross_device = False
        if platform.system() == "Windows":
            if hasattr(e, 'winerror'):
                # ERROR_NOT_SAME_DEVICE (17) - 跨设备
                if e.winerror == 17:
                    is_cross_device = True
                # ERROR_PRIVILEGE_NOT_HELD (1314) - 权限不足（通常为未开启开发者模式）
                elif e.winerror == 1314:
                    if log_func:
                        log_func(0, 0, f"❌ 创建符号链接需要管理员权限或开启 Windows 开发者模式", LOG_ERROR)
                    return False
        else:
            if hasattr(e, 'errno') and e.errno == 18:
                is_cross_device = True

        # 跨设备无法硬链接，尝试软链接
        if is_cross_device or (link_type == "hard" and "cross-device" in str(e).lower()):
            if log_func:
                log_func(0, 0, f"⚠️ 跨设备无法硬链接，尝试软链接...", LOG_WARNING)
            try:
                os.symlink(src, dst)
                if log_func:
                    log_func(0, 0, f"✅ 软链接创建成功", LOG_SUCCESS)
                return True
            except OSError as e2:
                if platform.system() == "Windows" and hasattr(e2, 'winerror') and e2.winerror == 1314:
                    if log_func:
                        log_func(0, 0, f"❌ 创建符号链接需要管理员权限或开启 Windows 开发者模式", LOG_ERROR)
                else:
                    if log_func:
                        log_func(0, 0, f"❌ 软链接也失败: {e2}", LOG_ERROR)
                return False
        else:
            if log_func:
                log_func(0, 0, f"❌ 链接创建失败: {e}", LOG_ERROR)
            return False
