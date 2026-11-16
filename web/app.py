#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask 应用工厂（含全局认证钩子）
"""

import os
from core.runtime_paths import config_file
from flask import Flask, render_template, request, jsonify

from . import routes_config
from . import routes_task
from . import routes_browse
from . import routes_subtitle
from . import routes_ai
from . import routes_failed
from . import routes_mapping
from . import routes_offline
from . import routes_media
from . import routes_cache


def create_app(config_path=None):
    """Create an app with an optional, per-instance configuration file.

    Explicit paths are made absolute so background tasks use the same file.
    The no-argument entry point retains the original working-directory default.
    """
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')
    from .validation import StrictJSONProvider
    from core.validation import MAX_JSON_BYTES
    app.json = StrictJSONProvider(app)
    app.config["MAX_CONTENT_LENGTH"] = MAX_JSON_BYTES
    app.config["CONFIG_PATH"] = str(config_file(config_path))
    from core.logger import setup_logging
    setup_logging()
    app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

    @app.before_request
    def before_request():
        from .auth import enforce_auth
        denied = enforce_auth()
        if denied is not None:
            return denied
        from . import task_state
        from flask import g
        if (task_state.is_shutting_down() and request.method in ('POST','PUT','PATCH','DELETE')
                and request.endpoint != 'stop_task'):
            return jsonify({'status':'error','code':'shutting_down','message':'服务正在停止，拒绝新的写入'}), 503
        synchronous = {
            'correct_failed_item', 'retry_processed_item', 'retry_processed_cache_item',
            'delete_media_item', 'batch_delete_media_items', 'clear_processed_cache',
            'delete_processed_cache_item', 'batch_delete_processed_cache', 'clear_failed_cache',
            'execute_subtitle', 'batch_rename_subtitles',
        }
        asynchronous = {'run_task', 'batch_correct_failed_items', 'offline_preparse_scan',
                        'offline_preparse_parse', 'refresh_poster_cache'}
        if request.endpoint in synchronous | asynchronous and task_state.is_task_running():
            return jsonify({"status":"error", "message":"已有写入任务运行或正在停止"}), 409
        from .validation import validate_request
        validate_request()
        from .path_access import enforce_path_access, PathAccessError
        try:
            enforce_path_access()
        except PathAccessError:
            return jsonify({"error": "路径不在允许范围内"}), 403
        except (ValueError, TypeError, KeyError):
            return jsonify({"error": "无效的路径参数"}), 400
        if request.endpoint in synchronous:
            task = task_state.try_start_task(request.endpoint, g.request_config, synchronous=True)
            if task is None:
                return jsonify({"status":"error", "message":"已有写入任务运行或正在停止"}), 409
            g.write_task = task
            g.write_scope = task_state.task_execution(task)
            g.write_scope.__enter__()
        return None

    def finish_request_task(error=None, result=None):
        from flask import g
        from . import task_state
        if hasattr(g, 'write_task'):
            task = g.pop('write_task')
            scope = g.pop('write_scope')
            try:
                task_state.finish_task(task.task_id, error=error, result=result)
            finally:
                scope.__exit__(None, None, None)

    @app.teardown_request
    def release_unfinished_request(error):
        finish_request_task(error)

    from core.validation import ValidationError
    from core.config_manager import ConfigError
    from werkzeug.exceptions import BadRequest, UnsupportedMediaType, RequestEntityTooLarge, NotFound, Conflict

    @app.errorhandler(ValidationError)
    def invalid_input(error):
        return jsonify({'status': 'error', 'code': 'invalid_request', 'message': str(error)}), 400

    @app.errorhandler(BadRequest)
    @app.errorhandler(UnsupportedMediaType)
    @app.errorhandler(RequestEntityTooLarge)
    def invalid_json(error):
        return jsonify({'status': 'error', 'code': 'invalid_request',
                        'message': '请求 JSON 无效或超过大小上限'}), 413 if error.code == 413 else 400

    @app.errorhandler(NotFound)
    @app.errorhandler(Conflict)
    def resource_error(error):
        return jsonify({'status': 'error', 'code': 'not_found' if error.code == 404 else 'conflict',
                        'message': error.description}), error.code

    @app.errorhandler(ConfigError)
    def corrupt_config(error):
        return jsonify({'status': 'error', 'code': 'config_invalid', 'message': str(error)}), 503

    from core.derived_cache import DerivedCacheError
    @app.errorhandler(DerivedCacheError)
    def derived_cache_failure(error):
        app.logger.error('派生缓存刷新失败', exc_info=(type(error), error, error.__traceback__))
        return jsonify({'status': 'error', 'code': 'derived_cache_failed', 'message': str(error)}), 503

    from core.json_store import CacheCorruptionError
    @app.errorhandler(CacheCorruptionError)
    def corrupt_cache(error):
        return jsonify({"status":"error", "code":"cache_corrupt", "message":str(error)}), 503

    from core.cancellation import ProcessingCancelled
    @app.errorhandler(ProcessingCancelled)
    def cancelled_request(error):
        return jsonify({"status":"cancelled", "message":str(error)}), 409

    @app.after_request
    def prevent_private_cache(response):
        finish_request_task(f'HTTP {response.status_code}' if response.status_code >= 400 else None,
                            response.get_json(silent=True))
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/healthz')
    def healthz():
        return jsonify({"status": "ok"})

    @app.route('/')
    def index():
        return render_template('index.html')

    routes_config.register(app)
    routes_task.register(app)
    routes_browse.register(app)
    routes_subtitle.register(app)
    routes_ai.register(app)
    routes_failed.register(app)
    routes_mapping.register(app)
    routes_offline.register(app)
    routes_media.register(app)
    routes_cache.register(app)


    return app
