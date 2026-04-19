#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anitopy 动漫文件名解析器（增强版）
优化：
- 纯数字文件名时直接从父目录提取标题和季号
- 罗马数字转阿拉伯数字（支持1-30季）
- 当文件名信息不足时，用目录信息补充标题和季号
- 罗马数字季号（如 III）自动转换为 Sxx 格式便于 anitopy 识别
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from .parser_helpers import extract_first_number, clean_parent_dir_name

try:
    import anitopy
    ANITOPY_AVAILABLE = True
except ImportError:
    ANITOPY_AVAILABLE = False

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"


def _build_roman_map(max_season: int = 30) -> Dict[str, str]:
    """构建罗马数字到阿拉伯数字的映射表（不区分大小写）"""
    roman_map = {
        1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX', 10: 'X',
        11: 'XI', 12: 'XII', 13: 'XIII', 14: 'XIV', 15: 'XV', 16: 'XVI', 17: 'XVII', 18: 'XVIII',
        19: 'XIX', 20: 'XX', 21: 'XXI', 22: 'XXII', 23: 'XXIII', 24: 'XXIV', 25: 'XXV',
        26: 'XXVI', 27: 'XXVII', 28: 'XXVIII', 29: 'XXIX', 30: 'XXX'
    }
    replacement_map = {}
    for num in range(1, max_season + 1):
        roman = roman_map[num]
        replacement_map[roman] = str(num)
        replacement_map[roman.lower()] = str(num)
    return replacement_map


ROMAN_TO_ARABIC = _build_roman_map(30)


def parse_with_anitopy(
    filename: str,
    parent_dir: str = "",
    log_func: Optional[Callable] = None
) -> Dict[str, Any]:
    """使用 anitopy 解析文件名，并提取显式季数和总集数"""
    if not ANITOPY_AVAILABLE:
        return {"media_type": "unknown", "_anitopy_available": False}

    # ========== 特殊处理：纯数字文件名 ==========
    stem = Path(filename).stem
    pure_number_match = re.match(r'^\d+$', stem)
    if pure_number_match:
        episode = int(stem)
        title = clean_parent_dir_name(parent_dir)
        if not title:
            title = parent_dir or "Unknown"

        season = 1
        season_match = re.search(r'[Ss](\d{1,2})', parent_dir)
        if season_match:
            season = int(season_match.group(1))
        else:
            cn_match = re.search(r'第\s*([一二三四五六七八九十\d]+)\s*季', parent_dir)
            if cn_match:
                num_str = cn_match.group(1)
                if num_str.isdigit():
                    season = int(num_str)
                else:
                    season_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
                    season = season_map.get(num_str, 1)

        if log_func:
            log_func(f"📁 纯数字文件名，从父目录提取: 标题={title}, S{season:02d}E{episode:02d}", LOG_INFO)

        return {
            "media_type": "tv",
            "_anitopy_success": True,
            "_cleaned_filename": filename,
            "_parent_dir": parent_dir,
            "title": title,
            "search_title": title,
            "year": None,
            "season": season,
            "episode": episode,
            "episode_title": "",
            "alternative_titles": [],
            "year_guess": None,
            "corrected_season": None,
            "corrected_episode": None,
            "release_group": "",
            "_parser": "anitopy",
            "explicit_season": season,
            "total_episode": None
        }

    # ========== 预处理：罗马数字季号转换为 Sxx 格式 ==========
    processed_filename = filename

    # 匹配标题末尾的罗马数字季号（如 "Title III [21]" 中的 III）
    # 确保罗马数字后面紧跟着集号标识或空格/括号
    roman_season_pattern = re.compile(
        r'\b(?P<base>.*?)\s+(?P<roman>I{1,3}|IV|V|VI{0,3}|IX|X{1,3}|XI{0,3})\b(?=\s*[\[\(]?\d+[\]\)]?)',
        re.IGNORECASE
    )
    match = roman_season_pattern.search(processed_filename)
    if match:
        roman = match.group('roman').upper()
        arabic = ROMAN_TO_ARABIC.get(roman) or ROMAN_TO_ARABIC.get(roman.lower())
        if arabic:
            base_title = match.group('base')
            # 用 Sxx 格式替换原罗马数字
            processed_filename = processed_filename.replace(
                match.group(0),
                f"{base_title} S{int(arabic):02d}"
            )
            if log_func:
                log_func(f"🔤 检测到罗马数字季号: {roman} → S{int(arabic):02d}", LOG_INFO)

    # ========== 其他罗马数字转阿拉伯数字（如文件名其他部分的 II、V 等） ==========
    for roman, arabic in ROMAN_TO_ARABIC.items():
        processed_filename = re.sub(
            rf'(?<![a-zA-Z0-9]){re.escape(roman)}(?![a-zA-Z0-9])',
            arabic,
            processed_filename,
            flags=re.I
        )

    cleaned_filename = processed_filename
    if log_func and cleaned_filename != filename:
        log_func(f"🔤 文件名预处理后: {cleaned_filename}", LOG_INFO)

    result = {
        "media_type": "unknown",
        "_anitopy_success": False,
        "_cleaned_filename": cleaned_filename,
        "_parent_dir": parent_dir
    }

    try:
        parsed = anitopy.parse(cleaned_filename)
    except Exception as e:
        if log_func:
            log_func(f"⚠️ anitopy 解析异常: {e}", "warning")
        return result

    title = parsed.get('anime_title')

    # 如果标题为空或不理想，用目录信息补充
    if not title or title == "Unknown" or re.match(r'^[\d\s\.]+$', title):
        dir_title = clean_parent_dir_name(parent_dir)
        if dir_title:
            title = dir_title
            if log_func:
                log_func(f"📁 文件名无标题，从父目录提取: {title}", LOG_INFO)
    elif not title and parent_dir:
        title = clean_parent_dir_name(parent_dir)
        if log_func and title:
            log_func(f"📁 从父目录提取标题: {title}", LOG_INFO)

    season = extract_first_number(parsed.get('anime_season')) or 1
    episode = extract_first_number(parsed.get('episode_number'))
    year = parsed.get('anime_year')
    release_group = parsed.get('release_group', '')
    episode_title = parsed.get('episode_title', '')

    # 如果解析出的季号为1但目录名明确指示更高季号，覆盖
    if season == 1:
        season_match = re.search(r'[Ss](\d{1,2})|Season\s*(\d{1,2})|第\s*(\d{1,2})\s*季', parent_dir, re.I)
        if season_match:
            detected_season = int(season_match.group(1) or season_match.group(2) or season_match.group(3))
            if detected_season > 1:
                season = detected_season
                if log_func:
                    log_func(f"📁 从父目录覆盖季号: S{season:02d}", LOG_INFO)

    if title and episode is not None:
        result["media_type"] = "tv"
        result["_anitopy_success"] = True
    elif title:
        result["media_type"] = "movie"
        result["_anitopy_success"] = True

    # 显式季数提取
    explicit_season = season
    season_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    combined = f"{filename} {parent_dir}"
    m = re.search(r'第\s*([一二三四五六七八九十\d]+)\s*季', combined)
    if m:
        num_str = m.group(1)
        explicit_season = int(num_str) if num_str.isdigit() else season_map.get(num_str, season)
    m = re.search(r'[Ss]eason\s*(\d{1,2})', combined, re.I)
    if m:
        explicit_season = int(m.group(1))
    m = re.search(r'[Ss](\d{1,2})(?![Ee])', combined)
    if m:
        explicit_season = int(m.group(1))

    # 总集数检测
    total_episode = None
    if explicit_season > 1:
        m = re.search(r'第\s*(\d{1,4})\s*集', combined)
        if m:
            total_episode = int(m.group(1))
        else:
            m = re.search(r'#(\d{1,4})|(\d{1,4})\s*話', combined)
            if m:
                total_episode = int(m.group(1) or m.group(2))
        if total_episode is not None:
            episode = 1
            if log_func:
                log_func(f"🔍 检测到总集数模式: 第{total_episode}集 (显式季数={explicit_season})", LOG_INFO)

    result.update({
        "title": title or "",
        "search_title": title or "",
        "year": year,
        "season": season,
        "episode": episode or 1,
        "episode_title": episode_title,
        "alternative_titles": [],
        "year_guess": year,
        "corrected_season": None,
        "corrected_episode": None,
        "release_group": release_group,
        "_parser": "anitopy",
        "explicit_season": explicit_season,
        "total_episode": total_episode
    })

    if log_func and result["_anitopy_success"]:
        season_str = f"{season:02d}" if season is not None else "??"
        episode_str = f"{episode:02d}" if episode is not None else "??"
        log_func(f"🎌 anitopy 解析: {title} S{season_str}E{episode_str}", "success")
    elif log_func:
        log_func(f"⚠️ anitopy 部分解析: title={title}, ep={episode}", "warning")

    return result
