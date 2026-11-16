#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器通用工具函数
包含文件名清理、跳过判断、回调包装、视频时长辅助等功能
优化：保护方括号数字不被误删、视频时长判断辅助
"""

import re
from pathlib import Path
from typing import Optional, Callable, Union

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"

# 特典/无关目录关键词（用于扫描时跳过整个目录）
SKIP_PATH_KEYWORDS = {
    'bonus', 'menu', 'cds', 'scans', 'sps', '特典', '映像特典', '特典cd',
    'cd', 'dvd', 'bd', 'extra', 'extras', 'omake', 'おまけ', 'music',
    'soundtrack', 'ost', 'op', 'ed', 'ncop', 'nced', 'pv', 'cm', 'sp',
    'specials', 'short', 'ova', 'oad'
}

# 特典文件夹关键词（原有）
SKIP_FOLDER_KEYWORDS = {'bonus', 'menu', 'cds', 'scans', 'sps', '特典', '映像特典'}


def sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符"""
    if name is None:
        return "Unknown"
    return re.sub(r'[\\/*?:"<>|]', '_', str(name)).strip()


def should_skip_file(file_path: Path) -> bool:
    """检查文件路径是否包含应跳过的文件夹"""
    for parent in file_path.parents:
        if parent.name.lower() in SKIP_FOLDER_KEYWORDS:
            return True
    return False


_PATH_TOKEN_SPLIT = re.compile(r'[\s\[\]\(\)\{\}._\-+&,，、【】（）]+')


SPECIAL_PATH_KEYWORDS = {'ova','oad','sp','sps','specials','特典','映像特典','omake','おまけ','bonus'}


def _scan_root(path, config):
    candidates = [Path(value).absolute() for value in config.get('source_folders', [])]
    parents = [root for root in candidates if path == root or root in path.parents]
    return max(parents,key=lambda root:len(root.parts)) if parents else path.parent


def should_skip_path(path, root=None, config=None):
    import fnmatch
    path = Path(path)
    root = Path(root) if root is not None else (_scan_root(path,config) if config is not None else None)
    relative = path
    if root is not None:
        try:
            relative = path.relative_to(root)
        except ValueError:
            pass
    parts = relative.parts
    if config is not None:
        if path.is_symlink() or any(part.startswith('.') for part in parts):
            return True
        excludes = config.get('scan_policy',{}).get('exclude_patterns',[])
        if any(fnmatch.fnmatchcase(relative.as_posix().casefold(),pattern.casefold())
               or any(fnmatch.fnmatchcase(part.casefold(),pattern.casefold()) for part in parts)
               for pattern in excludes):
            return True
    tokens = set().union(*({part.lower()} | set(_PATH_TOKEN_SPLIT.split(part.lower())) for part in parts)) if parts else set()
    excluded = tokens & SKIP_PATH_KEYWORDS
    if not excluded:
        return False
    if config is None or excluded - SPECIAL_PATH_KEYWORDS:
        return True
    if config.get('scan_policy',{}).get('include_specials',False):
        return False
    from .special_mapping import match_special_mapping
    mappings = config.get('special_mappings',[])
    # Descend: a mapping may name a file below this otherwise excluded directory.
    if path.is_dir():
        return not any(rule.get('enabled',True) and rule.get('keyword') and rule.get('tmdb_id') for rule in mappings)
    matched = match_special_mapping(path.name,mappings)
    return not bool(matched and matched.get('tmdb_id'))


def is_video_file(filepath, config):
    filepath = Path(filepath)
    if filepath.suffix.lower() not in {ext.lower() for ext in config['video_extensions']}:
        return False
    if should_skip_path(filepath, config=config):
        return False
    for pattern in config.get('ignore_patterns',[]):
        if re.search(rf'\b{re.escape(pattern.lower())}\b',filepath.stem.lower()):
            return False
    minimum = config.get('min_file_size_mb',0)
    if minimum > 0:
        try:
            if filepath.stat().st_size / (1024*1024) < minimum:
                return False
        except OSError:
            return False
    return True


def wrap_progress_callback(callback: Optional[Callable]) -> Optional[Callable]:
    """
    将原始的 progress_callback(current, total, msg, level) 包装为一个统一的 log_func
    """
    if callback is None:
        return None

    def unified_log(*args):
        if len(args) == 1:
            callback(0, 0, args[0], "info")
        elif len(args) == 2:
            callback(0, 0, args[0], args[1])
        elif len(args) == 4:
            callback(*args)
        else:
            callback(0, 0, str(args), "info")

    return unified_log


