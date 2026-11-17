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
        if not episodes:
            save_failed_cache(src, f"无法获取季 {season} 的集列表", cache_dict, log_func)
            return False

        ep_data = next((ep for ep in episodes if ep.get("episode_number") == episode), None)

        # 集号验证失败时的 AI 二次修正
        if not ep_data and info.get("_parser") == "anitopy" and config.get("ai_parser", {}).get("enabled"):
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
