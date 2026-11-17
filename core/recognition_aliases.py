"""Typed aliases with explicit provenance; legacy mappings remain read-only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .json_store import read_json, update_json
from .runtime_paths import cache_file

SCHEMA = 1
ALIASES_FILE = 'recognition_aliases_v1.json'
LEGACY_FILE = 'tmdb_aliases.json'
TRUSTED_SOURCES = frozenset({'manual', 'tmdb', 'nfo'})
SOURCES = TRUSTED_SOURCES | {'ai'}


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split()) if isinstance(value, str) else ''


def _validated(record):
    if not isinstance(record, dict):
        raise ValueError('别名记录格式无效')
    name, kind, ident, source = (record.get(key) for key in ('name','media_type','tmdb_id','source'))
    year, scope = record.get('year'), record.get('scope')
    if not isinstance(name,str) or not normalize(name) or len(name)>256:
        raise ValueError('别名无效')
    if kind not in ('tv','movie') or type(ident) is not int or not 1 <= ident <= 2147483647 or source not in SOURCES:
        raise ValueError('别名身份或来源无效')
    if year is not None and (not isinstance(year,str) or not re.fullmatch(r'(?:18|19|20|21)\d{2}',year)):
        raise ValueError('别名年份无效')
    if scope is not None and (not isinstance(scope,str) or not Path(scope).is_absolute() or str(Path(scope)) != scope or Path(scope).resolve() != Path(scope)):
        raise ValueError('别名作用域必须是规范绝对目录')
    return {'name':name.strip(), 'media_type':kind, 'tmdb_id':ident, 'source':source, 'year':year, 'scope':scope}


def _load():
    path=cache_file(ALIASES_FILE)
    if path.is_symlink():
        raise ValueError('别名文件不能是符号链接')
    if not path.exists():
        return {'schema':SCHEMA, 'records':[]}
    state=read_json(path)
    if type(state.get('schema')) is not int or state['schema'] != SCHEMA or not isinstance(state.get('records'), list):
        raise ValueError('别名存储格式无效或版本不受支持，原文件已保留')
    return {'schema':SCHEMA, 'records':[_validated(record) for record in state['records']]}


def _legacy():
    path=cache_file(LEGACY_FILE)
    if path.is_symlink():raise ValueError('旧别名文件不能是符号链接')
    data=read_json(path)
    records=[]
    for name, value in data.items():
        if not isinstance(name,str) or not normalize(name) or not isinstance(value,dict):continue
        ident=value.get('tmdb_id')
        kind=value.get('media_type')
        if type(ident) is not int or ident <= 0 or kind not in ('tv','movie'):continue
        records.append({'name':name,'tmdb_id':ident,'media_type':kind,'source':'legacy',
                        'year':value.get('year'), 'scope':None, 'trusted':False})
    return records


def revision(*, include_new=True):
    paths=([cache_file(ALIASES_FILE)] if include_new else []) + [cache_file(LEGACY_FILE)]
    raw=[]
    for path in paths:
        if path.is_symlink():raise ValueError('别名文件不能是符号链接')
        raw.append(path.read_bytes().hex() if path.exists() else None)
    return hashlib.sha256(json.dumps([SCHEMA,raw],ensure_ascii=False).encode()).hexdigest()


def add_aliases(records):
    """Validate the complete explicit batch before making one atomic write."""
    if not isinstance(records,list) or not 1 <= len(records) <= 50:
        raise ValueError('别名批次数量无效')
    checked=[_validated(record) for record in records]
    def mutate(data):
        state=_load()
        for record in checked:
            if record not in state['records']:
                state['records'].append(record)
        data.clear();data.update(state)
    update_json(cache_file(ALIASES_FILE),mutate)
    return deepcopy(checked)


def add_alias(name, media_type, tmdb_id, source, *, year=None, scope=None):
    return add_aliases([{'name':name,'media_type':media_type,'tmdb_id':tmdb_id,
                         'source':source,'year':year,'scope':scope}])[0]


def stored_aliases():
    return deepcopy(_load()['records'])


def manual_aliases():
    return deepcopy([record for record in _load()['records'] if record['source']=='manual'])


def remove_manual_alias(record):
    record=_validated(record)
    if record['source']!='manual' or not record['scope']:
        raise ValueError('只能删除指定范围的人工别名')
    def mutate(data):
        state=_load()
        if record not in state['records']:raise ValueError('人工别名不存在或已变化')
        state['records'].remove(record)
        data.clear();data.update(state)
    update_json(cache_file(ALIASES_FILE),mutate)


def all_aliases(*, src=None):
    source_path=Path(src).resolve() if src is not None else None
    records=[]
    for record in _load()['records']:
        scope=record['scope']
        if scope and (source_path is None or Path(scope).resolve() not in source_path.parents):continue
        records.append(dict(record, trusted=record['source'] in TRUSTED_SOURCES))
    return records+_legacy()


def find_aliases(name, *, src=None):
    key=normalize(name)
    return [record for record in all_aliases(src=src) if key and normalize(record['name']) == key]
