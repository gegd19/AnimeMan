"""Shared, non-coercing value/config validation. Errors never echo values."""
import json
import math
import re
from string import Formatter

MAX_ITEMS = 1000
MAX_PATH = 8192
MAX_JSON_BYTES = 4 * 1024 * 1024
PROVIDERS = ('deepseek', 'openai', 'zhipu', 'qwen')


class ValidationError(ValueError):
    pass


def object_value(value, field):
    if not isinstance(value, dict):
        raise ValidationError(f'{field} 必须为对象')
    return value


def string(value, field, *, empty=False, maximum=MAX_PATH):
    if not isinstance(value, str) or '\0' in value or len(value) > maximum or (not empty and not value.strip()):
        raise ValidationError(f'{field} 必须为有效字符串（上限 {maximum} 字符）')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValidationError(f'{field} 包含无效 Unicode 字符') from exc
    return value


def boolean(value, field):
    if type(value) is not bool:
        raise ValidationError(f'{field} 必须为布尔值')
    return value


def integer(value, field, minimum, maximum, *, nullable=False):
    if value is None and nullable:
        return value
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f'{field} 必须为 {minimum}–{maximum} 的整数')
    return value


def number(value, field, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValidationError(f'{field} 必须为 {minimum}–{maximum} 的有限数值')
    return value


def choice(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValidationError(f'{field} 的枚举值无效')
    return value


def array(value, field, *, nonempty=False, maximum=MAX_ITEMS):
    if not isinstance(value, list) or len(value) > maximum or (nonempty and not value):
        raise ValidationError(f'{field} 必须为数组（上限 {maximum} 项）')
    return value


def query_integer(value, field, minimum, maximum):
    if not isinstance(value, str) or len(value) > 10 or not re.fullmatch(r'[0-9]+', value):
        raise ValidationError(f'{field} 必须为整数查询参数')
    return integer(int(value), field, minimum, maximum)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError('JSON 包含重复字段')
        result[key] = value
    return result


def reject_constant(value):
    raise ValidationError('JSON 不支持非有限数字')


def strict_loads(raw, **kwargs):
    kwargs.setdefault('object_pairs_hook', unique_object)
    kwargs.setdefault('parse_constant', reject_constant)
    try:
        return json.loads(raw, **kwargs)
    except (RecursionError, UnicodeError) as exc:
        raise ValidationError('JSON 编码或嵌套深度无效') from exc


def json_value(value, field='JSON', depth=0):
    if depth > 32:
        raise ValidationError(f'{field} 嵌套超过 32 层')
    if isinstance(value, dict):
        for key, item in value.items():
            string(key, field + ' 字段名', maximum=MAX_PATH)
            json_value(item, field, depth + 1)
    elif isinstance(value, list):
        array(value, field)
        for item in value:
            json_value(item, field, depth + 1)
    elif isinstance(value, str):
        string(value, field, empty=True, maximum=4 * 1024 * 1024)
    elif type(value) is float and not math.isfinite(value):
        raise ValidationError(f'{field} 不支持非有限数字')
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ValidationError(f'{field} 包含非 JSON 类型')


def plot_prompt(value):
    string(value, 'prompt_template', empty=True, maximum=20000)
    try:
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None and (name not in ('title', 'original_plot') or spec or conversion not in (None, 's', 'r', 'a')):
                raise ValidationError('prompt_template 仅支持 title/original_plot，禁止格式宽度或属性访问')
    except ValueError as exc:
        raise ValidationError('prompt_template 格式无效') from exc


def validate_ai(value, field='ai_config'):
    object_value(value, field)
    for key in ('enabled', 'debug', 'batch_folder_enabled'):
        if key in value: boolean(value[key], f'{field}.{key}')
    if 'provider' in value: choice(value['provider'], f'{field}.provider', PROVIDERS)
    for key in ('api_key', 'model', 'base_url', 'prompt_template'):
        if key in value: string(value[key], f'{field}.{key}', empty=True, maximum=20000 if key == 'prompt_template' else MAX_PATH)
    if 'temperature' in value: number(value['temperature'], f'{field}.temperature', 0, 2)
    if 'max_tokens' in value: integer(value['max_tokens'], f'{field}.max_tokens', 1, 131072)
    if 'timeout' in value: number(value['timeout'], f'{field}.timeout', 1, 600)
    if 'folder_wait_timeout' in value: number(value['folder_wait_timeout'], f'{field}.folder_wait_timeout', 0.001, 600)
    if 'prompt_template' in value: plot_prompt(value['prompt_template'])


def validate_mapping(value, field='rule'):
    object_value(value, field)
    string(value.get('keyword'), field + '.keyword', maximum=512)
    integer(value.get('tmdb_id'), field + '.tmdb_id', 1, 2147483647)
    choice(value.get('media_type'), field + '.media_type', ('movie', 'tv'))
    for key in ('season', 'episode'):
        if value['media_type'] == 'tv' or key in value:
            integer(value.get(key), field + '.' + key, 0 if key == 'season' else 1,
                    99 if key == 'season' else 9999, nullable=value['media_type'] == 'movie')
    if 'enabled' in value: boolean(value['enabled'], field + '.enabled')
    for key in ('title_override', 'description'):
        if key in value: string(value[key], field + '.' + key, empty=True)


def validate_config(config):
    object_value(config, '配置')
    json_value(config, '配置')
    for key in ('source_folders', 'video_extensions', 'ignore_patterns', 'special_mappings'):
        array(config[key], key, maximum=64 if key == 'video_extensions' else MAX_ITEMS)
    for value in config['source_folders']: string(value, 'source_folders 路径')
    if 'browse_roots' in config:
        for value in array(config['browse_roots'], 'browse_roots'):
            string(value, 'browse_roots 路径')
    for value in config['ignore_patterns']: string(value, 'ignore_patterns 项', maximum=512)
    for value in config['video_extensions']:
        string(value, 'video_extensions 项', maximum=16)
        if not re.fullmatch(r'\.[A-Za-z0-9]+', value):
            raise ValidationError('video_extensions 项必须为点开头的扩展名')
    for key in ('tv_target_folder', 'movie_target_folder'):
        string(config[key], key, empty=True)
    choice(config['link_type'], 'link_type', ('hard', 'symlink'))
    for key in ('dry_run', 'add_year_to_folder', 'force_chinese_name', 'incremental', 'download_images'):
        boolean(config[key], key)
    integer(config['max_workers'], 'max_workers', 1, 32)
    number(config['min_file_size_mb'], 'min_file_size_mb', 0, 2147483647)
    number(config['tmdb_rate_limit'], 'tmdb_rate_limit', 0, 60)
    string(config['image_base_url'], 'image_base_url', empty=True)
    auth = object_value(config['auth'], 'auth')
    boolean(auth.get('enabled'), 'auth.enabled')
    for key in ('username', 'password'):
        string(auth.get(key), 'auth.' + key, empty=not auth['enabled'])
    tmdb = object_value(config['tmdb_api'], 'tmdb_api')
    for key in ('api_key', 'language'):
        string(tmdb.get(key), 'tmdb_api.' + key, empty=key == 'api_key')
    if tmdb.get('proxy') is not None: string(tmdb['proxy'], 'tmdb_api.proxy', empty=True)
    for key in ('ai_parser', 'ai_plot_enhance'): validate_ai(config[key], key)
    subtitle = object_value(config['subtitle'], 'subtitle')
    for key in ('enabled', 'auto_sync', 'keep_original', 'link_subtitles'):
        boolean(subtitle[key], 'subtitle.' + key)
    integer(subtitle['sync_timeout'], 'subtitle.sync_timeout', 1, 3600)
    parser = object_value(config['anime_parser'], 'anime_parser')
    for key in ('enabled', 'fallback_to_regex'): boolean(parser[key], 'anime_parser.' + key)
    center = object_value(config['subtitle_center'], 'subtitle_center')
    string(center['default_source_folder'], 'subtitle_center.default_source_folder', empty=True)
    number(center['auto_match_threshold'], 'subtitle_center.auto_match_threshold', 0, 100)
    for key in ('auto_sync_enabled', 'overwrite_existing'): boolean(center[key], 'subtitle_center.' + key)
    choice(center['link_mode'], 'subtitle_center.link_mode', ('hard', 'symlink', 'copy'))
    policy = object_value(config['scan_policy'], 'scan_policy')
    boolean(policy['include_specials'], 'scan_policy.include_specials')
    for value in array(policy['exclude_patterns'], 'scan_policy.exclude_patterns'):
        string(value, 'scan_policy.exclude_patterns 项', maximum=512)
    for value in config['special_mappings']: validate_mapping(value, 'special_mappings 项')
    if 'failure_retry' in config:
        retry = object_value(config['failure_retry'], 'failure_retry')
        if 'max_attempts' in retry: integer(retry['max_attempts'], 'failure_retry.max_attempts', 1, 10)
        if 'backoff_seconds' in retry: number(retry['backoff_seconds'], 'failure_retry.backoff_seconds', 1, 3600)
    if len(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')) > MAX_JSON_BYTES:
        raise ValidationError('配置序列化后超过 4 MiB')
    return config
