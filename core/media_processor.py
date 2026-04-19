#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单文件处理器（门面模块）
保持原有导入接口不变，实际逻辑已拆分到子模块中。
"""

# 从子模块重新导出所有对外接口
from .processor_utils import should_skip_file, is_video_file
from .processor_cache_ops import cleanup_previous_artifacts
from .processor_core import process_video, stop_processing
from .processor_manual import process_video_with_manual_correction
from .processor_repair import repair_missing_metadata
from .processor_runner import run_processor_with_callback
