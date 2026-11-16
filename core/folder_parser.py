"""Optional folder metadata with the same output contract and cache identity."""
from pathlib import Path
import json
import time
from .ai_budget import with_recognition_budget
from . import ai_client,parse_identity
from .parse_contract import normalize_header
from .parse_cache import update_record
from .json_store import read_json,write_json
from .runtime_paths import cache_file
from .execution_mode import skip_preview_write

FOLDER_CACHE_FILE='folder_ai_cache.json'


def load_folder_cache():return read_json(cache_file(FOLDER_CACHE_FILE))


@skip_preview_write
def save_folder_cache(cache):write_json(cache_file(FOLDER_CACHE_FILE),cache)


@with_recognition_budget
def parse_folder_with_ai(folder_path,config,log_func=None):
    files=parse_identity.folder_files(folder_path,config)
    if not files or not config.get('ai_parser',{}).get('enabled'):return None
    prompt='返回 JSON 对象：media_type(tv/movie)、title、season、year、alternative_titles；未知季号用 null，不猜第一集。\n'
    prompt+=json.dumps({'folder':Path(folder_path).name,'files':[f.relative_to(folder_path).as_posix() for f in files]},ensure_ascii=False)
    raw=ai_client.call_ai_api(prompt,config['ai_parser'],log_func)
    return normalize_header(ai_client._parse_ai_json_response(raw,log_func))


@parse_identity.with_identity_scope
@with_recognition_budget
def get_folder_meta(folder_path,config,log_func=None):
    folder_path=Path(folder_path);identity=parse_identity.folder_identity(folder_path,config)
    entry=load_folder_cache().get(str(folder_path.resolve()),{})
    if isinstance(entry,dict) and entry.get('_schema')==parse_identity.RULE_VERSION and entry.get('identity')==identity:
        result=normalize_header(entry.get('parse_result'))
        if result:return result
    if not config.get('ai_parser',{}).get('enabled'):return None
    result=normalize_header(parse_folder_with_ai(folder_path,config,log_func))
    if result:
        parse_identity.assert_snapshot_current(folder_path,config)
        update_record(cache_file(FOLDER_CACHE_FILE),str(folder_path.resolve()),{
            '_schema':parse_identity.RULE_VERSION,'identity':identity,'parse_result':result,'updated':time.time()})
    return result
