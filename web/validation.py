"""Validate complete request shapes before path access or writer acquisition."""
from flask import g, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from core.validation import (ValidationError, MAX_ITEMS, object_value, string, boolean,
    integer, number, choice, array, query_integer, json_value, strict_loads, validate_ai, validate_mapping)


class StrictJSONProvider(DefaultJSONProvider):
    def loads(self, value, **kwargs):
        return strict_loads(value, **kwargs)


BODYLESS = {'run_task', 'stop_task', 'clear_processed_cache', 'clear_failed_cache',
            'offline_preparse_scan', 'offline_preparse_parse', 'refresh_poster_cache', 'delete_mapping'}
PATH_ONLY = {'retry_processed_item', 'retry_processed_cache_item', 'delete_processed_cache_item'}
SORTS = ('processed_time', 'confidence', 'title', 'src_name')


def _paths(data, field):
    for path in array(data.get(field), field, nonempty=True):
        string(path, field + ' 路径')


def _subtitle(value):
    object_value(value, 'subtitle')
    string(value.get('name'), 'subtitle.name')
    for key in ('path', 'parent_dir', 'grandparent_dir'):
        if key in value: string(value[key], 'subtitle.' + key, empty=key != 'path')


def _media(value, *, target=False):
    object_value(value, 'media')
    if target:
        for key in ('target_path', 'target_dir'): string(value.get(key), 'media.' + key)
    for key in ('title', 'media_type'):
        if key in value: string(value[key], 'media.' + key, empty=key == 'title')
    if 'media_type' in value: choice(value['media_type'], 'media.media_type', ('movie', 'tv'))
    for key in ('season', 'episode', 'tmdb_id'):
        if key in value:
            integer(value[key], 'media.' + key, 0 if key == 'season' else 1,
                    99 if key == 'season' else 9999 if key == 'episode' else 2147483647, nullable=True)
    if 'seasons' in value:
        for season in object_value(value['seasons'], 'media.seasons').values():
            object_value(season, 'media season')
            for episode in array(season.get('episodes', []), 'media episodes'):
                object_value(episode, 'media episode')
                integer(episode.get('episode'), 'media episode.episode', 1, 9999)
                for key in ('target_path', 'target_dir', 'cache_key'):
                    if key in episode: string(episode[key], 'media episode.' + key)


def _correction(data, batch=False):
    integer(data.get('tmdb_id'), 'tmdb_id', 1, 2147483647)
    kind = choice(data.get('media_type', 'tv'), 'media_type', ('movie', 'tv'))
    if batch:
        _paths(data, 'src_paths')
        integer(data.get('season'), 'season', 0, 99, nullable=True)
        integer(data.get('start_episode', 1), 'start_episode', 1, 9999, nullable=kind == 'movie')
        integer(data.get('episode_increment', 1), 'episode_increment', 1, 9999, nullable=kind == 'movie')
    else:
        string(data.get('src_path'), 'src_path')
        integer(data.get('season'), 'season', 0, 99, nullable=kind == 'movie')
        integer(data.get('episode'), 'episode', 1, 9999, nullable=kind == 'movie')
        if 'save_rule_scope' in data: choice(data['save_rule_scope'], 'save_rule_scope', ('none', 'file', 'series'))


def _validate_query(endpoint):
    query = request.args
    for key in query:
        if len(query.getlist(key)) != 1:
            raise ValidationError('查询参数不能重复')
        string(query[key], '查询参数', empty=True)
    g.validated_query = {}
    if endpoint == 'get_processed_cache':
        g.validated_query['page'] = query_integer(query.get('page', '1'), 'page', 1, 1000000)
        g.validated_query['per_page'] = query_integer(query.get('per_page', '50'), 'per_page', 1, 200)
    if endpoint in ('get_processed_cache', 'get_processed_history'):
        allowed = SORTS if endpoint == 'get_processed_cache' else ('processed_time', 'src_name')
        choice(query.get('sort', 'processed_time'), 'sort', allowed)
        choice(query.get('order', 'desc'), 'order', ('asc', 'desc'))
    if endpoint == 'delete_mapping':
        g.validated_query['index'] = query_integer(query.get('index'), 'index', 0, MAX_ITEMS - 1)
    if endpoint == 'tmdb_search_proxy':
        string(query.get('query', ''), 'query', empty=True, maximum=200)
        choice(query.get('media_type', 'tv'), 'media_type', ('tv', 'movie'))
        if query.get('year'):
            query_integer(query['year'], 'year', 1800, 2199)
    if endpoint == 'stop_task' and 'force' in query:
        choice(query['force'], 'force', ('0', '1'))


