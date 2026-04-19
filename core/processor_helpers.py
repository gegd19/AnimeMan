#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器通用辅助函数（合并版）
包含文件名清理、跳过判断、解析辅助、标题提取、季号标识构建等
"""

import re
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

from .special_mapping import match_special_mapping
from . import parser_manager
from .logger import get_logger

logger = get_logger(__name__)

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"

# ========== 原有的通用工具函数 ==========

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
    保护方括号内的纯数字并转换为标准集号格式。
    """
    temp_markers = {}
    counter = 0

    def _protect(m):
        nonlocal counter
        num = m.group(1)
        marker = f"__EPNUM_{counter}__"
        temp_markers[marker] = f" - {num}"
        counter += 1
        return marker

    cleaned = re.sub(r'\[(\d+(?:\.\d+)?)\]', _protect, filename)

    # 移除方括号内的纯英文/数字压制组标签
    cleaned = re.sub(r'\[[A-Za-z0-9\-_&! ]+\]', ' ', cleaned)
    # 移除圆括号内的纯技术标签
    cleaned = re.sub(r'\([A-Za-z0-9\-_& ]+\)', ' ', cleaned)

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

    cleaned = re.sub(r'\.(mkv|mp4|avi|ts|m2ts|mov|wmv|flv|ass|ssa|srt|vtt)$', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\.EP(\d{1,3})(?:\b|\.)', r' - \1', cleaned, flags=re.I)
    cleaned = re.sub(r'\.EP_?(\d{1,3})', r' - \1', cleaned, flags=re.I)
    cleaned = cleaned.replace('_', ' ')

    for marker, replacement in temp_markers.items():
        cleaned = cleaned.replace(marker, replacement)

    protected_patterns = [
        (r'[Ss]\d{1,2}[Ee]\d{1,2}', lambda m: m.group(0)),
        (r'第\s*\d+\s*[集話话]', lambda m: m.group(0)),
        (r'\d{1,2}[xX]\d{1,2}', lambda m: m.group(0)),
        (r'#\d{1,4}', lambda m: m.group(0)),
        (r' - \d{1,3}', lambda m: m.group(0)),
    ]
    for pattern, repl in protected_patterns:
        cleaned = re.sub(pattern, repl, cleaned)

    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff-]', ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned if len(cleaned) >= 3 else filename


# ========== 拆分后新增的辅助函数 ==========

def apply_special_mapping(src: Path, config: dict, log_func) -> Tuple[Optional[int], Optional[str], Optional[int], Optional[int]]:
    special_mappings = config.get("special_mappings", [])
    if not special_mappings:
        return None, None, None, None
    matched = match_special_mapping(src.name, special_mappings)
    if matched:
        if log_func:
            log_func(f"🔖 命中手动映射规则: {matched['matched_keyword']} → TMDB ID {matched['tmdb_id']}", LOG_SUCCESS)
        return matched["tmdb_id"], matched["media_type"], matched.get("season"), matched.get("episode")
    return None, None, None, None


def parse_filename_info(src: Path, config: dict, log_func,
                        force_tmdb_id=None, force_media_type=None,
                        force_season=None, force_episode=None) -> Dict[str, Any]:
    try:
        info = parser_manager.parse_filename(src, config, log_func)
    except Exception as e:
        logger.error(f"文件名解析失败 {src}: {e}", exc_info=True)
        info = {"media_type": "unknown"}
    if force_tmdb_id:
        info["tmdb_id"] = force_tmdb_id
        info["media_type"] = force_media_type
        if force_media_type == "tv":
            info["season"] = force_season
            info["episode"] = force_episode
    return info


def compute_confidence(info: Dict[str, Any], has_force_tmdb: bool) -> int:
    if has_force_tmdb:
        return 100
    if info.get("_parser") == "anitopy":
        return 75
    if info.get("_from_ai") or info.get("_from_folder_cache"):
        return 80
    return 70


def prepare_search_query(info: Dict[str, Any], tech_noise_words: set) -> Tuple[str, str, Optional[str], List[str]]:
    title = info.get("title") or ""
    search_title = info.get("search_title") or title
    for word in tech_noise_words:
        search_title = re.sub(rf'\b{word}\b', '', search_title, flags=re.I)
    search_title = re.sub(r'[：:\s]+[^：:]*[篇章部季卷]$', '', search_title).strip()
    if not search_title or len(search_title) < 2:
        search_title = title
    year = info.get("year")
    year_guess = info.get("year_guess")
    search_year = year if year and year != "null" else (year_guess if year_guess else None)
    alt_titles = info.get("alternative_titles", [])
    return title, search_title, search_year, alt_titles


def extract_all_alternative_titles(details: Dict[str, Any], official_title: str) -> List[str]:
    titles = set()
    if official_title:
        titles.add(official_title.strip())
    original_title = details.get("original_title") or details.get("original_name")
    if original_title:
        titles.add(original_title.strip())
    alt_titles = details.get("alternative_titles", {})
    if isinstance(alt_titles, dict):
        results = alt_titles.get("titles", [])
    else:
        results = alt_titles.get("titles", [])
    for item in results:
        t = item.get("title") or item.get("name")
        if t:
            titles.add(t.strip())
    return [t for t in titles if t]


def build_season_indicators(max_season: int = 30) -> List[str]:
    indicators = []
    roman_map = {
        1: 'i', 2: 'ii', 3: 'iii', 4: 'iv', 5: 'v', 6: 'vi', 7: 'vii', 8: 'viii', 9: 'ix', 10: 'x',
        11: 'xi', 12: 'xii', 13: 'xiii', 14: 'xiv', 15: 'xv', 16: 'xvi', 17: 'xvii', 18: 'xviii',
        19: 'xix', 20: 'xx', 21: 'xxi', 22: 'xxii', 23: 'xxiii', 24: 'xxiv', 25: 'xxv',
        26: 'xxvi', 27: 'xxvii', 28: 'xxviii', 29: 'xxix', 30: 'xxx'
    }
    for num in range(2, max_season + 1):
        roman = roman_map[num]
        indicators.append(f' {roman} ')
        indicators.append(f'{roman} ')
        indicators.append(f' {roman}')
    chinese_num = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
                   '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
                   '二十一', '二十二', '二十三', '二十四', '二十五', '二十六', '二十七', '二十八', '二十九', '三十']
    for i in range(2, max_season + 1):
        indicators.append(f'第{chinese_num[i]}季')
    for i in range(2, max_season + 1):
        if i == 2:
            indicators.append('2nd season')
        elif i == 3:
            indicators.append('3rd season')
        else:
            indicators.append(f'{i}th season')
        indicators.append(f'season {i}')
    return indicators
