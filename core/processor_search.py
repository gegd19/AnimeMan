#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMDB搜索与AI辅助选择
优化：
- 本地别名映射库优先
- AI选择时仅发送标题和年份，减少token
- 纯数字文件名时提高AI缓存写入阈值
- 代理支持：所有TMDB请求均传递proxy参数
"""

import re
import json
import threading
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable

from . import tmdb_client, ai_client
from .constants import *
from .logger import get_logger

logger = get_logger(__name__)

_ai_selection_cache: Dict[Tuple[str, str, str], int] = {}
_ai_selection_cache_lock = threading.RLock()

# 本地别名映射文件
ALIAS_FILE = Path("tmdb_aliases.json")
_alias_cache: Dict[str, Dict] = {}


def _load_aliases() -> Dict[str, Dict]:
    global _alias_cache
    if _alias_cache:
        return _alias_cache
    if ALIAS_FILE.exists():
        try:
            with open(ALIAS_FILE, 'r', encoding='utf-8') as f:
                _alias_cache = json.load(f)
                _alias_cache = {k.lower(): v for k, v in _alias_cache.items()}
        except Exception:
            _alias_cache = {}
    return _alias_cache


def _lookup_local_alias(query: str) -> Optional[Dict]:
    aliases = _load_aliases()
    return aliases.get(query.lower().strip())


def original_search_tmdb(
    media_type: str,
    search_title: str,
    search_year: Optional[str],
    alt_titles: List[str],
    config: dict,
    log_func: Optional[Callable] = None,
    duration_hint: Optional[str] = None
) -> Tuple[Optional[Dict], str, int]:
    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")

    primary_type = media_type
    secondary_type = "movie" if media_type == "tv" else "tv"
    if duration_hint and duration_hint != media_type:
        primary_type, secondary_type = secondary_type, primary_type

    attempts = [(primary_type, search_title, search_year)]
    for alt in alt_titles:
        attempts.append((primary_type, alt, search_year))

    for mtype, query, year in attempts:
        try:
            result = tmdb_client.search_tmdb(mtype, query, year, api_key, language, log_func, alt_titles, proxy=proxy)
            if result:
                return result, mtype, 0
        except Exception:
            continue

    for mtype, query, year in attempts:
        try:
            result = tmdb_client.search_tmdb(secondary_type, query, year, api_key, language, log_func, alt_titles, proxy=proxy)
            if result:
                return result, secondary_type, 0
        except Exception:
            continue

    return None, media_type, 0


def ai_verify_and_correct_title(
    src: Path,
    original_title: str,
    candidates: List[Dict],
    config: dict,
    log_func: Optional[Callable] = None
) -> Optional[str]:
    ai_cfg = config.get("ai_parser", {})
    if not ai_cfg.get("enabled"):
        return None

    if log_func:
        log_func(f"🤖 检测到候选结果过多且匹配度低，AI 正在验证标题可信度...", LOG_INFO)

    top_titles = []
    for item in candidates[:5]:
        title = item.get("title") or item.get("name")
        year = (item.get("release_date") if item.get("media_type") == "movie" else item.get("first_air_date") or "")[:4]
        top_titles.append(f"- {title} ({year})")

    titles_text = "\n".join(top_titles)

    prompt = f"""你是影视文件识别专家。请分析以下信息并判断自动解析的剧名是否可信。

原始文件信息：
- 文件路径：{src}
- 文件名：{src.name}
- 所在目录：{src.parent.name}
- 祖父目录：{src.parent.parent.name if src.parent.parent != src.parent else ''}

自动解析结果：
- 剧名：{original_title}

TMDB 搜索返回的部分候选结果（前5个）：
{titles_text}

请回答：
1. 自动解析的剧名 "{original_title}" 是否可能是正确的？（回答"可信"或"不可信"）
2. 如果不可信，根据文件路径和目录名，你认为正确的剧名应该是什么？（直接给出剧名，不要额外解释）

请严格按以下格式返回（仅一行）：
可信 | 正确剧名
或
不可信 | 正确剧名

