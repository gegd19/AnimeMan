#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析器通用辅助函数"""

import re
import hashlib
from pathlib import Path
from typing import Dict, Optional

def extract_first_number(text: Optional[str]) -> Optional[int]:
    """提取文本中的第一个连续数字"""
    if text is None:
        return None
    match = re.search(r'\d+', str(text))
    return int(match.group()) if match else None

def clean_parent_dir_name(parent_dir: str) -> str:
    """清理父目录名，移除年份、画质等干扰信息"""
    if not parent_dir:
        return ""
    name = re.sub(r'[\[\(]?(19|20)\d{2}[\]\)]?', '', parent_dir)
    name = re.sub(r'\b(1080p|720p|4K|HDR|HEVC|x264|x265|AAC|WEB-DL|BluRay|BDRip)\b', '', name, flags=re.I)
    name = re.sub(r'[\[\(【].*?[\]\)】]', '', name)
    name = re.sub(r'[_,\.-]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def get_ai_config_fingerprint(ai_cfg: Dict) -> str:
    """生成 AI 配置指纹，用于缓存键"""
    fields = ["provider", "model", "temperature", "max_tokens", "base_url"]
    vals = [str(ai_cfg.get(f, "")) for f in fields]
    return hashlib.md5("|".join(vals).encode()).hexdigest()[:8]

def get_ai_parse_cache_key(file_path_str: str, config: Dict) -> str:
    """生成 AI 解析缓存键"""
    from .parser_helpers import get_ai_config_fingerprint
    ai_cfg = config.get("ai_parser", {})
    cfg_fp = get_ai_config_fingerprint(ai_cfg)
    path_hash = hashlib.md5(file_path_str.encode()).hexdigest()[:12]
    return f"{path_hash}|{cfg_fp}"
def get_video_files_in_folder(folder: Path, video_extensions: list, max_depth: int = 2) -> list:
    """
    获取文件夹内所有视频文件，支持递归子目录（默认深度2，覆盖 Season 1/ 等常见结构）
    """
    video_exts = {ext.lower() for ext in video_extensions}
    files = []

    def _scan(current: Path, depth: int):
        if depth > max_depth:
            return
        try:
            for item in current.iterdir():
                if item.is_file() and item.suffix.lower() in video_exts:
                    files.append(item)
                elif item.is_dir() and depth < max_depth and not item.name.startswith('.'):
                    # 跳过特典/花絮目录
                    if any(skip in item.name.lower() for skip in ['bonus', 'menu', 'cds', 'scans', 'sps', '特典']):
                        continue
                    _scan(item, depth + 1)
        except PermissionError:
            pass

    _scan(folder, 1)
    return files
def pre_clean_filename_for_anitopy(filename: str) -> str:
    """
    对文件名进行深度清洗，移除干扰词，提升 anitopy 解析准确率。
    保守清洗，仅移除高置信度的无关信息，并保护季/集标识。
    """
    import re

    # 1. 移除方括号内的纯英文/数字压制组标签（如 [VCB-Studio], [UHA-WINGS], [ReinForce]）
    cleaned = re.sub(r'\[[A-Za-z0-9\-_&! ]+\]', ' ', filename)

    # 2. 移除圆括号内的纯技术标签（如 (BDrip), (WebRip), (1080p)）
    cleaned = re.sub(r'\([A-Za-z0-9\-_& ]+\)', ' ', cleaned)

    # 3. 移除常见画质/编码/音频关键词（独立单词，避免误伤标题中的正常词汇）
    noise_keywords = [
        '1080p', '720p', '480p', '4k', '2160p', 'uhd',
        'hevc', 'x264', 'x265', 'h264', 'h265', 'avc', 'av1',
        'aac', 'flac', 'dts', 'ac3', 'eac3', 'truehd', 'opus',
        'web-dl', 'webrip', 'bdrip', 'bluray', 'blu-ray', 'dvdrip', 'hdtv',
        'complete', 'fin', 'end', 'v0', 'v1', 'v2', 'v3',
        'multi', 'dual', 'audio', 'eng', 'jpn', 'chs', 'cht'
    ]
    for kw in noise_keywords:
        # 使用单词边界，防止误伤标题中包含的子串（如 "1080" 可能出现在标题中）
        cleaned = re.sub(rf'\b{kw}\b', '', cleaned, flags=re.I)

    # 4. 移除文件扩展名（如果误传入）
    cleaned = re.sub(r'\.(mkv|mp4|avi|ts|m2ts|mov|wmv|flv|ass|ssa|srt|vtt)$', '', cleaned, flags=re.I)

    # 5. 保留常见的季/集标识，将其他分隔符替换为空格
    # 保护 S01E01、第01集 等模式不被破坏
    protected_patterns = [
        (r'[Ss]\d{1,2}[Ee]\d{1,2}', lambda m: m.group(0)),           # S01E01
        (r'第\s*\d+\s*[集話话]', lambda m: m.group(0)),               # 第01集
        (r'\d{1,2}[xX]\d{1,2}', lambda m: m.group(0)),               # 01x01
        (r'#\d{1,4}', lambda m: m.group(0)),                         # #01
    ]
    for pattern, repl in protected_patterns:
        cleaned = re.sub(pattern, repl, cleaned)

    # 6. 移除多余的特殊字符，但保留中文、英文、数字、空格、短横线
    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff-]', ' ', cleaned, flags=re.I)

    # 7. 将多个连续空格合并为一个
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # 若清洗后为空或过短（可能误删了标题），返回原始文件名
    if len(cleaned) < 3:
        return filename

    return cleaned
