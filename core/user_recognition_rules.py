"""Versioned, source-bounded user rules; no automatic global alias learning."""
from copy import deepcopy
import json
from pathlib import Path
import time
import unicodedata
import uuid

from .json_store import read_json, update_json
from .runtime_paths import cache_file

RULES_FILE = 'recognition_user_rules_v1.json'
SCHEMA = 1


class RuleValidationError(ValueError):
    pass


class RuleConflict(RuleValidationError):
    pass


def _path(value, config, *, directory=False):
    if not isinstance(value, str) or not value.strip():
        raise RuleValidationError('规则路径无效')
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise RuleValidationError('规则路径必须是非符号链接的绝对路径')
    resolved = path.resolve()
    roots = [Path(root).resolve() for root in config.get('source_folders', []) if isinstance(root,str) and root.strip()]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise RuleValidationError('规则路径不在源目录范围内')
    if directory and not resolved.is_dir():
        raise RuleValidationError('系列目录不存在')
    if not directory and not resolved.is_file():
        raise RuleValidationError('源文件不存在')
    return resolved


def _load_state():
    state = read_json(cache_file(RULES_FILE))
    if not state:
        return {'schema':SCHEMA, 'revision':0, 'rules':[]}
    if (type(state.get('schema')) is not int or state['schema'] != SCHEMA or type(state.get('revision')) is not int
            or state['revision'] < 0 or not isinstance(state.get('rules'),list)
            or any(not isinstance(rule,dict) for rule in state['rules'])):
        raise RuleValidationError('规则存储格式无效或版本不受支持，原文件已保留')
    ids = set()
    for rule in state['rules']:
        ident = rule.get('id')
        if (not isinstance(ident, str) or not ident or ident in ids
                or rule.get('scope') not in ('file', 'series')
                or not isinstance(rule.get('path'), str) or not rule['path']
                or type(rule.get('tmdb_id')) is not int or not 1 <= rule['tmdb_id'] <= 2147483647
                or rule.get('media_type') not in ('tv', 'movie')
                or type(rule.get('enabled')) is not bool or type(rule.get('deleted')) is not bool):
            raise RuleValidationError('规则记录无效，原文件已保留')
        if rule['scope'] == 'series':
            if (not isinstance(rule.get('anchor_title'), str) or not rule['anchor_title'].strip()
                    or rule.get('season') is not None or rule.get('episode') is not None):
                raise RuleValidationError('系列规则记录无效')
        elif rule['media_type'] == 'tv':
            if (type(rule.get('season')) is not int or not 0 <= rule['season'] <= 99
                    or type(rule.get('episode')) is not int or not 1 <= rule['episode'] <= 9999):
                raise RuleValidationError('剧集规则记录无效')
        elif rule.get('season') is not None or rule.get('episode') is not None:
            raise RuleValidationError('电影规则记录无效')
        ids.add(ident)
    return state


def list_rules(config):
    return deepcopy(_load_state()['rules'])


def revision(config):
    state = _load_state()
    return f"{state['schema']}:{state['revision']}"


def create_rule(config, src, scope, tmdb_id, media_type, *, season=None, episode=None, anchor_title=None):
    source = _path(src,config)
    if scope not in ('file','series') or media_type not in ('tv','movie') or type(tmdb_id) is not int or not 1 <= tmdb_id <= 2147483647:
        raise RuleValidationError('规则范围或 TMDB 身份无效')
    if scope == 'series':
        if not isinstance(anchor_title,str) or not anchor_title.strip():
            raise RuleValidationError('系列规则需要可验证的源标题')
        target = _path(str(source.parent),config,directory=True)
        season = episode = None
    else:
        target = source
        if media_type == 'tv' and (type(season) is not int or not 0 <= season <= 99
                                   or type(episode) is not int or not 1 <= episode <= 9999):
            raise RuleValidationError('单文件剧集规则需要有效季集号')
        if media_type == 'movie':
            season = episode = None
        anchor_title = None
    rule = {'id':uuid.uuid4().hex,'scope':scope,'path':str(target),'tmdb_id':tmdb_id,
            'media_type':media_type,'season':season,'episode':episode,
            'anchor_title':anchor_title.strip() if anchor_title else None,
            'enabled':True,'deleted':False,'created_at':time.time()}
    path=cache_file(RULES_FILE)
    def mutate(current):
        state = _load_state()
        state['rules'].append(rule)
        state['revision'] += 1
        current.clear();current.update(state)
    update_json(path,mutate)
    return deepcopy(rule)


def _change(rule_id, operation):
    if not isinstance(rule_id,str) or not rule_id:
        raise RuleValidationError('规则 ID 无效')
    found=[]
    def mutate(current):
        state=_load_state()
        for rule in state['rules']:
            if rule.get('id') == rule_id and not rule.get('deleted'):
                operation(rule);found.append(True);break
        if not found:raise RuleValidationError('规则不存在')
        state['revision'] += 1
        current.clear();current.update(state)
    update_json(cache_file(RULES_FILE),mutate)


def set_enabled(config, rule_id, enabled):
    if type(enabled) is not bool:raise RuleValidationError('启用状态无效')
    _change(rule_id,lambda rule:rule.update(enabled=enabled))


def delete_rule(config, rule_id):
    _change(rule_id,lambda rule:rule.update(enabled=False,deleted=True))


def _title(value):
    return unicodedata.normalize('NFKC',value).strip().casefold() if isinstance(value,str) else ''


def match_rule(src, config, info):
    source = _path(str(src),config)
    matches = {'file':[], 'series':[]}
    for rule in _load_state()['rules']:
        if rule.get('enabled') is not True or rule.get('deleted') is True:continue
        scope=rule.get('scope')
        if scope not in matches:raise RuleValidationError('规则范围无效')
        target=_path(rule.get('path'),config,directory=scope=='series')
        if scope=='file' and source==target:
            matches['file'].append(rule)
        elif scope=='series' and target in source.parents:
            anchor=_title(rule.get('anchor_title'))
            if anchor and anchor==_title(info.get('title')):
                if info.get('media_type') != rule.get('media_type'):
                    raise RuleConflict('系列规则与文件类型冲突，需要人工确认')
                matches['series'].append(rule)
    selected=matches['file'] or matches['series']
    if not selected:return None
    identities={(r.get('tmdb_id'),r.get('media_type'),r.get('season'),r.get('episode')) for r in selected}
    if len(identities)>1:raise RuleConflict('同一作用域存在冲突的人工规则')
    return deepcopy(selected[0])
