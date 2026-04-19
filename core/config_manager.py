#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
负责加载、保存、合并默认配置
"""

import json
import threading
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    "source_folders": ["D:/movie"],
    "tv_target_folder": "D:/Emby_Media/TV Shows",
    "movie_target_folder": "D:/Emby_Media/Movies",
    "video_extensions": [".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".wmv", ".flv"],
    "link_type": "hard",
    "ignore_patterns": ["sample", "trailer", "extra"],
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
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.1,
        "max_tokens": 600,
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
        "model": "deepseek-chat",
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


def load_config(config_path: str = "auto_config.json") -> Dict[str, Any]:
    """加载配置文件，如果不存在则创建默认配置"""
    with _config_lock:
        config_path_obj = Path(config_path)
        if config_path_obj.exists():
            try:
                with open(config_path_obj, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
            except Exception:
                user_config = {}
        else:
            user_config = {}

        merged = DEFAULT_CONFIG.copy()
        # 深度合并一级字典
        for k, v in user_config.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v

        # 如果 AI 功能启用但未提供有效的 API Key，则自动禁用并回退到正则解析
        if merged.get("ai_parser", {}).get("enabled"):
            ai_key = merged.get("ai_parser", {}).get("api_key", "")
            if not ai_key or ai_key == "YOUR_API_KEY":
                merged["ai_parser"]["enabled"] = False
                # 可在此记录日志，但因避免循环导入，logger 调用已省略
                # from .logger import get_logger
                # get_logger(__name__).warning("AI 解析已启用但 API Key 无效，已自动禁用")

        # 如果配置文件不存在，写入默认配置
        if not config_path_obj.exists():
            save_config(merged, config_path)

        return merged


def save_config(config: Dict[str, Any], config_path: str = "auto_config.json"):
    """保存配置到文件"""
    with _config_lock:
        temp_file = config_path + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        Path(temp_file).replace(config_path)
