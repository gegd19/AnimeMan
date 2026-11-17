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

from .ai_budget import AIBudgetExceeded, with_recognition_budget
from .log_redaction import redact
from .json_store import CacheCorruptionError
from .cancellation import ProcessingCancelled
from .parse_identity import tmdb_scope
import re
import json
import threading
from pathlib import Path
from .execution_mode import is_preview
from .runtime_paths import cache_file
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
_alias_path = None


def _load_aliases() -> Dict[str, Dict]:
    # Compatibility view of the legacy file; re-read so edits take effect.
    from .json_store import read_json
    path = cache_file(ALIAS_FILE.name)
    if path.is_symlink():
        raise ValueError('旧别名文件不能是符号链接')
    return {k.lower(): v for k, v in read_json(path).items() if isinstance(k,str)}


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

    from .candidate_evaluator import evaluate_candidates
    from .failure_policy import note_error
    if media_type not in ("tv", "movie"):
        return None, media_type, 0
    attempts = [(media_type, search_title, search_year)]
    attempts.extend((media_type, alt, search_year) for alt in alt_titles)
    for mtype, query, year in attempts:
        try:
            result = tmdb_client.search_tmdb(mtype, query, year, api_key, language, log_func, alt_titles, proxy=proxy)
            if result and evaluate_candidates([result], mtype, [search_title, *alt_titles], search_year)['selected']:
                return result, mtype, 1
        except (AIBudgetExceeded, CacheCorruptionError, ProcessingCancelled):
            raise
        except Exception as error:
            note_error(error)
            logger.warning(f"TMDB 搜索异常: {error}")

    return None, media_type, 0


@with_recognition_budget
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
        year = ((item.get("release_date") if item.get("media_type") == "movie" else item.get("first_air_date")) or "")[:4]
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
                status = parts[0].strip()
                corrected_title = parts[1].strip()
                if status == '不可信' and corrected_title and corrected_title != original_title:
                    if log_func:
                        log_func(f"🔧 AI 修正剧名: {original_title} → {corrected_title}", LOG_SUCCESS)
                    return corrected_title
    except CacheCorruptionError:
        raise
    except AIBudgetExceeded:
        raise
    except ProcessingCancelled:
        raise
    except Exception as e:
        logger.warning(f"AI 标题验证失败: {e}")
        if log_func:
            log_func(f"⚠️ AI 标题验证失败: {redact(e)}", LOG_WARNING)
    return None


@with_recognition_budget
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

    from .ai_selection import accepted_suggestion
    top_candidates = candidates[:10]
    if not top_candidates:
        return None
    choices = [{'id': item.get('id'), 'title': item.get('title') or item.get('name'),
                'date': (item.get('release_date') if media_type == 'movie' else item.get('first_air_date')) or ''}
               for item in top_candidates]
    prompt = (f"从候选中选择匹配 {search_title} 的 {media_type}；无法判断时 selected_id 为 null。"
              f"候选：{json.dumps(choices, ensure_ascii=False)}\n"
              '仅返回 JSON：{"selected_id":整数或null,"media_type":"tv或movie","reason":"简短说明"}')
    try:
        response = ai_client.call_ai_api(prompt, ai_cfg, log_func)
        return accepted_suggestion(response, top_candidates, media_type, [search_title])
    except (AIBudgetExceeded, CacheCorruptionError, ProcessingCancelled):
        raise
    except Exception as error:
        logger.warning(f"AI 辅助选择失败: {error}")
        if log_func:
            log_func("AI 候选建议不可用，需要人工确认", LOG_WARNING)
        return None


