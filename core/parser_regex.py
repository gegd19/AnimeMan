#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正则表达式文件名解析器（回退方案）"""

import re
from pathlib import Path
from typing import Dict, Any
from .parser_helpers import clean_parent_dir_name


def parse_with_regex(filename: str, parent_dir: str = "") -> Dict[str, Any]:
    """使用正则表达式解析文件名，支持日文/中文集号，并提取显式季数和总集数"""
    name = Path(filename).stem
    name = re.sub(r'\.\.\w+$', '', name)
    name = re.sub(r'^\[[^\]]+\]\s*', '', name)

    year_match = re.search(r'\b(19|20)\d{2}\b', name)
    year = year_match.group(0) if year_match else None

    # 显式季数提取
    explicit_season = 1
    season_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    combined = f"{name} {parent_dir}"
    m = re.search(r'第\s*([一二三四五六七八九十\d]+)\s*季', combined)
    if m:
        num_str = m.group(1)
        explicit_season = int(num_str) if num_str.isdigit() else season_map.get(num_str, 1)
    m = re.search(r'[Ss]eason\s*(\d{1,2})', combined, re.I)
    if m:
        explicit_season = int(m.group(1))
    m = re.search(r'[Ss](\d{1,2})(?![Ee])', combined)
    if m:
        explicit_season = int(m.group(1))

    # 集数匹配
    tv_patterns = [
        r'[Ss](\d{1,2})[Ee](\d{1,2})',
        r'(\d{1,2})[xX](\d{1,2})',
        r'第\s*(\d{1,2})\s*季\s*第\s*(\d{1,2})\s*集',
        r'第\s*(\d{1,3})\s*[話话]',
        r'\[(\d{1,2})\]'
    ]
    season, episode = None, None
    for p in tv_patterns:
        m = re.search(p, name, re.I)
        if m:
            if p in [r'[Ss](\d{1,2})[Ee](\d{1,2})', r'(\d{1,2})[xX](\d{1,2})', r'第\s*(\d{1,2})\s*季\s*第\s*(\d{1,2})\s*集']:
                season = int(m.group(1))
                episode = int(m.group(2))
            elif p == r'第\s*(\d{1,3})\s*[話话]':
                season = explicit_season
                episode = int(m.group(1))
            else:
                season = explicit_season
                episode = int(m.group(1))
            break

    media_type = "tv" if episode is not None else "movie"

    # 标题清洗
    name = re.sub(r'[\[\]\(\)【】_,\.-]', ' ', name)
    name = re.sub(r'\b(1080p|720p|4K|HDR|HEVC|x264|x265|AAC|WEB-DL|BluRay|BDRip)\b', '', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip()
    title = name if name else Path(filename).stem.split('.')[0]

    # 标题无效时使用父目录名
    if len(title) < 2 or title.isdigit() or title == "Unknown":
        clean_parent = clean_parent_dir_name(parent_dir)
        if clean_parent:
            title = clean_parent

    if not title:
        title = "Unknown"

    # 特辑处理
    name_lower = name.lower()
    special_keywords = ['ova', 'oad', 'sp', '特典', '特别篇', '番外', '剧场版']
    if any(kw in name_lower for kw in special_keywords) and media_type == "tv":
        season = 0
        sp_match = re.search(r'(?:ova|oad|sp|特典|特别篇|番外|剧场版)\s*(\d{1,2})', name, re.I)
        episode = int(sp_match.group(1)) if sp_match else 1

    if media_type == "tv" and episode is None:
        tail_num = re.search(r'\s+(\d{1,3})$', title)
        if tail_num:
            episode = int(tail_num.group(1))
            title = re.sub(r'\s+\d{1,3}$', '', title).strip()

    # 总集数检测
    total_episode = None
    if explicit_season > 1 and episode is not None:
        m = re.search(r'第\s*(\d{1,4})\s*集', filename)
        if m:
            total_episode = int(m.group(1))
        else:
            m = re.search(r'#(\d{1,4})|(\d{1,4})\s*話', filename)
            if m:
                total_episode = int(m.group(1) or m.group(2))
        if total_episode is not None:
            episode = 1

    return {
        "media_type": media_type,
        "title": title,
        "search_title": title,
        "year": year,
        "season": season if season else 1,
        "episode": episode if episode else 1,
        "episode_title": "",
        "alternative_titles": [],
        "year_guess": None,
        "corrected_season": None,
        "corrected_episode": None,
        "_parser": "regex",
        "explicit_season": explicit_season,
        "total_episode": total_episode
    }
