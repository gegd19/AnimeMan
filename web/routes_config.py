#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置相关 API 路由 + 媒体海报服务（带缓存优化）
- TMDB 测试端点优化：返回简洁友好的中文错误提示
- 修复 create_session 导入冲突
"""

import json
import threading
import time
from pathlib import Path
from flask import request, jsonify, send_from_directory
from core import config_manager, cache_manager
from .auth import require_auth

CONFIG_PATH = "auto_config.json"

# 海报缓存
_poster_cache = {}
_poster_cache_lock = threading.RLock()
POSTER_CACHE_FILE = "poster_cache.json"

_refresh_running = False
_refresh_lock = threading.Lock()


def _load_poster_cache():
    global _poster_cache
    cache_path = Path(POSTER_CACHE_FILE)
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                _poster_cache = json.load(f)
        except Exception:
            _poster_cache = {}
    else:
        _poster_cache = {}


def _save_poster_cache():
    with _poster_cache_lock:
        temp_file = POSTER_CACHE_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(_poster_cache, f, ensure_ascii=False, indent=2)
        Path(temp_file).replace(POSTER_CACHE_FILE)


def _scan_all_posters():
    cache = cache_manager.load_cache()
    new_cache = {}
    processed_dirs = set()

    for src_str, entry in cache.items():
        if entry.get("media_type") == "failed":
            continue

        target = Path(entry.get("target", ""))
        if not target.exists():
            continue

        tmdb_id = entry.get("tmdb_id")
        if not tmdb_id:
            continue

        if entry.get("media_type") == "movie":
            media_dir = target.parent
        else:
            media_dir = target.parent.parent

        dir_key = str(media_dir)
        if dir_key in processed_dirs:
            continue
        processed_dirs.add(dir_key)

        poster_path = None
        fanart_path = None

        for img in media_dir.glob("poster.*"):
            if img.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                poster_path = str(img)
                break

        for img in media_dir.glob("fanart.*"):
            if img.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                fanart_path = str(img)
                break

        if poster_path or fanart_path:
            new_cache[str(tmdb_id)] = {
                "poster_path": poster_path,
                "fanart_path": fanart_path,
                "updated": time.time()
            }

    with _poster_cache_lock:
        _poster_cache.clear()
        _poster_cache.update(new_cache)
    _save_poster_cache()
    return len(new_cache)


def _background_refresh():
    global _refresh_running
    try:
        count = _scan_all_posters()
        print(f"[PosterCache] 后台刷新完成，缓存 {count} 个海报")
    except Exception as e:
        print(f"[PosterCache] 后台刷新失败: {e}")
    finally:
        with _refresh_lock:
            _refresh_running = False


def _start_background_refresh():
    global _refresh_running
    with _refresh_lock:
        if _refresh_running:
            return False
        _refresh_running = True
    threading.Thread(target=_background_refresh, daemon=True).start()
    return True


_load_poster_cache()


def register(app):
    @app.route('/api/config', methods=['GET'])
    def config_get():
        config = config_manager.load_config(CONFIG_PATH)
        # 返回配置时，对于 auth.password 字段，返回空字符串（前端密码框留空，但保存时不覆盖）
        safe_config = config.copy()
        if 'auth' in safe_config:
            safe_config['auth'] = safe_config['auth'].copy()
            # 如果密码存在，则返回空字符串（前端显示为空，用户不修改则保持原密码）
            safe_config['auth']['password'] = ''
        return jsonify(safe_config)

    @app.route('/api/config', methods=['POST'])
    @require_auth
    def config_post():
        try:
            new_config = request.json
            merged = config_manager.load_config(CONFIG_PATH)

            # 处理认证密码：如果新配置中密码为空，则保留原密码
            if 'auth' in new_config and 'auth' in merged:
                if not new_config['auth'].get('password'):
                    # 保持原有密码
                    new_config['auth']['password'] = merged['auth'].get('password', '')

            for k, v in new_config.items():
                if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v

            config_manager.save_config(merged, CONFIG_PATH)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @app.route('/media_poster/<int:tmdb_id>')
    def serve_media_poster(tmdb_id):
        with _poster_cache_lock:
            cached = _poster_cache.get(str(tmdb_id))

        if cached:
            poster_path = cached.get("poster_path")
            fanart_path = cached.get("fanart_path")
            if poster_path and Path(poster_path).exists():
                img_path = Path(poster_path)
                return send_from_directory(str(img_path.parent), img_path.name)
            if fanart_path and Path(fanart_path).exists():
                img_path = Path(fanart_path)
                return send_from_directory(str(img_path.parent), img_path.name)

        cache = cache_manager.load_cache()
        for src_str, entry in cache.items():
            if entry.get("tmdb_id") == tmdb_id:
                target = Path(entry.get("target", ""))
                if target.exists():
                    media_type = entry.get("media_type")
                    if media_type == "tv":
                        show_dir = target.parent.parent
                    elif media_type == "movie":
                        show_dir = target.parent
                    else:
                        continue

                    for img_name in ["poster.jpg", "fanart.jpg"]:
                        img_path = show_dir / img_name
                        if img_path.exists():
                            return send_from_directory(str(img_path.parent), img_path.name)

        return "", 404

    @app.route('/api/media/poster_cache', methods=['GET'])
    def get_poster_cache_status():
        with _poster_cache_lock:
            count = len(_poster_cache)
        return jsonify({
            "cached_count": count,
            "refreshing": _refresh_running
        })

    @app.route('/api/media/refresh_poster_cache', methods=['POST'])
    @require_auth
    def refresh_poster_cache():
        if _start_background_refresh():
            return jsonify({"status": "started"})
        else:
            return jsonify({"status": "already_running"})

    # ========== TMDB 连通性测试 ==========
    @app.route('/api/tmdb/test', methods=['GET'])
    def test_tmdb_connection():
        """测试 TMDB API 连通性"""
        config = config_manager.load_config(CONFIG_PATH)
        api_key = config["tmdb_api"].get("api_key", "")
        if not api_key:
            return jsonify({"status": "error", "message": "TMDB API Key 未配置"}), 400

        language = config["tmdb_api"].get("language", "zh-CN")
        proxy = config.get("tmdb_api", {}).get("proxy")
        print(f"[ROUTE] 测试连通性读取的代理: {proxy}")

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
                return jsonify({"status": "error", "message": error_msg}), 500
        except Exception as e:
            error_str = str(e)
            if "Connection reset by peer" in error_str or "Connection aborted" in error_str:
                friendly_msg = "网络连接被重置，请检查网络或稍后重试"
            elif "Max retries exceeded" in error_str:
                friendly_msg = "连接 TMDB 超时，请检查网络或代理设置"
            elif "Name or service not known" in error_str:
                friendly_msg = "无法解析 TMDB 域名，请检查 DNS 设置"
            else:
                friendly_msg = f"TMDB 连接失败: {error_str[:100]}..."
            return jsonify({"status": "error", "message": friendly_msg}), 500
