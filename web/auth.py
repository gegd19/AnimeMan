#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP Basic 认证中间件
"""

from functools import wraps
from flask import request, Response
from core import config_manager

CONFIG_PATH = "auto_config.json"

# 不需要认证的公开端点（前缀匹配）
PUBLIC_ENDPOINTS = [
    '/static/',
    '/api/status',
    '/api/log',
    '/api/drives',
    '/api/browse',
    '/media_poster/',
]


def check_auth(username, password):
    """验证用户名密码是否正确"""
    config = config_manager.load_config(CONFIG_PATH)
    auth_cfg = config.get("auth", {})
    if not auth_cfg.get("enabled", False):
        return True
    return username == auth_cfg.get("username") and password == auth_cfg.get("password")


def authenticate():
    """发送 401 响应，要求浏览器弹出登录框"""
    return Response(
        '需要认证。请提供有效的用户名和密码。',
        401,
        {'WWW-Authenticate': 'Basic realm="Emby Auto Processor"'}
    )


def require_auth(f):
    """装饰器：要求 HTTP Basic 认证"""
    @wraps(f)
    def decorated(*args, **kwargs):
        config = config_manager.load_config(CONFIG_PATH)
        auth_cfg = config.get("auth", {})
        if not auth_cfg.get("enabled", False):
            return f(*args, **kwargs)

        path = request.path
        for public in PUBLIC_ENDPOINTS:
            if path.startswith(public):
                return f(*args, **kwargs)

        # /api/config GET 公开，POST 需要认证（通过装饰器单独控制）
        if path == '/api/config' and request.method == 'GET':
            return f(*args, **kwargs)

        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated
