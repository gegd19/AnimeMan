"""Bounded, conservative evidence from the existing scan's file list.

These observations are suggestions only; a shared title never confirms a TMDB ID.
"""
from pathlib import Path
import hashlib
import json
import unicodedata

from .cancellation import check_cancelled
from .parser_regex import parse_with_regex

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
    for item in scanned_files:
        check_cancelled()
        path = Path(item).absolute()
        if path.parent == folder and not path.is_symlink() and path.resolve() == path:
            candidates.add(path)
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
    fingerprint = hashlib.sha256(json.dumps([str(folder), len(ordered), signatures], ensure_ascii=False).encode()).hexdigest()
    return {'groups':group_list, 'sampled':len(samples), 'complete':len(ordered) <= limit,
            'unknown':unknown, 'identity_status':'conflict' if len(group_list)>1 else 'unconfirmed',
            'fingerprint':fingerprint}
