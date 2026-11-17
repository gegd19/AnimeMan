#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
负责加载、保存、合并默认配置
"""

from copy import deepcopy
import threading
from .execution_mode import skip_preview_write
from typing import Dict, Any
from .runtime_paths import config_file, effective_config
from .json_store import path_lock, write_json, backup_json
from .validation import validate_config, strict_loads, object_value, json_value, ValidationError, MAX_JSON_BYTES

DEFAULT_CONFIG: Dict[str, Any] = {
    "source_folders": ["D:/movie"],
    "tv_target_folder": "D:/Emby_Media/TV Shows",
    "movie_target_folder": "D:/Emby_Media/Movies",
    "video_extensions": [".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".wmv", ".flv"],
    "link_type": "hard",
    "ignore_patterns": ["sample", "trailer", "extra","sample","trailer","extra","Disc","SP","Vol","Menu","NCED","CM","ncop","NCOP.","SPs","PV","IV","Menu","Bonus"],
    "min_file_size_mb": 0,
    "dry_run": False,
    "add_year_to_folder": True,
    "force_chinese_name": True,
    "incremental": True,
    "max_workers": 3,
    "download_images": True,
    "image_base_url": "https://image.tmdb.org/t/p/",
    "tmdb_api": {"api_key": "YOUR_TMDB_API_KEY_V3", "language": "zh-CN"},
    "tmdb_rate_limit": 0.05,
    "ai_parser": {
        "enabled": False,
        "provider": "deepseek",
        "api_key": "YOUR_API_KEY",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.1,
        "max_tokens": 600,
        "thinking": "disabled",
        "timeout": 20,
        "debug": False,
        "batch_folder_enabled": True
    },
    "auth": {
        "enabled": False,
        "username": "admin",
        "password": "admin"
    },
    "ai_plot_enhance": {
        "enabled": False,
        "provider": "deepseek",
        "api_key": "YOUR_API_KEY",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.7,
        "max_tokens": 500,
        "timeout": 30,
        "prompt_template": "你是一个专业的影视剧文案。请将以下剧情简介改写得更加生动、吸引人，语言流畅自然，可以适当增加一些悬念和感染力。请直接输出改写后的简介，不要添加额外说明。\n\n原标题：{title}\n原简介：{original_plot}\n\n优化后简介："
    },
    "subtitle": {
        "enabled": True,
        "auto_sync": False,
        "sync_timeout": 60,
        "keep_original": True,
        "link_subtitles": True,
    },
    "anime_parser": {
        "enabled": True,
        "fallback_to_regex": True
    },
    "subtitle_center": {
        "default_source_folder": "",
        "auto_match_threshold": 75,
        "auto_sync_enabled": False,
        "link_mode": "hard",
        "overwrite_existing": False,
    },
    "scan_policy": {"include_specials": False, "exclude_patterns": []},
    "special_mappings": [
        {
            "keyword": "[OVA] 某科学的超电磁炮",
            "tmdb_id": 4604,
            "media_type": "tv",
            "season": 0,
            "episode": 1,
            "enabled": True,
            "description": "电磁炮 OVA"
        }
    ],
}

_config_lock = threading.RLock()


class ConfigError(ValueError):
    """The persisted configuration cannot be used; never apply defaults to damage."""


def _merge(defaults, values):
    result = deepcopy(defaults)
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _complete(value):
    object_value(value, '配置')
    json_value(value, '配置')
    # A persisted enabled auth section must explicitly carry its credentials.
    auth = value.get('auth')
    if isinstance(auth, dict) and auth.get('enabled') is True:
        if any(not isinstance(auth.get(key), str) or not auth[key].strip() for key in ('username', 'password')):
            raise ValidationError('启用认证需要显式非空用户名和密码')
    return validate_config(_merge(DEFAULT_CONFIG, value))


def _read_config(path):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if path.is_symlink():
            raise ConfigError('配置符号链接目标不存在，拒绝按新安装回退默认配置')
        return None
    try:
        if len(raw) > MAX_JSON_BYTES:
            raise ValidationError('配置文件超过 4 MiB')
        return _complete(strict_loads(raw))
    except (ValueError, TypeError, KeyError) as exc:
        # Keep the original plus a private, byte-for-byte recovery copy.
        backup_json(path, tag='t13-invalid')
        raise ConfigError('配置文件损坏或字段无效；已保留原件与备份，请修复后重试') from exc


def load_config(config_path=None, *, apply_environment=True, create_if_missing=True) -> Dict[str, Any]:
    path = config_file(config_path)
    with _config_lock, path_lock(path):
        stored = _read_config(path)
        merged = stored if stored is not None else _complete({})
        effective = effective_config(merged) if apply_environment else deepcopy(merged)
        validate_config(effective)
        # Preserve the existing runtime fallback; it never rewrites stored config.
        if effective['ai_parser'].get('enabled') and effective['ai_parser'].get('api_key') in ('', 'YOUR_API_KEY'):
            effective['ai_parser']['enabled'] = False
        if stored is None and create_if_missing and not effective.get('dry_run'):
            save_config(merged, path)
        return effective


@skip_preview_write
def save_config(config: Dict[str, Any], config_path=None):
    """Replace a validated snapshot atomically, refusing a damaged current file."""
    complete = _complete(config)
    path = config_file(config_path)
    with _config_lock, path_lock(path):
        _read_config(path)
        write_json(path, complete)


@skip_preview_write
def update_config(mutate, config_path=None):
    """Read/modify/validate/publish under one lock, without persisting env overrides."""
    path = config_file(config_path)
    with _config_lock, path_lock(path):
        current = _read_config(path)
        current = current if current is not None else _complete({})
        candidate = mutate(deepcopy(current))
        complete = _complete(candidate)
        if complete != current or not path.exists():
            write_json(path, complete)
        return deepcopy(complete)