@with_recognition_budget
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
    from .candidate_evaluator import evaluate_candidates
    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")
    try:
        from . import search_enhancer
    except ImportError:
        return original_search_tmdb(media_type, search_title, search_year, alt_titles, config, log_func, duration_hint)

    from . import recognition_aliases
    records = recognition_aliases.all_aliases(src=src)
    requested = {recognition_aliases.normalize(value) for value in [search_title, title_for_attempts, *alt_titles]
                 if recognition_aliases.normalize(value)}
    relevant = [r for r in records if r['trusted'] and recognition_aliases.normalize(r['name']) in requested
                and (media_type not in ('tv','movie') or r['media_type'] == media_type)
                and (not search_year or not r['year'] or r['year'] == str(search_year))]
    identities = list(dict.fromkeys((r['media_type'],r['tmdb_id']) for r in relevant))
    if len(identities) > 4:
        if log_func: log_func('别名关联作品过多，需要人工确认', LOG_WARNING)
        return None, media_type, 0
    trusted_names = {}
    for kind, ident in identities:
        trusted_names[(kind,ident)] = [r['name'] for r in records if r['trusted'] and r['media_type'] == kind
                                       and r['tmdb_id'] == ident and (not search_year or not r['year'] or r['year'] == str(search_year))]
    legacy = (_lookup_local_alias(search_title), search_enhancer.lookup_local_alias(search_title))
    legacy_ids = [(a.get('media_type'),a.get('tmdb_id')) for a in legacy if isinstance(a,dict)
                  and a.get('media_type') in ('tv','movie') and type(a.get('tmdb_id')) is int and a['tmdb_id'] > 0
                  and (media_type not in ('tv','movie') or a.get('media_type') == media_type)]
    requested_ids = list(dict.fromkeys(identities + legacy_ids))[:4]
    alias_results = {}
    for kind, ident in requested_ids:
        details = tmdb_client.get_tmdb_details(kind, ident, api_key, language, log_func, proxy=proxy)
        if not isinstance(details,dict) or details.get('id') != ident or not isinstance(details.get('name' if kind == 'tv' else 'title'),str):
            continue
        date = details.get('first_air_date' if kind == 'tv' else 'release_date')
        actual_year = date[:4] if isinstance(date,str) else None
        declared = {r['year'] for r in relevant if r['media_type']==kind and r['tmdb_id']==ident and r['year']}
        if len(declared) > 1 or (actual_year and declared and actual_year not in declared):
            trusted_names.pop((kind,ident), None)
            continue
        alias_results[(kind,ident)] = details

    # Gather a bounded set of result pages before choosing; identical IDs are
    # deduplicated, while aliases from different languages remain evidence.
    from .candidate_evaluator import evaluate_candidates
    from .failure_policy import note_error
    queries, seen_queries = [], set()
    hint_ids = {(r['media_type'], r['tmdb_id']) for r in records if r['source'] == 'ai'
                and recognition_aliases.normalize(r['name']) in requested
                and (media_type not in ('tv','movie') or r['media_type'] == media_type)}
    hint_names = [r['name'] for r in records if r['trusted'] and (r['media_type'],r['tmdb_id']) in hint_ids]
    for value in [search_title, *alt_titles, title_for_attempts, *hint_names, *search_enhancer.generate_search_candidates(search_title)]:
        key = recognition_aliases.normalize(value)
        if key and key not in seen_queries:
            queries.append(value.strip()); seen_queries.add(key)
    queries = queries[:4]
    languages = list(dict.fromkeys([language, 'en-US']))
    titles = list(dict.fromkeys(value for value in [search_title, title_for_attempts, *alt_titles] if isinstance(value, str) and value.strip()))
    merged = dict(alias_results)
    types = [media_type] if media_type in ('tv', 'movie') else ['tv', 'movie']
    for result_type in types:
        for lang in languages:
            for query in queries:
                try:
                    items = tmdb_client.search_tmdb_multi(result_type, query, search_year, api_key, lang, log_func, proxy=proxy)
                except (AIBudgetExceeded, CacheCorruptionError, ProcessingCancelled):
                    raise
                except Exception as error:
                    note_error(error)
                    logger.warning(f"TMDB 搜索异常: {error}")
                    continue
                for item in items:
                    if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] <= 0:
                        continue
                    key = (result_type, item['id'])
                    if key not in merged:
                        merged[key] = dict(item)
                    else:
                        previous = merged[key]
                        for name in ('name', 'title', 'original_name', 'original_title'):
                            value = item.get(name)
                            if value and value not in [previous.get('name'), previous.get('title'), previous.get('original_name'), previous.get('original_title')]:
                                empty = next((k for k in ('original_name','original_title','name','title') if not previous.get(k)), None)
                                if empty:
                                    previous[empty] = value
    ranked = []
    for result_type in types:
        items = [item for (kind, _), item in merged.items() if kind == result_type]
        for item in items:
            identity = (result_type, item['id'])
            candidate_titles = titles + trusted_names.get(identity, [])
            decision = evaluate_candidates([item], result_type, candidate_titles, search_year)
            ranked.extend(entry for entry in decision['candidates'] if entry['reason'] is None)
    ranked.sort(key=lambda entry: -entry['score'])
    if ranked and (len(ranked) == 1 or ranked[0]['score'] - ranked[1]['score'] >= 10):
        return ranked[0]['item'], ranked[0]['media_type'], len(merged)
    # Corrected titles are search hints only; original evidence remains mandatory.
    if not ranked and merged and config.get('ai_parser', {}).get('enabled') and src is not None:
        import unicodedata
        def normalized(value):
            return unicodedata.normalize('NFKC', value).strip().casefold()
        current = search_title
        seen = {normalized(current)}
        for _ in range(2):
            corrected = ai_verify_and_correct_title(src, current, list(merged.values()), config, log_func)
            if not isinstance(corrected, str) or not corrected.strip():
                break
            corrected = corrected.strip()
            key = normalized(corrected)
            if key in seen:
                break
            seen.add(key)
            current = corrected
            for result_type in types:
                for lang in languages:
                    try:
                        items = tmdb_client.search_tmdb_multi(result_type, corrected, search_year, api_key, lang, log_func, proxy=proxy)
                    except (AIBudgetExceeded, CacheCorruptionError, ProcessingCancelled):
                        raise
                    except Exception as error:
                        note_error(error)
                        logger.warning(f"TMDB 搜索异常: {error}")
                        continue
                    for item in items:
                        if isinstance(item, dict) and type(item.get('id')) is int and item['id'] > 0:
                            merged.setdefault((result_type, item['id']), dict(item))
            ranked = []
            for result_type in types:
                items = [item for (kind, _), item in merged.items() if kind == result_type]
                for item in items:
                    identity = (result_type, item['id'])
                    decision = evaluate_candidates([item], result_type, titles + trusted_names.get(identity, []), search_year)
                    ranked.extend(entry for entry in decision['candidates'] if entry['reason'] is None)
            ranked.sort(key=lambda entry: -entry['score'])
            if ranked and (len(ranked) == 1 or ranked[0]['score'] - ranked[1]['score'] >= 10):
                return ranked[0]['item'], ranked[0]['media_type'], len(merged)
    if log_func and merged:
        log_func('TMDB 候选证据不足或存在歧义，需要人工确认', LOG_WARNING)

    # 5. TVmaze 备选
    if media_type == "tv" and config.get("ai_parser", {}).get("enabled"):
        tmdb_id = search_enhancer.search_tvmaze(search_title, config=config)
        if type(tmdb_id) is int and tmdb_id > 0:
            details = tmdb_client.get_tmdb_details("tv", tmdb_id, api_key, language, log_func, proxy=proxy)
            if (isinstance(details, dict) and details.get('id') == tmdb_id
                    and evaluate_candidates([details], 'tv', titles, search_year)['selected']):
                if log_func:
                    log_func(f"📺 TVmaze 备选通过标题验证: TMDB ID {tmdb_id}", LOG_SUCCESS)
                return details, "tv", 1

    return None, media_type, 0
