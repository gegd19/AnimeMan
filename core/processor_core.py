#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单文件核心处理流程（主入口）
已拆分为多个子模块：
- constants.py：全局常量
- processor_helpers.py：通用辅助函数
- processor_search.py：TMDB搜索与AI辅助选择
- processor_movie.py：电影处理分支
- processor_tv.py：剧集处理分支
- processor_folder_ai.py：文件夹级AI批量解析
"""

from .ai_budget import AIBudgetExceeded, with_recognition_budget
from .failure_policy import note_error
from .parse_identity import tmdb_scope,with_identity_scope
from .json_store import CacheCorruptionError
from .cancellation import check_cancelled, ProcessingCancelled
import re
import time
import threading
import os
from pathlib import Path
from .execution_mode import execution_scope, is_preview
from typing import Dict, Any, Optional, Callable, List, Tuple

from . import cache_manager, parse_identity
from . import tmdb_client
from . import nfo_writer
from . import file_linker
from . import subtitle_handler
from . import video_info
from . import ai_client

from .constants import *
from .processor_helpers import (
    apply_special_mapping, parse_filename_info, compute_confidence,
    prepare_search_query, extract_all_alternative_titles, build_season_indicators
)
from .processor_search import search_tmdb_with_fallback
from .processor_movie import process_movie_branch
from .processor_tv import process_tv_branch
from .processor_folder_ai import try_folder_ai_batch
from .processor_utils import sanitize_filename, wrap_progress_callback
from .processor_cache_ops import save_failed_cache
from .logger import get_logger

logger = get_logger(__name__)

from .cancellation import stop_processing

SEASON_INDICATORS = build_season_indicators(30)

# 文件夹级 TMDB 缓存（成功匹配结果缓存）
_folder_tmdb_cache: Dict[Tuple[str, str], int] = {}
# Words that make a title name a later part of a series, so a season next to it counts from that part.
_SEQUEL_MARK = re.compile(r'(?i)(?:^|[\s._:~-])(?:II|III|IV|V|VI|VII|VIII|IX|X|\d+(?:st|nd|rd|th)|season|part|act|cour|final|zoku|shin)(?=$|[\s._:!~-])'
                          r'|(?<!no\.)\s\d{1,2}$|第\s*[一二三四五六七八九十\d]+\s*[季部期]|[续續]篇')
_folder_tmdb_cache_lock = threading.RLock()


@execution_scope
@with_identity_scope
@with_recognition_budget
def process_video(
    src: Path,
    config: Dict[str, Any],
    cache_dict: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> bool:
    wrapped_log = wrap_progress_callback(log_func)

    check_cancelled()

    try:
        force_tmdb_id, force_media_type, force_season, force_episode = apply_special_mapping(src, config, wrapped_log)
        user_rule = None
        local_info = None
        if config.get("user_rules", {}).get("enabled") is True:
            from .user_recognition_rules import match_rule, RuleValidationError
            try:
                user_rule = match_rule(src, config, {})
                local_config = dict(config, ai_parser=dict(config.get("ai_parser", {}), enabled=False))
                local_info = parse_filename_info(src, local_config, wrapped_log)
                user_rule = match_rule(src, config, local_info)
                if (user_rule is None and config.get('numbering_maps', {}).get('enabled') is True
                        and local_info.get('reason_code') == 'unsupported_episode_numbering'):
                    from .numbering_maps import decimal_title_hint
                    hint_title = decimal_title_hint(src.name)
                    if hint_title:
                        user_rule = match_rule(src, config, {'title':hint_title, 'media_type':'tv'})
                if (user_rule is None and not local_info.get('reason_code') and local_info.get('episode') is None):
                    from .folder_evidence import special_series_hint
                    hint = special_series_hint(src)
                    if hint:
                        user_rule = match_rule(src, config, hint)
                if user_rule and user_rule.get('_lower_priority_conflict') and wrapped_log:
                    wrapped_log(user_rule['_lower_priority_conflict'], LOG_WARNING)
                if user_rule and force_tmdb_id is not None:
                    conflict = (force_tmdb_id != user_rule['tmdb_id'] or force_media_type != user_rule['media_type'])
                    if user_rule['scope'] == 'file' and user_rule['media_type'] == 'tv':
                        conflict = conflict or (force_season is not None and force_season != user_rule['season']) or (force_episode is not None and force_episode != user_rule['episode'])
                    if conflict:
                        raise RuleValidationError("人工规则与已有特辑映射冲突，需要人工确认")
            except RuleValidationError as error:
                save_failed_cache(src, f"身份信息需要人工确认: {error}", cache_dict, wrapped_log)
                return False
        hint_id = None
        hint_type = None
        if config.get("identity_hints", {}).get("enabled", False):
            from .explicit_media_identity import extract_path_identity, extract_nfo_identity, explicit_media_type, IdentityEvidenceError
            try:
                roots = config.get("source_folders", [])
                path_id = extract_path_identity(src, roots)
                nfo_identity = extract_nfo_identity(src, roots)
                path_type = (explicit_media_type(src, roots)
                             if path_id is not None or nfo_identity or force_tmdb_id else None)
                if force_tmdb_id and path_type and path_type != force_media_type:
                    raise IdentityEvidenceError("人工映射与路径中的媒体类型冲突")
                if path_id is not None and nfo_identity and path_id != nfo_identity[1]:
                    raise IdentityEvidenceError("路径与 NFO 的 TMDB ID 冲突")
                if nfo_identity and path_type and path_type != nfo_identity[0]:
                    raise IdentityEvidenceError("路径与 NFO 的媒体类型冲突")
                hint_id = path_id if path_id is not None else (nfo_identity[1] if nfo_identity else None)
                if hint_id is not None:
                    hint_type = force_media_type if force_tmdb_id else (path_type or (nfo_identity[0] if nfo_identity else None))
                    if hint_type not in ("tv", "movie"):
                        raise IdentityEvidenceError("TMDB ID 缺少明确媒体类型")
                    if force_tmdb_id and (force_tmdb_id != hint_id or force_media_type != hint_type
                                          or (nfo_identity and nfo_identity[0] != force_media_type)):
                        raise IdentityEvidenceError("人工映射与路径或 NFO 的 TMDB 身份冲突")
            except IdentityEvidenceError as error:
                save_failed_cache(src, f"身份信息需要人工确认: {error}", cache_dict, wrapped_log)
                if config.get("dry_run") and wrapped_log:
                    wrapped_log(f"身份信息需要人工确认: {error}", LOG_WARNING)
                return False
        if user_rule and hint_id is not None and (user_rule['tmdb_id'] != hint_id or user_rule['media_type'] != hint_type):
            save_failed_cache(src, "人工规则与路径或 NFO 的 TMDB 身份冲突，需要人工确认", cache_dict, wrapped_log)
            return False
        parse_config = config
        if hint_id is not None or user_rule:
            parse_config = dict(config, ai_parser=dict(config.get("ai_parser", {}), enabled=False))
        info = parse_filename_info(src, parse_config, wrapped_log, force_tmdb_id, force_media_type, force_season, force_episode)

        if (user_rule and user_rule['media_type'] == 'tv'
                and info.get('reason_code') is None and info.get('episode') is None):
            from .folder_evidence import pending_file_identity
            save_failed_cache(src, "作品身份已确认，季集需要人工确认", cache_dict, wrapped_log)
            if not is_preview(config):
                entry = cache_dict.get(str(src.resolve()), {})
                if entry.get('media_type') == 'failed':
                    entry['recognition_pending'] = pending_file_identity(src, config, user_rule)
            return False

        # A decimal source label can proceed only with separately confirmed TV identity
        # and an exact explicit mapping; ranges and mixed identity stay for review.
        if (config.get('numbering_maps', {}).get('enabled') is True
                and info.get('reason_code') in ('unsupported_episode_numbering','ambiguous_roman_season')):
            from . import numbering_maps
            try:
                label = numbering_maps.extract_source_label(src.name)
                identity = (user_rule['tmdb_id'] if user_rule and user_rule['media_type'] == 'tv'
                            else force_tmdb_id if force_media_type == 'tv' else hint_id if hint_type == 'tv' else None)
                mapping = numbering_maps.match(config, src, identity, label) if label and identity else None
                if mapping:
                    prior = ((user_rule['season'], user_rule['episode']) if user_rule and user_rule['scope']=='file'
                             else (force_season, force_episode) if force_tmdb_id is not None else None)
                    if prior and ((prior[0] is not None and prior[0] != mapping['season']) or (prior[1] is not None and prior[1] != mapping['episode'])):
                        raise numbering_maps.MappingConflict('编号映射与单文件人工规则冲突，需要人工确认')
                    info = {'title':src.stem, 'search_title':src.stem, 'media_type':'tv',
                            'season':mapping['season'], 'episode':mapping['episode'],
                            'explicit_season':mapping['season'], 'numbering_source':'season_relative',
                            'tmdb_id':identity, '_explicit_identity':True, '_parser':'manual_numbering',
                            '_numbering_map_id':mapping['id'], '_numbering_source_label':label}
            except numbering_maps.MappingConflict as error:
                save_failed_cache(src, str(error), cache_dict, wrapped_log)
                return False

        if info.get('reason_code') == 'ambiguous_roman_season':
            confirmed = ((user_rule['season'], user_rule['episode'])
                         if user_rule and user_rule['scope']=='file' and user_rule['media_type']=='tv'
                         else (force_season, force_episode) if force_tmdb_id and force_media_type=='tv' else None)
            if (confirmed and type(confirmed[0]) is int and 0 <= confirmed[0] <= 99
                    and type(confirmed[1]) is int and 1 <= confirmed[1] <= 9999
                    and isinstance(info.get('title'),str) and info['title'].strip()):
                info = dict(info, media_type='tv', season=confirmed[0], episode=confirmed[1],
                            explicit_season=confirmed[0], numbering_source='season_relative')
                info.pop('reason_code',None)

        review_reasons = {
            "unsupported_episode_numbering": "集号范围或小数需要人工确认",
            "ambiguous_roman_season": "片名中的罗马数字不能确定季号，需要人工确认",
            "conflicting_season_evidence": "文件名与目录季号冲突，需要人工确认",
            "missing_series_title": "源目录内缺少可确认的剧集标题",
        }
        reason_code = info.get("reason_code")
        if reason_code in review_reasons:
            message = f"{reason_code}: {review_reasons[reason_code]}"
            save_failed_cache(src, message, cache_dict, wrapped_log)
            if config.get("dry_run") and wrapped_log:
                wrapped_log(message, LOG_WARNING)
            return False

        if hint_id is not None:
            if info.get("media_type") != hint_type:
                message = "解析媒体类型与路径中的 TMDB ID 冲突，需要人工确认"
                save_failed_cache(src, message, cache_dict, wrapped_log)
                if config.get("dry_run") and wrapped_log:
                    wrapped_log(message, LOG_WARNING)
                return False
            info = dict(info, tmdb_id=hint_id, _explicit_identity=True)

        if user_rule:
            if info.get('media_type') != user_rule['media_type']:
                save_failed_cache(src, "人工规则与解析媒体类型冲突，需要人工确认", cache_dict, wrapped_log)
                return False
            info = dict(info, tmdb_id=user_rule['tmdb_id'], _explicit_identity=True, _user_rule_id=user_rule['id'], _user_rule_scope=user_rule['scope'])
            if user_rule['scope'] == 'file' and user_rule['media_type'] == 'tv':
                info.update(season=user_rule['season'], episode=user_rule['episode'])

        if force_tmdb_id is not None:
            info['_special_mapping'] = True
            info['_special_mapping_season'] = force_season
            info['_special_mapping_episode'] = force_episode

        # 文件夹级 AI 批量解析
        folder_evidence = config.get('_folder_evidence')
        shared_allowed = not folder_evidence or (folder_evidence.get('complete') and folder_evidence.get('identity_status') != 'conflict' and not folder_evidence.get('unknown'))
        updated_info = (None if info.get("_explicit_identity") or not shared_allowed else
                        try_folder_ai_batch(src, config, info, force_tmdb_id, wrapped_log))
        if updated_info:
            info = updated_info

        def try_process_with_info(current_info: Dict, confidence_start: int):
            media_type = current_info.get("media_type")
            title = current_info.get("title") or ""
            if not title or title == "Unknown" or media_type not in ("movie", "tv"):
                return (False, None, None, None, None, None, confidence_start, current_info)

            if media_type == "tv" and (current_info.get("season") is None or current_info.get("episode") is None):
                return (False, None, None, None, None, None, confidence_start, current_info)

            confidence = confidence_start
            local_duration = video_info.get_video_duration(src)
            duration_hint = None
            if local_duration is not None and wrapped_log:
                wrapped_log(f"⏱️ 视频时长: {local_duration:.1f} 分钟", LOG_INFO)

            title_orig, search_title, search_year, alt_titles = prepare_search_query(current_info, TECH_NOISE_WORDS, aliases_enabled=config.get('recognition_aliases', {}).get('enabled') is True)

            cache_key = None
            if "tmdb_id" in current_info and current_info["tmdb_id"]:
                tmdb_id = current_info["tmdb_id"]
                media_type = current_info["media_type"]
                if wrapped_log:
                    wrapped_log(f"🎯 使用映射规则指定的 TMDB ID: {tmdb_id} ({media_type})", LOG_SUCCESS)
                tmdb_result = {"id": tmdb_id}
                candidate_count = 0
            else:
                # 文件夹级 TMDB 缓存
                folder_key = str(src.parent.resolve())
                cache_key = (tmdb_scope(src.parent,config),search_title,media_type,search_year,tuple(alt_titles),duration_hint)
                from .candidate_evaluator import evaluate_candidates
                with _folder_tmdb_cache_lock:
                    cached = _folder_tmdb_cache.get(cache_key)
                    cached_item = cached.get("candidate") if isinstance(cached, dict) else None
                    cached_type = cached.get("media_type") if isinstance(cached, dict) else None
                    cached_count = cached.get("candidate_count") if isinstance(cached, dict) else None
                    validated = (cached_type == media_type and isinstance(cached_item, dict)
                                 and cached.get("validation_stage") == "details_verified"
                                 and cached.get("rule_version") == parse_identity.RULE_VERSION
                                 and cached.get("ambiguity") == "resolved" and bool(cached.get("evidence"))
                                 and type(cached_count) is int and cached_count >= 1
                                 and evaluate_candidates([cached_item], cached_type,
                                     [search_title, title_orig, *alt_titles], search_year)['selected'])
                    cached_tmdb_id = cached_item.get('id') if validated else None

                if cached_tmdb_id:
                    tmdb_result = dict(cached_item)
                    media_type = cached_type
                    candidate_count = cached_count
                    if wrapped_log:
                        wrapped_log(f"📦 命中文件夹TMDB缓存: ID {cached_tmdb_id}", LOG_INFO)
                else:
                    tmdb_result, media_type, candidate_count = search_tmdb_with_fallback(
                        media_type, search_title, search_year, alt_titles, config, wrapped_log,
                        src=src, duration_hint=duration_hint, title_for_attempts=title_orig,
                        base_confidence=confidence
                    )
                if not tmdb_result:
                    return (False, None, None, None, None, None, confidence, current_info)

                if candidate_count > 1:
                    confidence -= 5
                    if wrapped_log:
                        wrapped_log(f"⚠️ 搜索返回 {candidate_count} 个候选结果，匹配评分降低 5 分", LOG_WARNING)

            tmdb_id = tmdb_result["id"]
            if tmdb_result.get('_verified_detail_alias') is True:
                current_info = dict(current_info, _verified_detail_alias=True)
            api_key = config["tmdb_api"]["api_key"]
            language = config["tmdb_api"].get("language", "zh-CN")
            proxy = config.get("tmdb_api", {}).get("proxy")
            details = tmdb_client.get_tmdb_details(
                media_type=media_type, tmdb_id=tmdb_id, api_key=api_key,
                language=language, log_func=wrapped_log, include_alternative_titles=True, proxy=proxy
            )
            if not details:
                return (False, None, None, None, None, None, confidence, current_info)
            if current_info.get("_explicit_identity") or current_info.get('_verified_detail_alias'):
                type_name = "title" if media_type == "movie" else "name"
                if (not isinstance(details, dict) or type(details.get("id")) is not int
                        or details['id'] != tmdb_id or not isinstance(details.get(type_name), str)
                        or not details[type_name].strip()):
                    return (False, None, None, None, None, None, confidence, current_info)
            if current_info.get('_verified_detail_alias'):
                from .candidate_evaluator import evaluate_candidates
                date_key = 'release_date' if media_type == 'movie' else 'first_air_date'
                old_date, new_date = tmdb_result.get(date_key), details.get(date_key)
                date_conflict = (isinstance(old_date, str) and isinstance(new_date, str)
                                 and old_date[:4].isdigit() and new_date[:4].isdigit()
                                 and old_date[:4] != new_date[:4])
                if date_conflict or not evaluate_candidates([details], media_type,
                        [search_title, title_orig, *alt_titles], search_year, include_alternatives=True)['selected']:
                    return (False, None, None, None, None, None, confidence, current_info)
                # An alternative title often names one season of a long series ("Maria Holic Alive",
                # "Golden Wind"); without a season in the name the parser's default season 1 is a guess.
                # A stated season is trusted as for a main-title match, unless the title itself marks a
                # later part ("Act II S2" counts from Act II, not TMDB's numbering).
                if media_type == 'tv':
                    from .parser_regex import explicit_season_number
                    regular = {item.get('season_number') for item in details.get('seasons') or []
                               if isinstance(item, dict) and type(item.get('season_number')) is int and item['season_number'] > 0}
                    stated = explicit_season_number(src.stem)
                    if stated is None:
                        stated = explicit_season_number(src.parent.name)
                    sequel_marked = any(isinstance(text, str) and _SEQUEL_MARK.search(text) for text in (search_title, title_orig))
                    if len(regular) > 1 and (stated is None or sequel_marked):
                        reason = '仅凭 TMDB 备用标题匹配到多季作品，备用标题可能只指其中一季，需要人工确认季号'
                        if wrapped_log:
                            wrapped_log(f"⚠️ {reason}", LOG_WARNING)
                        return (False, None, None, None, None, None, confidence,
                                dict(current_info, _alias_season_review=reason))

            if media_type == "movie":
                official_title = details.get("title")
            else:
                official_title = details.get("name") or details.get("original_name")
            if not official_title:
                official_title = title_orig
                if wrapped_log:
                    wrapped_log(f"⚠️ TMDB 无标题，使用解析标题: {title_orig}", LOG_WARNING)
            official_title = official_title.strip() if official_title else title_orig

            release_date = details.get("release_date" if media_type == "movie" else "first_air_date") or ""
            official_year = release_date[:4] if release_date else search_year or ""

            # A movie's duration is compared only with its own TMDB runtime.
            # TV runtime is evaluated later against the matched episode.
            from .duration_evidence import compare_duration
            duration_evidence = compare_duration(local_duration, details.get("runtime") if media_type == "movie" else None)
            if (media_type == "movie" and duration_evidence['status'] != 'unknown'
                    and local_duration < 40 and duration_evidence['status'] != 'conflict'):
                reason = "短时长电影需要人工确认"
                if wrapped_log:
                    wrapped_log(f"⚠️ {reason}", LOG_WARNING)
                return (False, None, None, None, None, None, confidence,
                        dict(current_info, _duration_conflict=reason))
            if duration_evidence['status'] == 'conflict':
                reason = (f"影片时长与 TMDB 差异 {duration_evidence['difference']:.1f} 分钟，"
                          f"超过容差 {duration_evidence['tolerance']:.1f} 分钟，需要人工确认")
                if wrapped_log:
                    wrapped_log(f"⚠️ {reason}", LOG_WARNING)
                return (False, None, None, None, None, None, confidence,
                        dict(current_info, _duration_conflict=reason))

            # Cache only an independently validated decision with matching details.
            if (cache_key is not None and not is_preview()
                    and type(tmdb_id) is int and tmdb_id > 0
                    and isinstance(details, dict) and details.get("id") == tmdb_id
                    and type(candidate_count) is int and candidate_count >= 1):
                assessment = evaluate_candidates([tmdb_result], media_type,
                    [search_title, title_orig, *alt_titles], search_year)
                if assessment['selected']:
                    evidence = assessment['candidates'][0]['evidence']
                    with _folder_tmdb_cache_lock:
                        _folder_tmdb_cache[cache_key] = {
                            "id": tmdb_id, "media_type": media_type,
                            "candidate": dict(tmdb_result), "candidate_count": candidate_count,
                            "rule_version": parse_identity.RULE_VERSION, "evidence": list(evidence),
                            "ambiguity": "resolved", "validation_stage": "details_verified"}
            score_evidence = []
            parser_name = current_info.get("_parser")
            if parser_name:
                score_evidence.append(f"解析来源：{parser_name}")
            if force_tmdb_id is not None:
                score_evidence.append("人工映射指定 TMDB 身份")
            elif current_info.get("_user_rule_id"):
                score_evidence.append("已保存的人工规则指定 TMDB 身份")
            elif current_info.get("_explicit_identity"):
                score_evidence.append("源路径或关联 NFO 中明确指定 TMDB ID")
            elif current_info.get('_verified_detail_alias'):
                score_evidence.append('候选标题或已核验备用标题与输入一致')
            else:
                from .candidate_evaluator import evaluate_candidates
                assessment = evaluate_candidates([tmdb_result], media_type,
                    [search_title, title_orig, *alt_titles], search_year)
                if assessment['selected']:
                    score_evidence.append("候选标题与输入一致")
            score_evidence.append("已获取 TMDB 详情")
            if duration_evidence['status'] == 'supported':
                score_evidence.append("影片时长与 TMDB 在容差内")
            score_conflicts = (["搜索存在多个候选，评分已降低"] if candidate_count > 1 else [])
            if user_rule and user_rule.get("_lower_priority_conflict"):
                score_conflicts.append(user_rule["_lower_priority_conflict"])
            current_info = dict(current_info, _local_video_duration=local_duration, _recognition_score={
                "origin": "manual_mapping" if force_tmdb_id is not None or current_info.get("_user_rule_id") else "automatic",
                "evidence": score_evidence, "conflicts": score_conflicts})
            return (True, details, media_type, tmdb_id, official_title, official_year, confidence, current_info)

        initial_confidence = compute_confidence(info, force_tmdb_id is not None)
        if info.get("_from_folder_ai_batch"):
            initial_confidence = max(initial_confidence, 85)
        success, details, media_type, tmdb_id, official_title, official_year, confidence, final_info = try_process_with_info(info, initial_confidence)

        if not success and final_info.get('_alias_season_review'):
            save_failed_cache(src, final_info['_alias_season_review'], cache_dict, wrapped_log)
            return False
        if not success and final_info.get('_verified_detail_alias'):
            save_failed_cache(src, 'TMDB 详情或别名证据发生变化，需要人工确认', cache_dict, wrapped_log)
            return False
        if not success and final_info.get('_explicit_identity'):
            save_failed_cache(src, "明确 TMDB ID 的详情无法验证，需要人工确认", cache_dict, wrapped_log)
            return False
        if not success and final_info.get('_duration_conflict'):
            save_failed_cache(src, final_info['_duration_conflict'], cache_dict, wrapped_log)
            return False

        # 强制 AI 解析
        force_ai_due_to_season = False
        if not success and info.get("_parser") == "anitopy" and info.get("season") == 1:
            combined_text = f"{src.name} {src.parent.name}".lower()
            if any(ind in combined_text for ind in SEASON_INDICATORS):
                force_ai_due_to_season = True
                if wrapped_log:
                    wrapped_log(f"⚠️ 检测到季号标识但 anitopy 解析为 S01，强制使用 AI 解析", LOG_WARNING)

        if (force_ai_due_to_season or (not success and info.get("_parser") == "anitopy")) and config.get("ai_parser", {}).get("enabled"):
            if not force_ai_due_to_season:
                if wrapped_log:
                    wrapped_log(f"⚠️ anitopy 解析后 TMDB 搜索失败，尝试使用 AI 重新解析...", LOG_WARNING)
            ai_info = ai_client.parse_filename_with_ai(src, config, wrapped_log)
            if ai_info.get("media_type") in ("movie", "tv"):
                ai_info["_from_ai"] = True
                success, details, media_type, tmdb_id, official_title, official_year, confidence, final_info = try_process_with_info(
                    ai_info, 80
                )
                if success:
                    info = ai_info
                    if wrapped_log:
                        wrapped_log(f"✅ AI 解析成功，继续处理", LOG_SUCCESS)

        if not success:
            save_failed_cache(src, final_info.get('_duration_conflict') or "TMDB 搜索无结果或详情获取失败", cache_dict, wrapped_log)
            return False

        if wrapped_log:
            if media_type == "movie":
                wrapped_log(f"🎬 识别为电影: {official_title} ({official_year or '未知'})", LOG_SUCCESS)
            else:
                wrapped_log(f"📺 识别为剧集: {official_title} S{final_info['season']:02d}E{final_info['episode']:02d}", LOG_SUCCESS)

        branch_config = dict(config, _recognition_score=final_info['_recognition_score'],
                             _local_video_duration=final_info.get('_local_video_duration'))
        if media_type == "movie":
            return process_movie_branch(src, branch_config, cache_dict, wrapped_log, official_title, official_year, tmdb_id, details, confidence)
        else:
            return process_tv_branch(src, branch_config, cache_dict, wrapped_log, official_title, official_year, tmdb_id, details, final_info, confidence)

    except AIBudgetExceeded:
        save_failed_cache(src, "AI 调用预算已耗尽，需要人工确认", cache_dict, wrapped_log)
        if config.get("dry_run") and wrapped_log:
            wrapped_log("AI 调用预算已耗尽，需要人工确认", LOG_WARNING)
        return False
    except ProcessingCancelled:
        raise

    except CacheCorruptionError:
        raise
    except Exception as e:
        note_error(e)
        logger.error(f"process_video 顶层异常 {src}: {e}", exc_info=True)
        save_failed_cache(src, f"未知异常: {e}", cache_dict, wrapped_log)
        return False