def validate_request():
    endpoint = request.endpoint
    _validate_query(endpoint)
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    raw = request.get_data(cache=True)
    if not raw and endpoint in BODYLESS:
        data = {}
    else:
        try:
            data = request.get_json()
        except (BadRequest, UnsupportedMediaType, ValueError) as exc:
            raise ValidationError('请求必须包含有效的 JSON 对象') from exc
        object_value(data, '请求 JSON')
        json_value(data, '请求 JSON')
    g.validated_body = data
    if endpoint in BODYLESS:
        return
    if endpoint == 'config_post':
        return  # Full merged config is checked inside the config transaction.
    if endpoint in PATH_ONLY:
        string(data.get('src_path'), 'src_path')
    elif endpoint == 'batch_delete_processed_cache':
        _paths(data, 'src_paths')
    elif endpoint in ('delete_media_item', 'batch_delete_media_items'):
        if endpoint == 'delete_media_item': string(data.get('src_path'), 'src_path')
        else: _paths(data, 'src_paths')
        boolean(data.get('delete_source', False), 'delete_source')
    elif endpoint in ('correct_failed_item', 'batch_correct_failed_items'):
        _correction(data, endpoint == 'batch_correct_failed_items')
    elif endpoint in ('set_recognition_rule_state', 'delete_recognition_rule'):
        string(data.get('id'), 'id', maximum=64)
        if endpoint == 'set_recognition_rule_state': boolean(data.get('enabled'), 'enabled')
    elif endpoint in ('add_mapping', 'update_mapping'):
        validate_mapping(data.get('rule'))
        if endpoint == 'update_mapping': integer(data.get('index'), 'index', 0, MAX_ITEMS - 1)
    elif endpoint == 'scan_subtitle_folder':
        if 'folder' in data: string(data['folder'], 'folder', empty=True)
    elif endpoint == 'match_subtitles':
        for subtitle in array(data.get('subtitles'), 'subtitles', nonempty=True): _subtitle(subtitle)
        number(data.get('threshold', 60), 'threshold', 0, 100)
    elif endpoint == 'execute_subtitle':
        for item in array(data.get('items'), 'items', nonempty=True):
            object_value(item, 'item')
            string(item.get('subtitle_path'), 'subtitle_path')
            _media(item.get('target_media'), target=True)
            boolean(item.get('auto_sync', False), 'auto_sync')
    elif endpoint == 'batch_rename_subtitles':
        for item in array(data.get('renames'), 'renames', nonempty=True):
            object_value(item, 'rename')
            for key in ('old_path', 'new_path'): string(item.get(key), key)
    elif endpoint in ('ai_parse_subtitles', 'ai_match_subtitles'):
        for item in array(data.get('files'), 'files', nonempty=True):
            object_value(item, 'file')
            string(item.get('path'), 'file.path')
            string(item.get('name'), 'file.name')
        if endpoint == 'ai_match_subtitles':
            _media(data.get('show_info'))
            string(data['show_info'].get('title'), 'show_info.title')
    elif endpoint == 'match_single_subtitle':
        _subtitle(data.get('subtitle'))
        number(data.get('threshold', 60), 'threshold', 0, 100)
        if data.get('force_title') is not None: string(data['force_title'], 'force_title')
    elif endpoint == 'stream_ai_enhance':
        string(data.get('title'), 'title', maximum=200)
        string(data.get('original_plot'), 'original_plot', maximum=5000)
        choice(data.get('ai_config_source', 'ai_parser'), 'ai_config_source', ('ai_parser', 'ai_plot_enhance'))
        validate_ai(data.get('ai_config', {}))
