#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validated parser fallbacks and a shared folder request/result per task."""
from copy import deepcopy,copy
from dataclasses import dataclass,field
from pathlib import Path
import re
import threading

from .ai_budget import AIBudgetExceeded, with_recognition_budget
from . import ai_client,cache_manager,folder_ai_cache,parse_identity
from .cancellation import check_cancelled,wait_for,ProcessingCancelled
from .execution_mode import skip_preview_write
from .json_store import CacheCorruptionError
from .parse_cache import update_record
from .parse_contract import normalize_media,normalize_folder,file_id
from .parser_helpers import get_ai_parse_cache_key, clean_parent_dir_name
from .parser_anitopy import parse_with_anitopy,ANITOPY_AVAILABLE,has_ambiguous_roman_episode
from .parser_regex import parse_with_regex, explicit_season_number
from .runtime_paths import cache_file

AI_CACHE={}
_ai_parse_persistent_cache={}
_persistent_cache_path=None
_persistent_signature=None
ai_parse_cache_lock=cache_manager.ai_parse_cache_lock
_ongoing_folder_parses={}
_ongoing_lock=threading.RLock()


@dataclass
class FolderFlight:
    event: object=field(default_factory=threading.Event)
    result: object=None
    error: object=None


def _ensure_persistent_cache():
    global _ai_parse_persistent_cache,_persistent_cache_path,_persistent_signature
    with ai_parse_cache_lock:
        path=cache_file(cache_manager.AI_PARSE_CACHE_FILE)
        stat=path.stat() if path.exists() else None
        signature=(stat.st_mtime_ns,stat.st_size,stat.st_ino) if stat else None
        if path!=_persistent_cache_path or signature!=_persistent_signature:
            _ai_parse_persistent_cache=cache_manager.load_ai_parse_cache()
            AI_CACHE.clear();_persistent_cache_path=path;_persistent_signature=signature


@skip_preview_write
def _save_parse_result(cache_key,result):
    global _persistent_signature
    validated=normalize_media(result,trusted=True)
    if not validated:return False
    with ai_parse_cache_lock:
        _ensure_persistent_cache()
        frame={'_schema':parse_identity.RULE_VERSION,'identity':cache_key,'result':validated}
        current=update_record(cache_file(cache_manager.AI_PARSE_CACHE_FILE),cache_key,frame)
        _ai_parse_persistent_cache.clear();_ai_parse_persistent_cache.update(current)
        AI_CACHE[cache_key]=deepcopy(frame)
        stat=cache_file(cache_manager.AI_PARSE_CACHE_FILE).stat()
        _persistent_signature=(stat.st_mtime_ns,stat.st_size,stat.st_ino)
    return True


def _cached_file_result(key):
    with ai_parse_cache_lock:
        frame=AI_CACHE.get(key,_ai_parse_persistent_cache.get(key))
        if not isinstance(frame,dict) or frame.get('_schema')!=parse_identity.RULE_VERSION or frame.get('identity')!=key:return None
        return normalize_media(frame.get('result'),trusted=True)


def _extract_file_info_from_offline_cache(file_path,parse_result,log_func=None):
    if not isinstance(parse_result,dict) or not isinstance(parse_result.get('files'),dict):return None
    return normalize_media(parse_result['files'].get(Path(file_path).name))


