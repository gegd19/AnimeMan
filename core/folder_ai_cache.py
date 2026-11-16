"""Content/config/rule-bound folder results with lossless per-file overrides."""
from copy import deepcopy
from pathlib import Path
import threading
import time
from . import parse_identity
from .parse_contract import normalize_folder
from .parse_cache import update_record
from .json_store import read_json,write_json
from .runtime_paths import cache_file
from .execution_mode import skip_preview_write

CACHE_FILE='folder_ai_parse_cache.json'
DEFAULT_CACHE_TTL_DAYS=90
_cache_lock=threading.RLock()


def _get_folder_fingerprint(folder_path,video_extensions):
    return parse_identity.folder_identity(folder_path,{'video_extensions':video_extensions})


def load_folder_cache():
    with _cache_lock:return read_json(cache_file(CACHE_FILE))


@skip_preview_write
def save_folder_cache(cache):
    with _cache_lock:write_json(cache_file(CACHE_FILE),cache)


def get_cached_folder_parse(folder_path,config,ttl_days=DEFAULT_CACHE_TTL_DAYS):
    identity,files=parse_identity.folder_snapshot(folder_path,config)
    entry=load_folder_cache().get(str(Path(folder_path).resolve()),{})
    if not isinstance(entry,dict) or entry.get('_schema')!=parse_identity.RULE_VERSION or entry.get('identity')!=identity:return None
    updated=entry.get('updated')
    if type(updated) not in (int,float) or time.time()-updated>ttl_days*86400:return None
    result=normalize_folder(_parse_folder_result(entry.get('parse_result')),folder_path,files)
    return result or None


@skip_preview_write
def save_folder_parse_result(folder_path,parse_result,config):
    identity,files=parse_identity.folder_snapshot(folder_path,config)
    result=normalize_folder(parse_result,folder_path,files)
    if not result:return False
    entry={'_schema':parse_identity.RULE_VERSION,'identity':identity,'parse_result':_compress_folder_parse_result(result),'updated':time.time()}
    with _cache_lock:update_record(cache_file(CACHE_FILE),str(Path(folder_path).resolve()),entry)
    return True


def _compress_folder_parse_result(raw):
    if not isinstance(raw,dict):return {}
    defaults={'media_type':raw.get('media_type'),'title':raw.get('folder_title'),'season':raw.get('season'),'year':raw.get('year')}
    result=deepcopy(raw);result['_format']=2
    result['files']={name:{key:deepcopy(value) for key,value in info.items() if key not in defaults or value!=defaults[key]}
                     for name,info in raw.get('files',{}).items()}
    return result


def _decompress_folder_parse_result(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('files'),dict):return {}
    if any(not isinstance(info,dict) for info in raw['files'].values()):return {}
    defaults={'media_type':raw.get('media_type'),'title':raw.get('folder_title'),'season':raw.get('season'),'year':raw.get('year')}
    result=deepcopy(raw);result.pop('_format',None)
    result['files']={name:dict(deepcopy(defaults),**deepcopy(info)) for name,info in raw.get('files',{}).items()}
    return result


def _parse_folder_result(raw):
    if not isinstance(raw,dict):return {}
    return _decompress_folder_parse_result(raw) if raw.get('_format')==2 else raw
