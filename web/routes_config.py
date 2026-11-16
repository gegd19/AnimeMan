#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置相关 API 路由 + 媒体海报服务（带缓存优化）
- TMDB 测试端点优化：返回简洁友好的中文错误提示
- 修复 create_session 导入冲突
"""

from core.json_store import read_json, write_json
import threading
from core.execution_mode import skip_preview_write
from core.runtime_paths import cache_file, managed_media_fields
from flask import request, jsonify, send_from_directory
from core import config_manager, cache_manager, derived_cache
from .auth import require_auth
from . import task_state
from .task_state import request_config
from .config_secrets import public_config, merge_config

CONFIG_PATH = "auto_config.json"

# 海报缓存
_poster_cache = {}
_poster_cache_path = None
_poster_cache_lock = threading.RLock()
POSTER_CACHE_FILE = "poster_cache.json"

_refresh_running = False


def _load_poster_cache():
    global _poster_cache, _poster_cache_path
    cache_path = cache_file(POSTER_CACHE_FILE)
    data = read_json(cache_path)
    _poster_cache, _poster_cache_path = data, cache_path


def _ensure_poster_cache(config=None, *, force=False):
    global _poster_cache, _poster_cache_path
    path = cache_file(POSTER_CACHE_FILE)
    frame = derived_cache.get('poster', config, force=force)
    with _poster_cache_lock:
        _poster_cache = frame
        _poster_cache_path = path
    return frame


@skip_preview_write
def _save_poster_cache():
    global _poster_cache_path
    with _poster_cache_lock:
        write_json(cache_file(POSTER_CACHE_FILE), _poster_cache)
        _poster_cache_path = cache_file(POSTER_CACHE_FILE)


def _scan_all_posters(config=None):
    return len(_ensure_poster_cache(config, force=True)['items'])


def _start_background_refresh(config):
    def worker(snapshot, callback):
        global _refresh_running
        _refresh_running = True
        try:
            count = _scan_all_posters(snapshot)
            callback(count, count, f'海报缓存刷新完成：{count}', 'info')
            return {'success':count, 'failed':0, 'total':count}
        finally:
            _refresh_running = False
    return task_state.launch_task('poster_refresh', config, worker, thread_factory=threading.Thread)



def register(app):
    config_path = app.config.get("CONFIG_PATH", CONFIG_PATH)

    @app.route('/api/config', methods=['GET'])
    def config_get():
        config = config_manager.load_config(config_path)
        config["environment_managed"] = managed_media_fields()
        return jsonify(public_config(config))

    @app.route('/api/config', methods=['POST'])
    @require_auth
    def config_post():
        from core.validation import ValidationError
        payload = dict(request.get_json())
        effective = request_config(config_path)
        payload.pop('environment_managed', None)
        for field in managed_media_fields():
            if field in payload and payload[field] != effective[field]:
                raise ValidationError('路径由环境变量管理，请修改环境变量并重启服务')
            payload.pop(field, None)

        def mutate(current):
            try:
                return merge_config(current, payload)
            except ValueError as error:
                raise ValidationError(str(error)) from error
        try:
            config_manager.update_config(mutate, config_path)
        except OSError:
            return jsonify({'status': 'error', 'code': 'config_write_failed',
                            'message': '配置写入失败，原配置已保留'}), 500
        return jsonify({'status': 'success'})

    @app.route('/media_poster/<int:tmdb_id>', defaults={'media_type': None})
    @app.route('/media_poster/<any(movie,tv):media_type>/<int:tmdb_id>')
    def serve_media_poster(tmdb_id, media_type):
        config = request_config(config_path)
        # Hold the primary read lock through opening the selected image response.
        with cache_manager.cache_lock:
            try:
                image = derived_cache.find_poster(media_type, tmdb_id, config)
            except derived_cache.AmbiguousMediaError as error:
                return jsonify({'status': 'error', 'code': 'ambiguous_media', 'message': str(error)}), 409
            if image is None:
                return '', 404
            return send_from_directory(str(image.parent), image.name)

    @app.route('/api/media/poster_cache', methods=['GET'])
    def get_poster_cache_status():
        data = derived_cache.poster_status(request_config(config_path))
        state = task_state.get_task_status()
        return jsonify(dict(data, refreshing=state['running'] and state.get('kind') == 'poster_refresh'))

    @app.route('/api/media/refresh_poster_cache', methods=['POST'])
    @require_auth
    def refresh_poster_cache():
        task = _start_background_refresh(request_config(config_path))
        if task is None:
            return jsonify({"status":"error", "message":"已有写入任务运行或正在停止"}), 409
        return jsonify({"status":"started", "task_id":task.task_id})

    # ========== TMDB 连通性测试 ==========
    @app.route('/api/tmdb/test', methods=['GET'])
    def test_tmdb_connection():
        """测试 TMDB API 连通性"""
        config = config_manager.load_config(config_path)
        api_key = config["tmdb_api"].get("api_key", "")
        if not api_key:
            return jsonify({"status": "error", "message": "TMDB API Key 未配置"}), 400

        language = config["tmdb_api"].get("language", "zh-CN")
        proxy = config.get("tmdb_api", {}).get("proxy")


        try:
            # 使用别名导入，避免与局部变量冲突
            from core.tmdb_client import create_session as tmdb_create_session, _tmdb_limiter
            _tmdb_limiter.wait()
            url = "https://api.themoviedb.org/3/configuration"
            params = {"api_key": api_key}
            session = tmdb_create_session(proxy)
            resp = session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return jsonify({
                    "status": "success",
                    "message": "TMDB 连接正常",
                    "images_base_url": data.get("images", {}).get("secure_base_url", "")
                })
            else:
                error_msg = f"HTTP {resp.status_code}"
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("status_message", error_msg)
                except Exception:
                    pass
                return jsonify({"status": "error", "message": f"TMDB 请求失败: HTTP {resp.status_code}"}), 500
        except Exception as e:
            error_str = str(e)
            if "Connection reset by peer" in error_str or "Connection aborted" in error_str:
                friendly_msg = "网络连接被重置，请检查网络或稍后重试"
            elif "Max retries exceeded" in error_str:
                friendly_msg = "连接 TMDB 超时，请检查网络或代理设置"
            elif "Name or service not known" in error_str:
                friendly_msg = "无法解析 TMDB 域名，请检查 DNS 设置"
            else:
                friendly_msg = "TMDB 连接失败，请检查网络、代理与密钥"
            return jsonify({"status": "error", "message": friendly_msg}), 500