@parse_identity.with_identity_scope
@with_recognition_budget
def _get_or_wait_folder_parse(folder_path,config,log_func=None,tmdb_structure=''):
    check_cancelled()
    folder_path=Path(folder_path);config=deepcopy(config)
    if tmdb_structure:
        config['parse_context']=dict(config.get('parse_context',{}),tmdb_structure=tmdb_structure)
    legacy_key=str(folder_path.resolve())
    key=(str(cache_file(folder_ai_cache.CACHE_FILE)),legacy_key,parse_identity.policy_key(config),tmdb_structure)
    memo=parse_identity.current_memo()
    with _ongoing_lock:
        # Compatibility with a previously registered Event; never remove its owner.
        legacy=_ongoing_folder_parses.get(legacy_key)
        if legacy is not None:
            flight=None;owner=False
        elif key in memo.completed:
            completed=memo.completed[key]
            if completed.error:raise copy(completed.error)
            return deepcopy(completed.result)
        else:
            flight=_ongoing_folder_parses.get(key)
            owner=flight is None
            if owner:
                flight=FolderFlight();_ongoing_folder_parses[key]=flight
    if legacy is not None:
        return folder_ai_cache.get_cached_folder_parse(folder_path,config) if wait_for(legacy,60) else None
    if not owner:
        timeout=config.get('ai_parser',{}).get('folder_wait_timeout',60)
        if not wait_for(flight.event,timeout):
            if log_func:log_func('等待文件夹解析超时，交给本地回退；未启动重复请求','warning')
            return None
        if flight.error:raise copy(flight.error)
        return deepcopy(flight.result)
    try:
        result=folder_ai_cache.get_cached_folder_parse(folder_path,config)
        if result is None:
            _,files=parse_identity.folder_snapshot(folder_path,config)
            result=normalize_folder(ai_client.parse_folder_with_ai(folder_path,files,config,log_func,tmdb_structure=tmdb_structure),folder_path,files)
            if result:
                parse_identity.assert_snapshot_current(folder_path,config)
                folder_ai_cache.save_folder_parse_result(folder_path,result,config)
        flight.result=result or None
        return deepcopy(flight.result)
    except BaseException as exc:
        flight.error=exc
        raise
    finally:
        with _ongoing_lock:
            memo.completed[key]=flight
            flight.event.set()
            if _ongoing_folder_parses.get(key) is flight:del _ongoing_folder_parses[key]


def _tag(raw,source):
    result=normalize_media(raw,trusted=True)
    if result:
        result['_parser']=source
        if source in {'ai_file','ai_folder','offline_ai'}:result['_from_ai']=True
    return result