例如：
可信 | 鬼灭之刃
不可信 | 数码宝贝大冒险"""

    try:
        resp = ai_client.call_ai_api(prompt, ai_cfg, log_func)
        if resp:
            parts = resp.strip().split('|')
            if len(parts) >= 2:
                is_trusted = parts[0].strip().lower() == '可信'
                corrected_title = parts[1].strip()
                if not is_trusted and corrected_title and corrected_title != original_title:
                    if log_func:
                        log_func(f"🔧 AI 修正剧名: {original_title} → {corrected_title}", LOG_SUCCESS)
                    return corrected_title
    except Exception as e:
        logger.warning(f"AI 标题验证失败: {e}")
        if log_func:
            log_func(f"⚠️ AI 标题验证失败: {e}", LOG_WARNING)
    return None


def ai_select_best_match(
    src: Path,
    candidates: List[Dict],
    search_title: str,
    media_type: str,
    config: dict,
    log_func: Optional[Callable] = None,
    base_confidence: int = 0
) -> Optional[Dict]:
    ai_cfg = config.get("ai_parser", {})
    if not ai_cfg.get("enabled"):
        return None

    effective_min_conf = MIN_CONFIDENCE_FOR_AI_CACHE
    stem = src.stem
    if re.match(r'^\d+$', stem):
        effective_min_conf = 85
        if log_func:
            log_func(f"⚠️ 纯数字文件名，AI选择缓存阈值提高至 {effective_min_conf}%", "info")

    use_cache = (media_type != "movie") and (base_confidence >= effective_min_conf)

    folder_key = str(src.parent.resolve())
    cache_key = (folder_key, search_title, media_type)

    if use_cache:
        with _ai_selection_cache_lock:
            cached_tmdb_id = _ai_selection_cache.get(cache_key)
            if cached_tmdb_id:
                for item in candidates:
                    if item.get("id") == cached_tmdb_id:
                        if log_func:
                            title = item.get("title") or item.get("name")
                            log_func(f"📦 命中 AI 选择缓存: {title} (TMDB ID: {cached_tmdb_id})", LOG_INFO)
                        return item

    if log_func:
        log_func(f"🤖 检测到多个搜索结果，调用 AI 辅助选择...", LOG_INFO)

    top_candidates = candidates[:10]
    candidate_count = len(top_candidates)

    candidates_desc = []
    for idx, item in enumerate(top_candidates, 1):
        title = item.get("title") or item.get("name")
        year = (item.get("release_date") if media_type == "movie" else item.get("first_air_date") or "")[:4]
        candidates_desc.append(f"{idx}. {title} ({year})")

    candidates_text = "\n".join(candidates_desc)

    prompt = f"""你是影视文件识别专家。请从以下 TMDB 搜索结果中选择最匹配的一项。

原始文件信息：
- 文件路径：{src}
- 文件名：{src.name}
- 所在目录：{src.parent.name}
- 搜索词：{search_title}
- 媒体类型：{"电影" if media_type == "movie" else "剧集"}

候选列表：
{candidates_text}

**选择规则**：
1. 标题与搜索词完全相同或高度相似的候选最优先。
2. 若没有完全匹配，优先选择标题最短且包含搜索词（或被搜索词包含）的候选。
3. 注意：避免选择续作、外传、重制版，除非文件名明确包含对应关键词（如“Z”、“改”、“超”）。
4. 若有年份信息，优先选择与常见发行年份相符的。

