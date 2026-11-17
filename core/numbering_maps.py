"""Explicit, versioned TV numbering maps, scoped to configured source roots."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from .json_store import read_json, update_json
from .runtime_paths import cache_file

FILE = 'recognition_numbering_maps_v1.json'
SCHEMA = 1
MAX_RANGE = 1000


class MappingConflict(ValueError):
    pass


def _scope(scope, config):
    if not isinstance(scope,str) or not scope or not Path(scope).is_absolute():
        raise ValueError('映射作用域必须为绝对目录')
    path=Path(scope)
    if path.resolve() != path or not path.is_dir():
        raise ValueError('映射作用域不存在或包含符号链接/非规范路径')
    roots=[Path(root).resolve() for root in config.get('source_folders',[]) if isinstance(root,str) and root.strip()]
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError('映射作用域不在源目录内')
    return path


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('编号映射整数无效')
    return value


def _validate(rule):
    if not isinstance(rule,dict):raise ValueError('编号映射记录无效')
    rule=deepcopy(rule)
    if not isinstance(rule.get('id'),str) or not rule['id'] or rule.get('kind') not in ('exact','range'):
        raise ValueError('编号映射记录无效')
    if not isinstance(rule.get('scope'),str) or not Path(rule['scope']).is_absolute() or '..' in Path(rule['scope']).parts:
        raise ValueError('编号映射作用域无效')
    _integer(rule.get('tmdb_id'),1,2147483647)
    _integer(rule.get('season'),0,99)
    _integer(rule.get('episode'),1,9999)
    if type(rule.get('enabled')) is not bool or type(rule.get('deleted')) is not bool:
        raise ValueError('编号映射状态无效')
    if rule['kind']=='exact':
        label=rule.get('source_label')
        if not isinstance(label,str) or not label.strip() or len(label)>128 or any(ord(c)<32 for c in label) or '/' in label or '\\' in label:
            raise ValueError('原始编号无效')
    else:
        start=_integer(rule.get('start'),0,9999);end=_integer(rule.get('end'),0,9999)
        if end<start or end-start+1>MAX_RANGE or rule['episode']+end-start>9999:
            raise ValueError('编号范围或目标越界')
    return rule


def _load():
    path=cache_file(FILE)
    if path.is_symlink():raise ValueError('编号映射文件不能是符号链接')
    if not path.exists():return {'schema':SCHEMA,'revision':0,'rules':[]}
    state=read_json(path)
    if type(state.get('schema')) is not int or state['schema']!=SCHEMA or type(state.get('revision')) is not int or state['revision']<0 or not isinstance(state.get('rules'),list):
        raise ValueError('编号映射存储格式无效，原文件已保留')
    if len(state['rules'])>1000:raise ValueError('编号映射数量超限')
    rules=[_validate(rule) for rule in state['rules']]
    if len({rule['id'] for rule in rules})!=len(rules):raise ValueError('编号映射 ID 冲突')
    for rule in rules:
        _check_conflicts(rule,rules)
    return {'schema':SCHEMA,'revision':state['revision'],'rules':rules}


def revision():
    state=_load()
    return hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def list_maps():
    return deepcopy(_load()['rules'])


def _source_range(rule):
    if rule['kind']=='range':return rule['start'],rule['end']
    label=rule['source_label']
    return (int(label),int(label)) if re.fullmatch(r'[0-9]+',label) else None


def _source_overlap(a,b):
    if a['kind']=='exact' and b['kind']=='exact':return a['source_label']==b['source_label']
    ra,rb=_source_range(a),_source_range(b)
    return bool(ra and rb and max(ra[0],rb[0])<=min(ra[1],rb[1]))


def _overlap_scopes(a,b):
    a,b=Path(a),Path(b)
    return a==b or a in b.parents or b in a.parents


def _check_conflicts(candidate, rules):
    if not candidate['enabled'] or candidate['deleted']:return
    for other in rules:
        if not other['enabled'] or other['deleted'] or other['id']==candidate['id']:continue
        if _overlap_scopes(candidate['scope'],other['scope']) and _source_overlap(candidate,other):
            raise MappingConflict('作用域中的原始编号映射冲突')
        if candidate['tmdb_id']==other['tmdb_id'] and candidate['season']==other['season']:
            end=lambda r:r['episode'] + (r['end']-r['start'] if r['kind']=='range' else 0)
            if max(candidate['episode'],other['episode'])<=min(end(candidate),end(other)):
                raise MappingConflict('多个源编号映射到同一作品季集')


def _add(config, scope, tmdb_id, kind, season, episode, **fields):
    path=_scope(scope,config)
    rule=_validate({'id':uuid.uuid4().hex,'scope':str(path),'tmdb_id':tmdb_id,'kind':kind,
                    'season':season,'episode':episode,'enabled':True,'deleted':False,
                    'created_at':time.time(), **fields})
    def mutate(data):
        state=_load();_check_conflicts(rule,state['rules'])
        state['rules'].append(rule);state['revision']+=1;data.clear();data.update(state)
    update_json(cache_file(FILE),mutate)
    return deepcopy(rule)


def add_exact(config, scope, tmdb_id, source_label, season, episode):
    return _add(config,scope,tmdb_id,'exact',season,episode,source_label=source_label)


def add_range(config, scope, tmdb_id, start, end, season, episode):
    return _add(config,scope,tmdb_id,'range',season,episode,start=start,end=end)


def set_enabled(rule_id,enabled):
    if type(enabled) is not bool:raise ValueError('启用状态无效')
    def mutate(data):
        state=_load();rule=next((r for r in state['rules'] if r['id']==rule_id and not r['deleted']),None)
        if not rule:raise ValueError('编号映射不存在')
        rule['enabled']=enabled;_check_conflicts(rule,state['rules']);state['revision']+=1
        data.clear();data.update(state)
    update_json(cache_file(FILE),mutate)


def match(config, src, tmdb_id, source_label):
    src=Path(src)
    if not src.is_absolute() or src.resolve()!=src or src.is_symlink() or not src.is_file():
        raise ValueError('源文件路径无效')
    _integer(tmdb_id,1,2147483647)
    matches=[]
    for rule in _load()['rules']:
        if not rule['enabled'] or rule['deleted']:continue
        scope=Path(rule['scope'])
        if scope not in src.parents:continue
        _scope(str(scope),config)
        if rule['kind']=='exact':
            applies=rule['source_label']==source_label
            offset=0
        else:
            applies=isinstance(source_label,str) and bool(re.fullmatch(r'[0-9]+',source_label)) and rule['start']<=int(source_label)<=rule['end']
            offset=int(source_label)-rule['start'] if applies else 0
        if applies:
            if rule['tmdb_id']!=tmdb_id:raise MappingConflict('编号映射与作品身份冲突')
            matches.append(dict(rule,source_label=source_label,episode=rule['episode']+offset))
    if len(matches)>1:raise MappingConflict('多个编号映射同时匹配')
    return matches[0] if matches else None


def extract_source_label(filename):
    """Extract one explicit numeric label verbatim; multi-episode names are rejected."""
    stem=Path(filename).stem
    if re.fullmatch(r'\d+(?:\.\d+)?',stem):return stem
    multi = re.search(r'(?i)(?:E(?:P)?|OVA|OAD|SP|第|\s-\s|\[)\s*\d+(?:\.\d+)?\s*[-~–]\s*(?:E(?:P)?\s*)?\d+',stem)
    if multi:raise MappingConflict('多集文件需要人工确认')
    pattern=r'(?i)(?:(?<![A-Za-z])(?:E(?:P)?|OVA|OAD|SP)\s*|第\s*|(?<=\s-\s)|\[)(\d+(?:\.\d+)?)(?![\d.])'
    labels=[match.group(1) for match in re.finditer(pattern,stem)]
    if len(labels)>1:raise MappingConflict('多集文件需要人工确认')
    return labels[0] if labels else None
