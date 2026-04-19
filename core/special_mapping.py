#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
特辑/OVA 手动映射规则管理模块
"""

from typing import List, Dict, Any, Optional


def match_special_mapping(filename: str, mappings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    检查文件名是否命中某条映射规则

    Args:
        filename: 文件名（含扩展名或全路径均可）
        mappings: 映射规则列表，每条规则包含 keyword, tmdb_id, media_type, season, episode, enabled

    Returns:
        命中则返回规则字典（补充 media_type 等），否则返回 None
    """
    filename_lower = filename.lower()
    for rule in mappings:
        if not rule.get("enabled", True):
            continue
        keyword = rule.get("keyword", "").lower()
        if keyword and keyword in filename_lower:
            return {
                "media_type": rule.get("media_type", "tv"),
                "tmdb_id": rule.get("tmdb_id"),
                "season": rule.get("season"),
                "episode": rule.get("episode"),
                "title_override": rule.get("title_override"),
                "matched_keyword": rule.get("keyword"),
                "_from_mapping": True
            }
    return None


def validate_mapping_rule(rule: Dict[str, Any]) -> tuple:
    """
    验证映射规则的有效性

    Returns:
        (是否有效, 错误信息)
    """
    keyword = rule.get("keyword", "").strip()
    if not keyword:
        return False, "关键词不能为空"

    tmdb_id = rule.get("tmdb_id")
    if not tmdb_id or not str(tmdb_id).isdigit():
        return False, "TMDB ID 必须为正整数"

    media_type = rule.get("media_type")
    if media_type not in ("movie", "tv"):
        return False, "媒体类型必须为 movie 或 tv"

    if media_type == "tv":
        season = rule.get("season")
        if season is None or not str(season).lstrip('-').isdigit():
            return False, "剧集必须指定有效的季号"
        episode = rule.get("episode")
        if episode is None or not str(episode).lstrip('-').isdigit():
            return False, "剧集必须指定有效的集号"

    return True, ""


def normalize_mapping_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """标准化规则字段类型"""
    normalized = {
        "keyword": rule.get("keyword", "").strip(),
        "tmdb_id": int(rule.get("tmdb_id", 0)),
        "media_type": rule.get("media_type", "tv"),
        "enabled": rule.get("enabled", True)
    }
    if normalized["media_type"] == "tv":
        normalized["season"] = int(rule.get("season", 0))
        normalized["episode"] = int(rule.get("episode", 1))
    else:
        normalized["season"] = None
        normalized["episode"] = None

    if rule.get("title_override"):
        normalized["title_override"] = rule["title_override"].strip()
    if rule.get("description"):
        normalized["description"] = rule["description"].strip()

    return normalized