请直接返回候选编号（1-{candidate_count}），例如：3"""

    try:
        resp = ai_client.call_ai_api(prompt, ai_cfg, log_func)
        if resp:
            match = re.search(r'\b([1-9]\d*)\b', resp)
            if match:
                idx = int(match.group(1)) - 1
                if 0 <= idx < candidate_count:
                    selected = top_candidates[idx]
                    tmdb_id = selected.get("id")
                    if tmdb_id and use_cache:
                        with _ai_selection_cache_lock:
                            _ai_selection_cache[cache_key] = tmdb_id
                    if log_func:
                        title = selected.get("title") or selected.get("name")
                        cache_msg = " (已缓存)" if use_cache else " (未缓存-低置信度)"
                        log_func(f"✅ AI 选择: {title}{cache_msg}", LOG_SUCCESS)
                    return selected
    except Exception as e:
        logger.warning(f"AI 辅助选择失败: {e}")
        if log_func:
            log_func(f"⚠️ AI 辅助选择失败，回退到评分算法", LOG_WARNING)
    return None


def search_tmdb_with_fallback(
    media_type: str,
    search_title: str,
    search_year: Optional[str],
    alt_titles: List[str],
    config: dict,
    log_func: Optional[Callable] = None,
    src: Optional[Path] = None,
    duration_hint: Optional[str] = None,
    title_for_attempts: str = "",
    base_confidence: int = 0
) -> Tuple[Optional[Dict], str, int]:
    # 0. 本地别名映射优先（最高优先级）
    alias = _lookup_local_alias(search_title)
    if alias:
        tmdb_id = alias.get("tmdb_id")
        forced_type = alias.get("media_type", media_type)
        if log_func:
            log_func(f"🔖 命中本地别名映射: {search_title} → TMDB ID {tmdb_id}", LOG_SUCCESS)
        return {"id": tmdb_id}, forced_type, 0

    try:
        from . import search_enhancer
    except ImportError:
        return original_search_tmdb(media_type, search_title, search_year, alt_titles, config, log_func, duration_hint)

    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")

    # 1. 内置别名映射（search_enhancer）
    alias = search_enhancer.lookup_local_alias(search_title)
    if alias:
        tmdb_id = alias.get("tmdb_id")
        forced_type = alias.get("media_type", media_type)
        if log_func:
            log_func(f"🔖 命中内置别名映射: {search_title} → TMDB ID {tmdb_id}", LOG_SUCCESS)
        return {"id": tmdb_id}, forced_type, 0

    # 2. 生成多级候选搜索词
    candidates = search_enhancer.generate_search_candidates(search_title)
    for alt in alt_titles:
        if alt and alt not in candidates:
            candidates.append(alt)
    if title_for_attempts and title_for_attempts not in candidates:
        candidates.append(title_for_attempts)

    primary_type = media_type
    secondary_type = "movie" if media_type == "tv" else "tv"
    if duration_hint and duration_hint != media_type:
        primary_type, secondary_type = secondary_type, primary_type
        if log_func:
            log_func(f"🔄 根据时长调整搜索优先级: 先搜 {primary_type}，再搜 {secondary_type}", LOG_INFO)

    languages_to_try = [language] if language == "en-US" else [language, "en-US"]

    for lang in languages_to_try:
        for mtype in (primary_type, secondary_type):
            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    raw_results = tmdb_client.search_tmdb_multi(
                        mtype, candidate, search_year, api_key, lang, log_func, proxy=proxy
                    )
                except Exception as e:
                    logger.warning(f"TMDB 搜索异常: {e}")
                    continue
                if raw_results:
                    candidate_count = len(raw_results)
                    if candidate_count > 1 and log_func:
                        log_func(f"⚠️ TMDB 搜索到 {candidate_count} 个可能的结果", LOG_WARNING)

                    # 标题可信度验证
                    if (candidate_count >= MIN_CANDIDATES_FOR_TITLE_CHECK and
                        config.get("ai_parser", {}).get("enabled") and
                        src is not None):
                        top_score = 0
                        for item in raw_results[:5]:
                            title = item.get("title") or item.get("name")
                            score = 0.0
                            if title:
                                if candidate.lower() == title.lower():
                                    score += 20
                                elif candidate.lower() in title.lower() or title.lower() in candidate.lower():
                                    score += 10
                            top_score = max(top_score, score)

                        if top_score < LOW_SCORE_THRESHOLD:
                            corrected = ai_verify_and_correct_title(
                                src, candidate, raw_results, config, log_func
                            )
                            if corrected and corrected != candidate:
                                if log_func:
                                    log_func(f"🔄 使用修正后的标题重新搜索: {corrected}", LOG_INFO)
                                return search_tmdb_with_fallback(
                                    media_type, corrected, search_year, alt_titles,
                                    config, log_func, src, duration_hint, title_for_attempts, base_confidence
                                )

                    # AI 辅助多结果选择
                    if candidate_count > 1 and config.get("ai_parser", {}).get("enabled") and src is not None:
                        ai_selected = ai_select_best_match(
                            src, raw_results, candidate, mtype, config, log_func, base_confidence
                        )
                        if ai_selected:
                            if lang != language and log_func:
                                log_func(f"🌐 使用 {lang} 搜索成功: {candidate}", LOG_SUCCESS)
                            if mtype != media_type and log_func:
                                log_func(f"🔄 使用备选类型 {mtype} 搜索成功", LOG_SUCCESS)
                            return ai_selected, mtype, candidate_count

                    # 回退到加权评分
                    top_candidates = raw_results[:5]
                    scored = []
                    for item in top_candidates:
                        title = item.get("title") or item.get("name")
                        score = 0.0
                        if title:
                            score -= len(title) * 0.5
                            if candidate.lower() == title.lower():
                                score += 20
                            candidate_lower = candidate.lower()
                            title_lower = title.lower()
                            if candidate_lower in title_lower or title_lower in candidate_lower:
                                score += 10
                            if any(word in title_lower for word in TECH_NOISE_WORDS):
                                score -= 15
                        item_year = (item.get("release_date") if mtype=="movie" else item.get("first_air_date") or "")[:4]
                        if search_year and item_year == str(search_year):
                            score += 30
                        scored.append((score, item))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    best = scored[0][1]

                    if lang != language and log_func:
                        log_func(f"🌐 使用 {lang} 搜索成功: {candidate}", LOG_SUCCESS)
                    if mtype != media_type and log_func:
                        log_func(f"🔄 使用备选类型 {mtype} 搜索成功", LOG_SUCCESS)
                    if len(scored) > 1 and log_func:
                        log_func(f"🎯 从 {candidate_count} 个结果中优选: {best.get('title') or best.get('name')}", LOG_INFO)
                    return best, mtype, candidate_count

    # 5. TVmaze 备选
    if media_type == "tv" and config.get("ai_parser", {}).get("enabled"):
        tmdb_id = search_enhancer.search_tvmaze(search_title)
        if tmdb_id:
            if log_func:
                log_func(f"📺 TVmaze 备选成功，找到 TMDB ID: {tmdb_id}", LOG_SUCCESS)
            return {"id": tmdb_id}, "tv", 0

    return None, media_type, 0
