#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局常量定义
"""

# 日志级别
LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"

# 置信度阈值
MIN_FINAL_CONFIDENCE = 60          # 最低置信度，低于此值视为失败
MIN_CONFIDENCE_FOR_AI_CACHE = 70   # 允许写入AI选择缓存的最低置信度

# 时长差异阈值（分钟）
MAX_DURATION_DIFF_MINUTES = 10

# 标题验证触发阈值
MIN_CANDIDATES_FOR_TITLE_CHECK = 5   # 候选数超过此值时考虑验证标题
LOW_SCORE_THRESHOLD = 15             # 最高得分低于此值时认为标题可能有问题

# 技术词汇黑名单（用于清洗搜索词）
TECH_NOISE_WORDS = {
    'mp4', 'mkv', 'avi', 'aac', 'flac', 'x264', 'x265', 'h264', 'h265',
    'hevc', '1080p', '720p', '4k', 'bluray', 'web-dl', 'bdrip', 'dvdrip',
    'complete', 'fin', 'end', 'gb', 'big5', 'chs', 'cht', 'jpn', 'eng'
}
