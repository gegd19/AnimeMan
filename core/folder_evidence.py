"""Bounded, conservative evidence from the existing scan's file list.

These observations are suggestions only; a shared title never confirms a TMDB ID.
"""
from pathlib import Path
import hashlib
import json
import re
import unicodedata

from .cancellation import check_cancelled
from .parser_regex import parse_with_regex

EVIDENCE_VERSION = "e03-v1"
MAX_SAMPLES = 64


def collect_folder_evidence(folder, scanned_files, config, *, limit=MAX_SAMPLES):
    if type(limit) is not int or not 1 <= limit <= MAX_SAMPLES:
        raise ValueError('目录证据采样上限无效')
    folder = Path(folder).absolute()
    roots = [Path(root).resolve() for root in config.get('source_folders', []) if isinstance(root, str) and root.strip()]
    if folder.is_symlink() or folder.resolve() != folder or not any(folder == root or root in folder.parents for root in roots):
        raise ValueError('目录证据超出源目录范围')
    # The caller provides the scan inventory; this function never walks directories.
    candidates = set()
    missing = 0
    for item in scanned_files:
        check_cancelled()
        path = Path(item).absolute()
        if path.parent == folder and not path.is_symlink() and path.resolve() == path:
            if path.is_file():
                candidates.add(path)
            else:
                missing += 1
    ordered = sorted(candidates, key=lambda path: path.name)
    samples = ordered[:limit]
    groups = {}
    signatures = []
    unknown = 0
    for path in samples:
        check_cancelled()
        stat = path.stat()
        signatures.append([path.name, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
        parsed = parse_with_regex(path.name, folder.name)
        title = parsed.get('title', '').strip()
        if parsed.get('media_type') != 'tv' or not title or title.casefold() == 'unknown':
            unknown += 1
            continue
        key = (unicodedata.normalize('NFKC', title).casefold(), parsed.get('year'))
        group = groups.setdefault(key, {'title':title, 'year':parsed.get('year'), 'files':[]})
        group['files'].append(path.name)
    group_list = [groups[key] for key in sorted(groups, key=lambda value:(value[0],value[1] or ''))]
    fingerprint = hashlib.sha256(json.dumps([EVIDENCE_VERSION, str(folder), len(ordered), missing, signatures], ensure_ascii=False).encode()).hexdigest()
    return {'groups':group_list, 'sampled':len(samples), 'complete':len(ordered) <= limit and missing == 0,
            'unknown':unknown + missing, 'identity_status':'conflict' if len(group_list)>1 else 'unconfirmed',
            'fingerprint':fingerprint}


def _source_signature(src):
    stat = Path(src).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def special_series_hint(src):
    """A bare special marker can identify a title, never its season or episode."""
    match = re.fullmatch(r'(.+?)\s+(?:OVA|OAD|SP|SPECIAL|特典|特别篇|番外)', Path(src).stem, re.I)
    if not match or not match.group(1).strip():
        return {}
    return {'title':match.group(1).strip(), 'media_type':'tv'}


def pending_file_identity(src, config, rule):
    """Record a previously confirmed scoped rule, never an episode guess."""
    from . import parse_identity, user_recognition_rules
    effective = {key:value for key,value in config.items() if key != '_folder_evidence'}
    return {'identity_status':'confirmed', 'numbering_status':'unknown',
            'tmdb_id':rule['tmdb_id'], 'media_type':'tv', 'rule_id':rule['id'],
            'rule_revision':user_recognition_rules.revision(config), 'rule_scope':rule['scope'],
            'policy':parse_identity.policy_key(effective), 'source_signature':_source_signature(src)}


def current_pending_identity(src, config, pending):
    """Only expose an identity while its source, policy and explicit rule still match."""
    from . import parse_identity, user_recognition_rules as rules
    from .explicit_media_identity import extract_path_identity, extract_nfo_identity, explicit_media_type, IdentityEvidenceError
    from .special_mapping import match_special_mapping
    if not isinstance(pending, dict) or pending.get('identity_status') != 'confirmed' or pending.get('numbering_status') != 'unknown':
        return None
    if config.get('user_rules', {}).get('enabled') is not True:
        return None
    src = Path(src)
    if src.is_symlink() or not src.is_file() or _source_signature(src) != pending.get('source_signature'):
        return None
    effective = {key:value for key,value in config.items() if key != '_folder_evidence'}
    try:
        if pending.get('rule_revision') != rules.revision(config) or pending.get('policy') != parse_identity.policy_key(effective):
            return None
        rule = rules.match_rule(src, config, special_series_hint(src) if pending.get('rule_scope') == 'series' else {})
        ident = pending.get('tmdb_id')
        if not rule or rule['scope'] != pending.get('rule_scope') or rule['id'] != pending.get('rule_id') or rule['tmdb_id'] != ident or rule['media_type'] != 'tv':
            return None
        mapping = match_special_mapping(src.name, config.get('special_mappings', []))
        if mapping and (mapping['tmdb_id'] != ident or mapping['media_type'] != 'tv'):
            return None
        if config.get('identity_hints', {}).get('enabled'):
            roots = config.get('source_folders', [])
            path_id, nfo = extract_path_identity(src, roots), extract_nfo_identity(src, roots)
            kind = explicit_media_type(src, roots) if path_id is not None or nfo else None
            if (path_id is not None and path_id != ident) or (nfo and nfo != ('tv', ident)) or (kind and kind != 'tv'):
                return None
    except (rules.RuleValidationError, IdentityEvidenceError):
        return None
    return {'identity_status':'confirmed', 'numbering_status':'unknown', 'tmdb_id':ident, 'media_type':'tv'}