@parse_identity.with_identity_scope
@with_recognition_budget
def parse_filename(file_path,config,log_func=None):
    from .offline_ai_preparser import get_cached_preparse,parse_folder_on_demand,load_raw_cache
    _ensure_persistent_cache();check_cancelled()
    file_path=Path(file_path);folder=file_path.parent
    # Decimal and range episode tokens need explicit mapping; never truncate them.
    # A decimal episode has a standalone fractional token of any length (12.5, [12.5], E07.5, 12.5v2);
    # dot-separated scene names such as "S04E03.1080p" or "E01.4K" are a resolution, not episode 3.1080.
    stem=file_path.stem
    ambiguous=(re.search(r'(?i)(?:\s-\s*|\[|第\s*|(?<![a-z])e(?:p)?\s*)\d{1,3}\.\d+(?!\d|[a-uw-z])',stem)
               or re.search(r'(?i)(?:\s-\s*|\[|(?<![a-z])e(?:p)?\s*)\d{1,3}\s*[-~–]\s*(?:e(?:p)?\s*)?\d{1,3}(?!\d)',stem))
    if ambiguous:
        return {'media_type':'unknown','reason_code':'unsupported_episode_numbering'}
    key=get_ai_parse_cache_key(str(file_path),config)
    enabled=config.get('ai_parser',{}).get('enabled',False)
    evidence=config.get('_folder_evidence')
    shared_allowed = not evidence or (evidence.get('complete') and evidence.get('identity_status') != 'conflict' and not evidence.get('unknown'))
    resolved_folder=folder.resolve()
    roots=[Path(root).resolve() for root in config.get('source_folders',[]) if isinstance(root,str) and root.strip()]
    matching=[root for root in roots if resolved_folder == root or root in resolved_folder.parents]
    root=max(matching,key=lambda path:len(path.parts)) if matching else None
    ancestors=[]
    current=resolved_folder
    if root is not None:
        for _ in range(4):
            ancestors.append(current)
            if current==root:break
            current=current.parent
    file_season=explicit_season_number(stem)
    dir_seasons=[value for value in (explicit_season_number(path.name) for path in ancestors) if value is not None]
    if file_season is not None and any(value != file_season for value in dir_seasons):
        return {'media_type':'unknown','reason_code':'conflicting_season_evidence'}
    if has_ambiguous_roman_episode(stem) and file_season is None and not dir_seasons:
        if config.get('anime_parser',{}).get('enabled') and ANITOPY_AVAILABLE:
            partial=parse_with_anitopy(file_path.name,folder.name,log_func)
        else:
            partial=parse_with_regex(file_path.name,folder.name)
        return dict(partial, season=None, explicit_season=None, reason_code='ambiguous_roman_season')
    if re.fullmatch(r'\d+',stem):
        generic=re.compile(r'(?i)^(?:season\s*\d+|s\d+|第\s*[零一二两三四五六七八九十\d]+\s*季|bdrip|bluray|web-?dl|library|media)$')
        title=next((clean_parent_dir_name(path.name) for path in ancestors
                    if not generic.fullmatch(path.name.strip())
                    and clean_parent_dir_name(path.name).strip()),None)
        if not title:
            return {'media_type':'unknown','reason_code':'missing_series_title'}
        if len(set(dir_seasons))>1:
            return {'media_type':'unknown','reason_code':'conflicting_season_evidence'}
        season=dir_seasons[0] if dir_seasons else 1
        info=_tag({'media_type':'tv','title':title,'season':season,'episode':int(stem),
                   'explicit_season':season},'anitopy')
        if info:
            parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
        return {'media_type':'unknown'}
    # An explicit Chinese season and episode are stronger than a partial movie parse.
    if ((re.search(r'第\s*[零一二两三四五六七八九十\d]+\s*季', file_path.stem)
             or (file_season is not None and re.search(r'(?:全剧|累计|总计)\s*第', file_path.stem)))
            and re.search(r'第\s*\d{1,4}\s*[集話话](?!\d)', file_path.stem)):
        info=_tag(parse_with_regex(file_path.name,folder.name),'regex')
        if info:
            parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
    if enabled and shared_allowed:
        for source,result in [('offline_ai',get_cached_preparse(folder,config)),
                              ('ai_folder',folder_ai_cache.get_cached_folder_parse(folder,config))]:
            info=_extract_file_info_from_offline_cache(file_path,result)
            if info:
                info=_tag(info,source);parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
    cached=_cached_file_result(key)
    if cached:return cached
    # Evaluate local evidence before scheduling any new AI request.
    anime=None
    local_info=None
    if config.get('anime_parser',{}).get('enabled') and ANITOPY_AVAILABLE:
        anime=parse_with_anitopy(file_path.name,folder.name,log_func)
        local_info=_tag(anime,'anitopy')
        if (local_info and anime.get('_anitopy_success')
                and local_info.get('media_type') == 'tv'):
            parse_identity.assert_file_current(file_path);_save_parse_result(key,local_info);return local_info
    else:
        local_info=_tag(parse_with_regex(file_path.name,folder.name),'regex')
        if local_info and local_info.get('media_type') == 'tv':
            parse_identity.assert_file_current(file_path);_save_parse_result(key,local_info);return local_info
    if enabled and shared_allowed and config.get('ai_parser',{}).get('batch_folder_enabled',True):
        _,files=parse_identity.folder_snapshot(folder,config)
        if len(files)>=2:
            try:batch=_get_or_wait_folder_parse(folder,config,log_func)
            except (AIBudgetExceeded,ProcessingCancelled,CacheCorruptionError,OSError):raise
            except Exception as exc:
                if log_func:log_func(f'文件夹解析异常，交给回退：{exc}','warning')
                batch=None
            info=_extract_file_info_from_offline_cache(file_path,batch)
            if info:
                info=_tag(info,'ai_folder');parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
    if (not enabled and local_info and anime is not None and anime.get('_anitopy_success')):
        parse_identity.assert_file_current(file_path);_save_parse_result(key,local_info);return local_info
    if (not enabled and anime is not None
            and not config.get('anime_parser',{}).get('fallback_to_regex',True)):
        return {'media_type':'unknown'}
    if enabled and shared_allowed and str(folder.resolve()) in load_raw_cache():
        result=parse_folder_on_demand(folder,config,log_func=log_func)
        info=_extract_file_info_from_offline_cache(file_path,result)
        if info:
            info=_tag(info,'offline_ai');parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
    if enabled:
        info=_tag(ai_client.parse_filename_with_ai(file_path,config,log_func,anitopy_hint=anime),'ai_file')
        if info:
            parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
    if local_info:
        parse_identity.assert_file_current(file_path);_save_parse_result(key,local_info);return local_info
    result=parse_with_regex(file_path.name,folder.name)
    info=_tag(result,'regex')
    if info:parse_identity.assert_file_current(file_path);_save_parse_result(key,info);return info
    return result
