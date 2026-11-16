"""Versioned JSON projections of the authoritative processing cache.

Lock order is processing-cache lock -> JSON path lock. Invalidation never takes
projection/file locks, and publication precedes marking a projection clean.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from . import cache_manager
from .cancellation import check_cancelled
from .execution_mode import is_preview, preview_mode
from .json_store import read_json, write_json, backup_json, CacheCorruptionError
from .media_identity import media_identity, identity_key, poster_url
from .metadata_io import is_valid_image
from .path_safety import validate_target_path, UnsafePathError, target_roots, source_roots
from .runtime_paths import cache_file

SCHEMA = 14
FILES = {'library': 'media_library_cache.json', 'poster': 'poster_cache.json'}
_state_lock = threading.RLock()
_epochs = {}
_clean = {}


class DerivedCacheError(OSError):
    pass


class AmbiguousMediaError(ValueError):
    pass


def _namespace(path=None):
    path = Path(path) if path is not None else cache_file(cache_manager.CACHE_FILE)
    # The commit notification must not fail on a post-commit filesystem lookup.
    return os.path.abspath(os.fspath(path))


def invalidate(primary_path):
    """Called only after a successful primary-cache commit; no derived I/O here."""
    key = _namespace(primary_path)
    with _state_lock:
        _epochs[key] = _epochs.get(key, 0) + 1


def _state(kind):
    key = _namespace()
    with _state_lock:
        epoch = _epochs.get(key, 0)
        return key, epoch, _clean.get((key, kind), 0) != epoch


def _accept(kind, key, epoch):
    with _state_lock:
        if _epochs.get(key, 0) == epoch:
            _clean[key, kind] = epoch


def _config(config):
    if config is None:
        from .config_manager import load_config
        return load_config(create_if_missing=False)
    return config


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _stamp(path):
    try:
        stat = path.stat()
        return [str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return None


def _within(path, roots):
    return any(path == root or root in path.parents for root in roots)


def _safe_image(path, source, config):
    try:
        validate_target_path(source, path, config, 'subtitle')
        resolved = path.resolve()
        return (_within(resolved, target_roots(config, 'subtitle'))
                and not _within(resolved, source_roots(config)))
    except (UnsafePathError, ValueError, RuntimeError):
        return False


def _episode(value, minimum, maximum):
    if isinstance(value, str) and value.isdecimal() and len(value) <= 4:
        value = int(value)
    return value if type(value) is int and minimum <= value <= maximum else None


def _policy(config):
    return {'targets': sorted(map(str, target_roots(config, 'subtitle'))),
            'sources': sorted(map(str, source_roots(config)))}


def _primary_revision(processed, config):
    return _digest([SCHEMA, processed, _policy(config)])


def _snapshot(config, *, identities=None):
    processed = cache_manager.load_cache()
    rows, issues, filesystem, by_identity = [], [], [], {}
    for source, entry in sorted(processed.items()):
        check_cancelled()
        if not isinstance(entry, dict):
            issues.append({'cache_key': source, 'message': '无效处理记录'})
            continue
        kind = entry.get('media_type')
        if kind not in ('movie', 'tv'):
            continue
        identity = media_identity(kind, entry.get('tmdb_id'))
        if identities is not None and identity not in identities:
            continue
        if entry.get('needs_reindex'):
            issues.append({'cache_key': source, 'message': '记录需要重建，未加入派生索引'})
            continue
        try:
            target = validate_target_path(source, entry.get('target'), config, kind)
        except (UnsafePathError, ValueError, RuntimeError) as error:
            issues.append({'cache_key': source, 'message': str(error)})
            continue
        season = _episode(entry.get('season'), 0, 99) if kind == 'tv' else None
        episode = _episode(entry.get('episode'), 1, 9999) if kind == 'tv' else None
        if kind == 'tv' and (season is None or episode is None):
            issues.append({'cache_key': source, 'message': '季集身份无效，未默认第一集'})
            continue
        folder = target.parent if kind == 'movie' else target.parent.parent
        candidates = {}
        stamps = []
        for name in ('poster', 'fanart'):
            paths = []
            extensions = ('.jpg', '.jpeg', '.png')
            candidates_in_folder = {folder / (name + extension) for extension in extensions}
            # Retain the old scanner's supported uppercase extensions/variants.
            candidates_in_folder.update(path for path in folder.glob(name + '.*') if path.suffix.lower() in extensions)
            ordered = sorted(candidates_in_folder, key=lambda path: (
                extensions.index(path.suffix.lower()), path.name != name + path.suffix.lower(), path.name))
            for path in ordered:
                safe = _safe_image(path, source, config)
                stamps.append([str(path), _stamp(path) if safe else 'unsafe'])
                if safe:
                    paths.append(path)
            candidates[name] = paths
        target_stamp = _stamp(target)
        physical = [source, target_stamp, stamps]
        filesystem.append(physical)
        if identity:
            by_identity.setdefault(identity_key(identity), []).append(physical)
        rows.append({'source': source, 'entry': entry, 'target': target, 'folder': folder,
                     'exists': target_stamp is not None and target.is_file(),
                     'identity': identity,
                     'season': season, 'episode': episode, 'candidates': candidates})
    return {'rows': rows, 'issues': issues,
            'primary_revision': _primary_revision(processed, config),
            'identity_revisions': {key: _digest(value) for key, value in by_identity.items()},
            'revision': _digest([SCHEMA, processed, _policy(config), filesystem])}


def _images(row):
    if not row['exists']:
        return {'poster_path': None, 'fanart_path': None}
    result = {}
    for slot, paths in row['candidates'].items():
        result[slot + '_path'] = next((str(path) for path in paths if path.is_file() and is_valid_image(path)), None)
    return result


def _library(snapshot):
    movies, shows = [], {}
    for row in snapshot['rows']:
        check_cancelled()
        entry, target, identity = row['entry'], row['target'], row['identity']
        title = entry.get('title') or ''
        aliases = entry.get('alternative_titles')
        aliases = aliases if isinstance(aliases, list) else ([title] if title else [])
        images = _images(row)
        image_exists = any(images.values())
        common = {'media_type': entry['media_type'], 'tmdb_id': identity[1] if identity else None,
                  'title': title, 'year': entry.get('year', ''), 'alternative_titles': aliases}
        if entry['media_type'] == 'movie':
            movies.append(dict(common, cache_key=row['source'], target_path=str(target), target_dir=str(target.parent),
                               target_exists=row['exists'], poster_exists=image_exists,
                               poster_url=poster_url(identity) if image_exists else None,
                               processed_time=entry.get('processed_time', 0)))
            continue
        # Unidentified shows remain distinct; no global None-ID grouping.
        group = identity or ('tv', None, str(row['folder']))
        if group not in shows:
            shows[group] = dict(common, poster_exists=False, poster_url=None, seasons={})
        show = shows[group]
        if image_exists:
            show['poster_exists'] = True
            show['poster_url'] = poster_url(identity)
        season = str(row['season'])
        show['seasons'].setdefault(season, {'season_number': row['season'], 'episodes': []})['episodes'].append({
            'episode': row['episode'], 'title': entry.get('episode_title') or f"第 {row['episode']} 集",
            'target_path': str(target), 'target_dir': str(target.parent), 'cache_key': row['source'],
            'target_exists': row['exists'], 'processed_time': entry.get('processed_time', 0)})
    for show in shows.values():
        for season in show['seasons'].values():
            season['episodes'].sort(key=lambda episode: episode['episode'])
        show['seasons'] = dict(sorted(show['seasons'].items(), key=lambda pair: int(pair[0])))
    return {'movies': movies, 'tv_shows': list(shows.values()), 'issues': snapshot['issues']}


def _posters(snapshot):
    items, identities = {}, set()
    for row in snapshot['rows']:
        check_cancelled()
        identity = row['identity']
        if not identity:
            continue
        key = identity_key(identity)
        identities.add(key)
        images = _images(row)
        if not any(images.values()):
            continue
        item = items.setdefault(key, {'media_type': identity[0], 'tmdb_id': identity[1],
                                     'poster_path': None, 'fanart_path': None})
        for name, path in images.items():
            if item[name] is None:
                item[name] = path
    return {'items': items, 'identities': sorted(identities), 'issues': snapshot['issues']}


def _valid(frame, kind):
    if (frame.get('_schema') != SCHEMA or frame.get('kind') != kind
            or not isinstance(frame.get('source_revision'), str)
            or not isinstance(frame.get('primary_revision'), str) or 'checksum' not in frame):
        return False
    if kind == 'library':
        shape = isinstance(frame.get('movies'), list) and isinstance(frame.get('tv_shows'), list)
    else:
        shape = (isinstance(frame.get('items'), dict) and isinstance(frame.get('identities'), list)
                 and isinstance(frame.get('identity_revisions'), dict))
    return shape and frame['checksum'] == _digest({key: value for key, value in frame.items() if key != 'checksum'})


def generate_library(config=None):
    config = _config(config)
    with preview_mode(is_preview(config)), cache_manager.cache_lock:
        return dict(_library(_snapshot(config)), updated=time.time())


def get(kind, config=None, *, force=False):
    config = _config(config)
    with preview_mode(is_preview(config)), cache_manager.cache_lock:
        try:
            for _ in range(3):
                check_cancelled()
                key, epoch, dirty = _state(kind)
                path = cache_file(FILES[kind])
                old = read_json(path)
                valid = _valid(old, kind)
                # A warm image lookup checks primary provenance cheaply, then
                # find_poster validates only the requested identity's files.
                if (kind == 'poster' and valid and not force and not dirty
                        and old['primary_revision'] == _primary_revision(cache_manager.load_cache(), config)):
                    return deepcopy(old)
                snapshot = _snapshot(config)
                if valid and not force and not dirty and old['source_revision'] == snapshot['revision']:
                    return deepcopy(old)
                payload = _library(snapshot) if kind == 'library' else _posters(snapshot)
                frame = dict(payload, _schema=SCHEMA, kind=kind, source_revision=snapshot['revision'],
                             primary_revision=snapshot['primary_revision'], updated=time.time())
                if kind == 'poster':
                    frame['identity_revisions'] = snapshot['identity_revisions']
                frame['checksum'] = _digest(frame)
                # Image/target replacement can happen outside primary-cache writes.
                if _snapshot(config)['revision'] != snapshot['revision']:
                    continue
                check_cancelled()
                if not is_preview(config):
                    if path.exists() and not valid:
                        backup_json(path, tag='t14')
                    check_cancelled()
                    write_json(path, frame)
                    _accept(kind, key, epoch)
                return deepcopy(frame)
            raise DerivedCacheError('媒体状态持续变化，派生缓存未发布，请重试')
        except CacheCorruptionError:
            raise
        except OSError as error:
            if isinstance(error, DerivedCacheError):
                raise
            raise DerivedCacheError('派生缓存刷新失败，旧快照已保留') from error


def poster_status(config=None):
    config = _config(config)
    with preview_mode(is_preview(config)), cache_manager.cache_lock:
        snapshot = _snapshot(config)
        frame = read_json(cache_file(FILES['poster']))
        stale = not _valid(frame, 'poster') or _state('poster')[2] or frame.get('source_revision') != snapshot['revision']
        return {'cached_count': 0 if stale else len(frame['items']), 'stale': stale}


def find_poster(media_type, tmdb_id, config):
    identity = media_identity(media_type or 'movie', tmdb_id)
    if not identity:
        return None
    with cache_manager.cache_lock:
        for _ in range(3):
            frame = get('poster', config)
            keys = [key for key in frame['identities'] if key.endswith(':' + str(identity[1]))]
            if media_type is None:
                if len(keys) > 1:
                    raise AmbiguousMediaError('该数字 ID 同时属于电影和 TV，请指定媒体类型')
                if not keys:
                    return None
                media_type = keys[0].split(':')[0]
            identity = media_identity(media_type, identity[1])
            key = identity_key(identity)
            snapshot = _snapshot(config, identities={identity})
            if frame['identity_revisions'].get(key) != snapshot['identity_revisions'].get(key):
                get('poster', config, force=True)
                continue
            item = frame['items'].get(key, {})
            allowed = {str(path) for row in snapshot['rows'] if row['identity'] == identity and row['exists']
                       for paths in row['candidates'].values() for path in paths}
            for name in ('poster_path', 'fanart_path'):
                path = item.get(name)
                if path and path in allowed and Path(path).is_file() and is_valid_image(path):
                    return Path(path)
            return None
        raise DerivedCacheError('媒体状态持续变化，海报未返回，请重试')
