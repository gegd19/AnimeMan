#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core package initialization
Export commonly used functions for external usage
"""

from .config_manager import load_config, save_config, DEFAULT_CONFIG
from .cache_manager import load_cache, save_cache, get_file_fingerprint
from .media_processor import run_processor_with_callback, stop_processing

# Optional: export offline AI preparser functions for CLI convenience
from .offline_ai_preparser import scan_source_folders, run_ai_preparse, load_ai_preparse_cache
