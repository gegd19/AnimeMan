#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core package initialization
Export commonly used functions for external usage
"""

__all__ = ["load_config", "save_config", "DEFAULT_CONFIG", "load_cache", "save_cache",
           "get_file_fingerprint", "run_processor_with_callback", "stop_processing",
           "scan_source_folders", "run_ai_preparse", "load_ai_preparse_cache"]


def __getattr__(name):
    # Importing the path/migration tool must not initialize processors, logs or
    # caches first; keep the existing public exports available lazily.
    from importlib import import_module
    exports = {
        "load_config": "config_manager", "save_config": "config_manager", "DEFAULT_CONFIG": "config_manager",
        "load_cache": "cache_manager", "save_cache": "cache_manager", "get_file_fingerprint": "cache_manager",
        "run_processor_with_callback": "media_processor", "stop_processing": "media_processor",
        "scan_source_folders": "offline_ai_preparser", "run_ai_preparse": "offline_ai_preparser",
        "load_ai_preparse_cache": "offline_ai_preparser",
    }
    if name in exports:
        return getattr(import_module(f".{exports[name]}", __name__), name)
    raise AttributeError(name)
