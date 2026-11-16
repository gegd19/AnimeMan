"""One authentication policy for the global hook and legacy decorators."""

from functools import wraps
import hmac

from flask import current_app, g, has_app_context, request, Response, jsonify
from core import config_manager
from core.runtime_paths import config_file

CONFIG_PATH = "auto_config.json"
PUBLIC_ENDPOINTS = frozenset({"healthz", "static"})


def _config_path():
    return current_app.config.get("CONFIG_PATH", CONFIG_PATH) if has_app_context() else str(config_file())


def _load_checked_config():
    return config_manager.load_config(_config_path())


def check_auth(username, password):
    config = g.request_config if has_app_context() and hasattr(g, "request_config") else _load_checked_config()
    auth = config.get("auth", {})
    if not auth.get("enabled", False):
        return True
    return (isinstance(username, str) and isinstance(password, str)
            and hmac.compare_digest(username.encode(), str(auth.get("username", "")).encode())
            and hmac.compare_digest(password.encode(), str(auth.get("password", "")).encode()))


def authenticate():
    return Response('需要认证。请提供有效的用户名和密码。', 401,
                    {'WWW-Authenticate': 'Basic realm="AnimeMan", charset="UTF-8"'})


def enforce_auth():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if getattr(g, "auth_checked", False):
        return None
    try:
        g.request_config = _load_checked_config()
    except (OSError, ValueError, TypeError):
        return jsonify({"error": "配置无法读取，服务已拒绝业务访问，请修复配置"}), 503
    if g.request_config.get("auth", {}).get("enabled", False):
        auth = request.authorization
        if auth is None or auth.type.lower() != "basic" or not check_auth(auth.username, auth.password):
            return authenticate()
    g.auth_checked = True
    return None


def require_auth(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        denied = enforce_auth()
        return denied if denied is not None else function(*args, **kwargs)
    return wrapped
