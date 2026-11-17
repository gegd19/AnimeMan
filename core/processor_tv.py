#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剧集处理分支（整合版）
包含总集数换算、AI二次修正、置信度阈值等
- 代理支持：所有 TMDB 请求（含图片下载）均传递 proxy 参数
"""

from .failure_policy import note_error
from .ai_budget import AIBudgetExceeded
from .log_redaction import redact
from .json_store import CacheCorruptionError
from .cancellation import check_cancelled, ProcessingCancelled
import os
import re
import threading
import unicodedata
import time
from pathlib import Path
from .path_safety import absolute_link_path, validate_target_path
from typing import Dict, Optional, Callable

from . import cache_manager, tmdb_client, nfo_writer, file_linker, subtitle_handler, ai_client
from .processor_helpers import extract_all_alternative_titles
from .media_paths import episode_video_path
from .processor_cache_ops import save_failed_cache
from .constants import MIN_FINAL_CONFIDENCE
from .logger import get_logger
from .library_transaction import transactional_media, preview_target

logger = get_logger(__name__)

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"


_SPECIAL_MARK = re.compile(r'(?i)(?<![a-z])(?:ova|oad|sp|special|specials|ncop|nced)(?![a-z])|特典|特[别別]篇|番外|\bS0*0E\d')
_EPISODE_TITLE_CACHE: Dict[tuple, list] = {}
_EPISODE_TITLE_LOCK = threading.Lock()


def episode_title_key(text) -> str:
    """Comparable key for an episode title written in the file name; empty when it says nothing."""
    if not isinstance(text, str):
        return ""
    value = unicodedata.normalize("NFKC", text).casefold().strip()
    if re.fullmatch(r"(?:episode|ep|第)?\s*\d+\s*(?:集|話|话)?", value):
        return ""
    key = re.sub(r"[\W_]+", "", value)
    return key if len(key) >= 6 and re.search(r"[a-z]", key) else ""


def _english_episodes(tmdb_id, season, api_key, proxy):
    with _EPISODE_TITLE_LOCK:
        cached = _EPISODE_TITLE_CACHE.get((tmdb_id, season))
    if cached is not None:
        return cached
    episodes = tmdb_client.get_tv_season_episodes(tmdb_id, season, api_key, "en-US", None, proxy=proxy) or []
    found = [(ep.get("episode_number"), episode_title_key(ep.get("name"))) for ep in episodes if isinstance(ep, dict)]
    with _EPISODE_TITLE_LOCK:
        if len(_EPISODE_TITLE_CACHE) > 256:
            _EPISODE_TITLE_CACHE.clear()
        _EPISODE_TITLE_CACHE[(tmdb_id, season)] = found
    return found


def episodes_named(key, tmdb_id, seasons, api_key, proxy):
    """(season, episode) pairs whose English TMDB title is the one written in the file name."""
    hits = []
    for season in seasons:
        for number, name in _english_episodes(tmdb_id, season, api_key, proxy):
            if type(number) is int and name and (name == key or (len(key) >= 10 and (name.startswith(key) or key.startswith(name)))):
                hits.append((season, number))
    return hits


_SEASON_NAME_NUMBERS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _named_season(name) -> Optional[int]:
    """The season number a group name states (Season 4, S4, 第4季, 第四季), or None."""
    if not isinstance(name, str):
        return None
    if _SPECIAL_MARK.search(name) or re.search(r'特[别別]|特典', name):
        return 0
    match = re.search(r'(?i)(?:\bseason\s*|\bS)0*(\d{1,2})\b|第\s*0*(\d{1,2})\s*[季期]|第\s*([一二三四五六七八九十])\s*[季期]', name)
    if not match:
        return None
    return int(match.group(1) or match.group(2)) if (match.group(1) or match.group(2)) else _SEASON_NAME_NUMBERS[match.group(3)]


def season_from_episode_groups(tmdb_id, season, episode, api_key, language, log_func=None, proxy=None):
    """Map a release season that TMDB folds into one long season, using TMDB's own episode groups.

    Accepted only when every group that names this season agrees: its N-th part is named season N, and the
    part has at least this many episodes. Returns (tmdb season, tmdb episode, group name) or None.
    """
    answers = {}
    for summary in tmdb_client.get_tv_episode_groups(tmdb_id, api_key, language, log_func, proxy)[:8]:
        if not isinstance(summary, dict) or summary.get("type") not in (1, 3, 4, 6, 7):
            continue
        group = tmdb_client.get_episode_group(summary.get("id"), api_key, language, log_func, proxy)
        parts = sorted((p for p in (group or {}).get("groups") or [] if isinstance(p, dict)), key=lambda p: p.get("order", 0))
        numbers = [_named_season(p.get("name")) for p in parts]
        # Every regular part names its season, in order (a season may be split into parts, "Season 2 Part 2"),
        # so "Season 4" is not an arc that happens to say 4.
        regular = [n for n in numbers if n != 0]
        if None in regular or not regular or season not in regular:
            continue
        sequence = [n for i, n in enumerate(regular) if i == 0 or n != regular[i - 1]]
        if sequence != list(range(1, len(sequence) + 1)):
            continue
        eps = [e for p, n in zip(parts, numbers) if n == season
               for e in sorted((e for e in p.get("episodes") or [] if isinstance(e, dict)), key=lambda e: e.get("order", 0))]
        if not 1 <= episode <= len(eps):
            continue
        target = eps[episode - 1]
        sn, en = target.get("season_number"), target.get("episode_number")
        if type(sn) is int and type(en) is int and sn > 0 and en > 0:
            answers.setdefault((sn, en), summary.get("name") or "")
    if len(answers) != 1:
        if len(answers) > 1 and log_func:
            log_func(f"TMDB 剧集组对第 {season} 季给出不同的换算结果，需要人工确认", LOG_WARNING)
        return None
    (sn, en), name = next(iter(answers.items()))
    return sn, en, name


@transactional_media
def process_tv_branch(
    src: Path,
    config: dict,
    cache_dict: dict,
    log_func: Optional[Callable],
    official_title: str,
    official_year: str,
    tmdb_id: int,
    details: Dict,
    info: Dict,
    confidence: int
) -> bool:
    """处理剧集文件"""
    if confidence < MIN_FINAL_CONFIDENCE:
        save_failed_cache(src, f"匹配评分过低 ({confidence} < {MIN_FINAL_CONFIDENCE})", cache_dict, log_func)
        return False

    try:
        season = info.get("season")
        episode = info.get("episode")
        if (type(tmdb_id) is not int or tmdb_id <= 0
                or not isinstance(official_title, str) or not official_title.strip()
                or type(season) is not int or season < 0
                or type(episode) is not int or episode < 1):
            save_failed_cache(src, "剧集身份信息不完整，需要人工确认", cache_dict, log_func)
            return False
        mapped = None
        if config.get('numbering_maps', {}).get('enabled') is True:
            from . import numbering_maps
            try:
                mapped_revision = numbering_maps.revision()
                label = numbering_maps.extract_source_label(src.name)
                mapped = numbering_maps.match(config, src, tmdb_id, label) if label else None
                if info.get('_numbering_map_id') and (not mapped or mapped['id'] != info['_numbering_map_id']):
                    raise numbering_maps.MappingConflict('编号映射已变化，需要人工确认')
                if mapped:
                    if (not isinstance(details,dict) or type(details.get('id')) is not int
                            or details['id'] != tmdb_id or not isinstance(details.get('name'),str) or not details['name'].strip()):
                        raise numbering_maps.MappingConflict('作品身份无法验证，需要人工确认')
                    user_file_conflict = (info.get('_user_rule_id') and info.get('_user_rule_scope', 'file') == 'file'
                                          and (season,episode) != (mapped['season'],mapped['episode']))
                    old_season, old_episode = info.get('_special_mapping_season'), info.get('_special_mapping_episode')
                    special_conflict = (info.get('_special_mapping') and
                                        ((old_season is not None and old_season != mapped['season']) or
                                         (old_episode is not None and old_episode != mapped['episode'])))
                    if user_file_conflict or special_conflict:
                        raise numbering_maps.MappingConflict('编号映射与人工规则指定的季集冲突，需要人工确认')
                    season,episode = mapped['season'],mapped['episode']
                    info = dict(info, season=season, episode=episode, explicit_season=season,
                                numbering_source='season_relative', total_episode=None,
                                corrected_season=None, corrected_episode=None,
                                _numbering_map_id=mapped['id'], _numbering_source_label=label)
                    if not any(type(item.get('season_number')) is int and item['season_number'] == season
                               for item in details.get('seasons',[]) if isinstance(item,dict)):
                        raise numbering_maps.MappingConflict('映射目标季不在 TMDB 作品中，需要人工确认')
                    if log_func:log_func(f"🔖 编号映射: {label} → S{season:02d}E{episode:02d}", LOG_INFO)
            except numbering_maps.MappingConflict as error:
                save_failed_cache(src, str(error), cache_dict, log_func)
                return False
        explicit_season = info.get("explicit_season", season)
        total_episode = info.get("total_episode")

        api_key = config["tmdb_api"]["api_key"]
        language = config["tmdb_api"].get("language", "zh-CN")
        proxy = config.get("tmdb_api", {}).get("proxy")          # 获取代理配置
        base_url = config["image_base_url"]

        # Only explicitly established absolute numbering may be converted.
        numbering_source = info.get("numbering_source", "unknown")
        if numbering_source not in ("season_relative", "absolute", "unknown"):
            save_failed_cache(src, "编号来源无效，需要人工确认", cache_dict, log_func)
            return False
        if total_episode is not None and numbering_source == "unknown":
            save_failed_cache(src, "累计集号来源不明确，需要人工确认", cache_dict, log_func)
            return False
        if numbering_source == "absolute":
            if type(total_episode) is not int or total_episode < 1:
                save_failed_cache(src, "累计集号无效，需要人工确认", cache_dict, log_func)
                return False
            season_numbers = sorted({s.get("season_number") for s in details.get("seasons", [])
                                     if type(s.get("season_number")) is int and s.get("season_number") > 0})
            cumulative = 0
            converted = False
            for expected_number, sn in enumerate(season_numbers, 1):
                if sn != expected_number:
                    break
                eps = tmdb_client.get_tv_season_episodes(tmdb_id, sn, api_key, language, log_func, proxy=proxy)
                if not eps:
                    break
                episode_numbers = [ep.get("episode_number") for ep in eps if isinstance(ep, dict)]
                if (len(episode_numbers) != len(eps)
                        or any(type(number) is not int for number in episode_numbers)
                        or sorted(episode_numbers) != list(range(1, len(eps) + 1))):
                    break
                season_meta = next((item for item in details.get("seasons", [])
                                    if item.get("season_number") == sn), {})
                stated_count = season_meta.get("episode_count")
                if type(stated_count) is int and stated_count != len(eps):
                    break
                if cumulative + len(eps) >= total_episode:
                    if explicit_season is not None and sn != explicit_season:
                        break
                    season, episode = sn, total_episode - cumulative
                    confidence = max(confidence - 10, 0)
                    converted = True
                    if log_func:
                        log_func(f"🔄 总集数转换: 第{total_episode}集 → S{season:02d}E{episode:02d}", LOG_INFO)
                    break
                cumulative += len(eps)
            if not converted:
                save_failed_cache(src, "累计集号无法可靠换算，需要人工确认", cache_dict, log_func)
                return False

        # 应用 AI 修正
        corrected_season = info.get("corrected_season")
        corrected_episode = info.get("corrected_episode")
        if corrected_season is not None and corrected_episode is not None:
            if corrected_season != season:
                save_failed_cache(src, "季号修正与原始季号冲突，需要人工确认", cache_dict, log_func)
                return False
            season = corrected_season
            episode = corrected_episode
            confidence = max(confidence - 10, 0)
            if log_func:
                log_func(f"✨ 应用 AI 修正: S{info['season']:02d}E{info['episode']:02d} -> S{season:02d}E{episode:02d}", LOG_INFO)

        # A special (season 0) that only the AI suggested: TMDB numbers specials its own way, so a name without a
        # special marker is not enough to pick one of them.
        if season == 0 and info.get("_from_ai") and not _SPECIAL_MARK.search(f"{src.parent.name} {src.stem}"):
            save_failed_cache(src, "AI 判断为特别篇（第 0 季），但文件名没有特别篇标记，需要人工确认", cache_dict, log_func)
            return False

        # 常规剧集处理
        regular_seasons = [s for s in details.get("seasons", []) if s.get("season_number", 0) > 0]
        special_seasons = [s for s in details.get("seasons", []) if s.get("season_number", 0) == 0]

        if not regular_seasons and not special_seasons:
            save_failed_cache(src, "TMDB 中没有季信息", cache_dict, log_func)
            return False

        episodes = tmdb_client.get_tv_season_episodes(
            tmdb_id, season, api_key, language, log_func, proxy=proxy
        )
        # Missing or unavailable season data is not evidence for another season.
        # The one exception: TMDB has no such season, and its own episode groups name that season explicitly.
        if not episodes and season > 0 and season not in {s.get("season_number") for s in regular_seasons}:
            group_mapped = season_from_episode_groups(tmdb_id, season, episode, api_key, language, log_func, proxy)
            if group_mapped:
                if log_func:
                    log_func(f"🔄 TMDB 没有第 {season} 季，按 TMDB 剧集组「{group_mapped[2]}」换算: S{season:02d}E{episode:02d} → S{group_mapped[0]:02d}E{group_mapped[1]:02d}", LOG_INFO)
                season, episode = group_mapped[0], group_mapped[1]
                confidence = max(confidence - 10, 0)
                episodes = tmdb_client.get_tv_season_episodes(tmdb_id, season, api_key, language, log_func, proxy=proxy)
        title_key = episode_title_key(info.get("episode_title"))
        regular_numbers = sorted(n for n in {s.get("season_number") for s in regular_seasons} if type(n) is int and n > 0)
        if not episodes and title_key:
            named = episodes_named(title_key, tmdb_id, regular_numbers[:12], api_key, proxy)
            if len(named) == 1:
                if log_func:
                    log_func(f"🔤 集名「{info.get('episode_title')}」只对应 TMDB S{named[0][0]:02d}E{named[0][1]:02d}，按集名入库", LOG_INFO)
                season, episode = named[0]
                episodes = tmdb_client.get_tv_season_episodes(tmdb_id, season, api_key, language, log_func, proxy=proxy)
        if not episodes:
            save_failed_cache(src, f"无法获取季 {season} 的集列表", cache_dict, log_func)
            return False

        ep_data = next((ep for ep in episodes if ep.get("episode_number") == episode), None)
        if title_key:
            named = episodes_named(title_key, tmdb_id, [season], api_key, proxy)
            if (season, episode) in named:
                if log_func:
                    log_func("🔤 文件里的集名与 TMDB 该集一致", LOG_SUCCESS)
                if isinstance(config.get("_recognition_score"), dict):
                    config["_recognition_score"].setdefault("evidence", []).append("文件里的集名与 TMDB 该集一致")
                confidence = min(confidence + 5, 100)
            elif len(named) == 1 and ep_data:
                save_failed_cache(src, f"文件里的集名「{info.get('episode_title')}」对应 TMDB 第 {named[0][1]} 集，"
                                       f"与集号 {episode} 不一致，需要人工确认", cache_dict, log_func)
                return False
            elif len(named) == 1 and not ep_data:
                if log_func:
                    log_func(f"🔤 TMDB 第 {season} 季没有第 {episode} 集，集名对应第 {named[0][1]} 集，按集名入库", LOG_INFO)
                episode = named[0][1]
                ep_data = next((ep for ep in episodes if ep.get("episode_number") == episode), None)

        # 集号验证失败时的 AI 二次修正
        if not ep_data and mapped is None and info.get("_parser") == "anitopy" and config.get("ai_parser", {}).get("enabled"):
            if log_func:
                log_func(f"⚠️ TMDB 中无 S{season:02d}E{episode:02d}，尝试使用 AI 重新解析...", LOG_WARNING)

            season_info = ', '.join([f'第{s.get("season_number")}季({s.get("episode_count")}集)' for s in details.get('seasons', []) if s.get('season_number', 0) > 0])

            context_prompt = f"""你是一个专业的影视文件名修正专家。以下信息来自一个自动解析失败的视频文件：

原始文件路径：{src}
文件名：{src.name}
所在目录：{src.parent.name}

自动解析工具 (anitopy) 给出的结果：
- 标题：{info.get('title')}
- 季号：{season}
- 集号：{episode}
- 显式季数：{explicit_season}
- 总集数：{total_episode}

TMDB 搜索结果：
- 已找到剧集：{official_title} (TMDB ID: {tmdb_id})
- 该剧集共有季：{season_info}
- 但在第 {season} 季中未找到第 {episode} 集。

请仅在证据充分时建议季集，不得猜测或默认第 0 季或第 1 集；
如果无法确认，将 corrected_season 与 corrected_episode 均设为 null。
不要改变已有明确季号。候选季集仍须通过 TMDB 验证。

请直接返回 JSON 格式：
{{
  "corrected_season": 整数或 null,
  "corrected_episode": 整数或 null,
  "reason": "简短修正理由"
}}
只返回 JSON，不要任何额外解释。"""

            ai_cfg = config.get("ai_parser", {})
            ai_resp = ai_client.call_ai_api(context_prompt, ai_cfg, log_func)
            if ai_resp:
                try:
                    from .validation import strict_loads
                    correction = strict_loads(ai_resp)
                    if not isinstance(correction, dict) or set(correction) != {"corrected_season", "corrected_episode", "reason"}:
                        raise ValueError("AI 季集建议格式无效")
                    new_season = correction["corrected_season"]
                    new_episode = correction["corrected_episode"]
                    reason = correction["reason"]
                    if new_season is None and new_episode is None:
                        save_failed_cache(src, "AI 无法确认季集，需要人工确认", cache_dict, log_func)
                        return False
                    if (type(new_season) is not int or not 0 <= new_season <= 99
                            or type(new_episode) is not int or not 1 <= new_episode <= 9999
                            or not isinstance(reason, str)):
                        raise ValueError("AI 季集建议无效")
                    if log_func:
                        log_func(f"🤖 AI 修正建议: S{new_season:02d}E{new_episode:02d} ({reason})", LOG_INFO)

                    if new_season != season:
                        save_failed_cache(src, "AI 建议更改季号，需要人工确认", cache_dict, log_func)
                        return False
                    episodes_new = tmdb_client.get_tv_season_episodes(
                        tmdb_id, new_season, api_key, language, log_func, proxy=proxy
                    )
                    ep_data = next((ep for ep in episodes_new if ep.get("episode_number") == new_episode), None)
                    if ep_data:
                        season = new_season
                        episode = new_episode
                        confidence = max(confidence - 15, 0)
                        if log_func:
                            log_func(f"✅ AI 修正成功: S{season:02d}E{episode:02d}", LOG_SUCCESS)
                    else:
                        if log_func:
                            log_func(f"❌ AI 修正后仍无匹配 (S{new_season:02d}E{new_episode:02d})", LOG_ERROR)
                except ProcessingCancelled:
                    raise
                except CacheCorruptionError:
                    raise
                except Exception as e:
                    note_error(e)
                    logger.warning(f"AI 修正响应解析失败: {e}")
                    if log_func:
                        log_func(f"❌ AI 修正响应解析失败: {redact(e)}", LOG_WARNING)

        if not ep_data:
            save_failed_cache(src, f"TMDB中无 S{season:02d}E{episode:02d} 数据", cache_dict, log_func)
            return False

        # Series-wide episode_run_time is not reliable evidence for this episode.
        from .duration_evidence import compare_duration
        duration_evidence = compare_duration(config.get("_local_video_duration"), ep_data.get("runtime"))
        if (season == 0 and duration_evidence['status'] != 'unknown'
                and config.get("_local_video_duration") > 90
                and duration_evidence['status'] != 'conflict'):
            reason = "长时长特辑需要人工确认"
            if log_func and config.get("dry_run"):
                log_func(f"⚠️ {reason}", LOG_WARNING)
            save_failed_cache(src, reason, cache_dict, log_func)
            return False
        if duration_evidence['status'] == 'conflict':
            reason = (f"该集时长与 TMDB 差异 {duration_evidence['difference']:.1f} 分钟，"
                      f"超过容差 {duration_evidence['tolerance']:.1f} 分钟，需要人工确认")
            if log_func and config.get("dry_run"):
                log_func(f"⚠️ {reason}", LOG_WARNING)
            save_failed_cache(src, reason, cache_dict, log_func)
            return False
        if duration_evidence['status'] == 'supported' and '_recognition_score' in config:
            score = dict(config['_recognition_score'])
            score['evidence'] = [*score['evidence'], '该集时长与 TMDB 在容差内']
            config = dict(config, _recognition_score=score)

        confidence = min(confidence + 5, 100)
        if (type(season) is not int or season < 0
                or type(episode) is not int or episode < 1):
            save_failed_cache(src, "最终季集身份无效，需要人工确认", cache_dict, log_func)
            return False
        if confidence < MIN_FINAL_CONFIDENCE:
            reason = f"最终匹配评分过低 ({confidence} < {MIN_FINAL_CONFIDENCE})"
            if log_func and config.get("dry_run"):
                log_func(f"⚠️ {reason}", LOG_WARNING)
            save_failed_cache(src, reason, cache_dict, log_func)
            return False

        if mapped is not None and numbering_maps.revision() != mapped_revision:
            save_failed_cache(src, "编号映射在验证期间发生变化，需要人工确认", cache_dict, log_func)
            return False

        target_path = episode_video_path(src, config, official_title, official_year,
                                         season, episode, ep_data.get("name"))
        season_dir = target_path.parent
        show_dir = season_dir.parent

        if config.get("dry_run"):
            target_path = preview_target(src, target_path, config, "tv")
            if log_func:
                log_func(f"🔍 [模拟] -> {target_path}", LOG_INFO)
            return True

        nfo_writer.write_tvshow_nfo(show_dir, official_title, tmdb_id, details.get("overview", ""), official_year, len(regular_seasons), config, log_func)
        if config.get("download_images"):
            if poster := details.get("poster_path"):
                tmdb_client.download_image(
                    tmdb_client.build_image_url(base_url, poster),
                    show_dir / "poster.jpg",
                    log_func,
                    proxy=proxy
                )
            if backdrop := details.get("backdrop_path"):
                tmdb_client.download_image(
                    tmdb_client.build_image_url(base_url, backdrop),
                    show_dir / "fanart.jpg",
                    log_func,
                    proxy=proxy
                )

        nfo_writer.write_season_nfo(season_dir, season, tmdb_id, log_func)
        nfo_writer.write_episode_nfo(season_dir, ep_data, official_title, season, episode, tmdb_id, config, log_func, video_path=target_path)

        target_path = validate_target_path(src, target_path, config, "tv")

        if not file_linker.create_link(src, target_path, config["link_type"], log_func):
            return False
        src_str = str(src.resolve())
        alt_titles = extract_all_alternative_titles(details, official_title)

        with cache_manager.cache_lock:
            cache_dict[src_str] = {
                "target": str(absolute_link_path(target_path)),
                "source_path": src_str,
                "fingerprint": cache_manager.get_file_fingerprint(src),
                "fingerprint_strong": cache_manager.get_file_fingerprint_strong(src),
                "media_type": "tv",
                "title": official_title,
                "season": season,
                "episode": episode,
                "tmdb_id": tmdb_id,
                "confidence": confidence,
                **({"score_origin": config["_recognition_score"]["origin"],
                    "score_evidence": list(config["_recognition_score"]["evidence"]),
                    "score_conflicts": list(config["_recognition_score"]["conflicts"])}
                   if "_recognition_score" in config else {}),
                "processed_time": time.time(),
                "alternative_titles": alt_titles,
                "episode_title": ep_data.get("name", "")
            }

        if config.get("subtitle", {}).get("enabled", True):
            subtitle_handler.process_subtitles_for_video(src, target_path, season_dir, config, log_func)

        if log_func:
            label = "人工指定" if config.get("_recognition_score", {}).get("origin") == "manual_mapping" else f"匹配评分: {confidence}"
            log_func(f"💾 缓存已保存 ({label})", LOG_SUCCESS)
        return True
    except AIBudgetExceeded:
        raise
    except ProcessingCancelled:
        raise
    except CacheCorruptionError:
        raise
    except Exception as e:
        note_error(e)
        logger.error(f"剧集分支处理失败 {src}: {e}", exc_info=True)
        save_failed_cache(src, f"处理异常: {e}", cache_dict, log_func)
        return False