def pre_clean_filename_for_anitopy(filename: str) -> str:
    """
    深度清洗文件名，移除干扰词，提升 anitopy 解析准确率。
    增强：保护方括号内的纯数字（如 [11]）并转换为标准集号格式 " - 11"
    """
    import re

    # 临时标记，用于保护方括号数字
    temp_markers = {}
    counter = 0

    def _protect(m):
        nonlocal counter
        num = m.group(1)
        marker = f"__EPNUM_{counter}__"
        # 将纯数字方括号转换为 anitopy 能识别的集号格式
        temp_markers[marker] = f" - {num}"
        counter += 1
        return marker

    # 1. 保护方括号内的纯数字或小数（如 [11]、[24.5]）
    cleaned = re.sub(r'\[(\d+(?:\.\d+)?)\]', _protect, filename)

    # 2. 移除方括号内的纯英文/数字/符号组合（压制组标签）
    cleaned = re.sub(r'\[[A-Za-z0-9\-_&! ]+\]', ' ', cleaned)

    # 3. 移除圆括号内的纯技术标签
    cleaned = re.sub(r'\([A-Za-z0-9\-_& ]+\)', ' ', cleaned)

    # 4. 移除常见画质/编码/音频关键词
    noise_keywords = [
        '1080p', '720p', '480p', '4k', '2160p', 'uhd',
        'hevc', 'x264', 'x265', 'h264', 'h265', 'avc', 'av1',
        'aac', 'flac', 'dts', 'ac3', 'eac3', 'truehd', 'opus',
        'web-dl', 'webrip', 'bdrip', 'bluray', 'blu-ray', 'dvdrip', 'hdtv',
        'complete', 'fin', 'end', 'v0', 'v1', 'v2', 'v3',
        'multi', 'dual', 'audio', 'eng', 'jpn', 'chs', 'cht'
    ]
    for kw in noise_keywords:
        cleaned = re.sub(rf'\b{kw}\b', '', cleaned, flags=re.I)

    # 5. 移除文件扩展名
    cleaned = re.sub(r'\.(mkv|mp4|avi|ts|m2ts|mov|wmv|flv|ass|ssa|srt|vtt)$', '', cleaned, flags=re.I)

    # 6. 将 .EP029、.EP29 等格式转换为标准集号格式
    cleaned = re.sub(r'\.EP(\d{1,3})(?:\b|\.)', r' - \1', cleaned, flags=re.I)
    cleaned = re.sub(r'\.EP_?(\d{1,3})', r' - \1', cleaned, flags=re.I)

    # 7. 将下划线替换为空格
    cleaned = cleaned.replace('_', ' ')

    # 8. 恢复被保护的集号标记
    for marker, replacement in temp_markers.items():
        cleaned = cleaned.replace(marker, replacement)

    # 9. 保护常见季/集标识（避免被后续规则破坏）
    protected_patterns = [
        (r'[Ss]\d{1,2}[Ee]\d{1,2}', lambda m: m.group(0)),
        (r'第\s*\d+\s*[集話话]', lambda m: m.group(0)),
        (r'\d{1,2}[xX]\d{1,2}', lambda m: m.group(0)),
        (r'#\d{1,4}', lambda m: m.group(0)),
        (r' - \d{1,3}', lambda m: m.group(0)),  # 保护我们生成的 " - 11"
    ]
    for pattern, repl in protected_patterns:
        cleaned = re.sub(pattern, repl, cleaned)

    # 10. 清理特殊字符，保留中文、英文、数字、空格、短横线
    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff-]', ' ', cleaned, flags=re.I)

    # 11. 合并多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if len(cleaned) < 3:
        return filename
    return cleaned


def is_long_video_duration(duration_minutes: Optional[float], threshold: float = 50.0) -> bool:
    """
    判断视频时长是否超过阈值（默认50分钟）。
    用于辅助识别剧场版/电影 vs 普通剧集。
    """
    if duration_minutes is None:
        return False
    return duration_minutes > threshold


def adjust_media_type_by_duration(
    current_media_type: str,
    duration_minutes: Optional[float],
    log_func: Optional[Callable] = None
) -> tuple:
    """
    根据视频时长调整媒体类型，返回 (新类型, 置信度调整值, 提示信息)
    - 剧集时长 > 50分钟：极可能是剧场版/电影，建议改为 movie
    - 电影时长 < 40分钟：可能是剧集/OVA，建议改为 tv
    """
    if duration_minutes is None:
        return current_media_type, 0, None

    if current_media_type == "tv" and duration_minutes > 50:
        hint = f"⚠️ 识别为剧集但时长达 {duration_minutes:.1f} 分钟，极可能是剧场版/电影"
        if log_func:
            log_func(hint, LOG_WARNING)
        return "movie", -20, hint

    if current_media_type == "movie" and duration_minutes < 40:
        hint = f"⚠️ 识别为电影但时长仅 {duration_minutes:.1f} 分钟，可能是剧集/OVA"
        if log_func:
            log_func(hint, LOG_WARNING)
        return "tv", -15, hint

    return current_media_type, 0, None
