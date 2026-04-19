 
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频信息提取模块
"""

import subprocess
import json
from pathlib import Path
from typing import Optional


def get_video_duration_ffprobe(video_path: Path) -> Optional[float]:
    """
    使用 ffprobe 获取视频时长（单位：分钟）
    返回 None 表示获取失败
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        duration_sec = float(data['format'].get('duration', 0))
        return duration_sec / 60.0  # 转换为分钟
    except Exception:
        return None


def get_video_duration(video_path: Path) -> Optional[float]:
    """获取视频时长（分钟），失败返回 None"""
    return get_video_duration_ffprobe(video_path)
