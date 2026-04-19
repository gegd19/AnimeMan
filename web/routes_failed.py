#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
失败缓存管理 API
- 异步批量修正任务，带进度反馈和异常保护
- 支持绝对集数跨季自动换算（排除特典季）
- 包含 TMDB 搜索代理（仅缓存有效结果）
- 包含文件夹详情查询（查看文件夹内所有视频文件状态）
- 所有 TMDB 请求均支持代理
"""

import threading
from pathlib import Path
from flask import request, jsonify
from core import cache_manager, config_manager
from core.tmdb_client import search_tmdb_multi, build_image_url, get_tmdb_details, get_tv_season_episodes
from core.media_processor import (
    cleanup_previous_artifacts,
    process_video_with_manual_correction,
    process_video
)
from .task_state import (
    progress_callback,
    is_task_running,
    set_task_running,
    reset_task_state,
    should_stop,
    clear_stop_flag
)

CONFIG_PATH = "auto_config.json"


def _wrap_callback(cb):
    """将 progress_callback 包装为兼容 (msg, level) 的 log_func"""
    if cb is None:
        return None

    def wrapped(current_or_msg, total_or_level=None, msg=None, level=None):
        if msg is not None and level is not None:
            cb(current_or_msg, total_or_level, msg, level)
        else:
            cb(0, 0, current_or_msg, total_or_level or "info")
    return wrapped


def register(app):
    @app.route('/api/failed_cache', methods=['GET'])
    def get_failed_cache():
        """获取所有处理失败的文件记录"""
        try:
            cache = cache_manager.load_cache()
            failed_items = []
            for src_str, entry in cache.items():
                if entry.get("media_type") == "failed":
                    path = Path(src_str)
                    failed_items.append({
                        "path": src_str,
                        "name": path.name,
                        "reason": entry.get("failed_reason", "未知原因"),
                        "failed_time": entry.get("failed_time", 0)
                    })
            failed_items.sort(key=lambda x: x.get("failed_time", 0), reverse=True)
            return jsonify({"failed": failed_items})
        except Exception as e:
            return jsonify({"failed": [], "error": str(e)}), 500

    @app.route('/api/failed_cache/clusters', methods=['GET'])
    def get_failed_clusters():
        """获取按文件夹聚类的失败缓存"""
        try:
            cache = cache_manager.load_cache()
            clusters = {}

            for src_str, entry in cache.items():
                if entry.get("media_type") != "failed":
                    continue
                folder = str(Path(src_str).parent)
                if folder not in clusters:
                    clusters[folder] = []
                clusters[folder].append({
                    "path": src_str,
                    "name": Path(src_str).name,
                    "reason": entry.get("failed_reason", "未知原因"),
                    "failed_time": entry.get("failed_time", 0)
                })

            cluster_list = []
            for folder, files in clusters.items():
                files.sort(key=lambda x: x.get("failed_time", 0), reverse=True)
                cluster_list.append({
                    "folder": folder,
                    "count": len(files),
                    "files": files
                })

            cluster_list.sort(key=lambda x: x["count"], reverse=True)
            return jsonify({"clusters": cluster_list})
        except Exception as e:
            return jsonify({"clusters": [], "error": str(e)}), 500

    @app.route('/api/failed_cache/clear', methods=['POST'])
    def clear_failed_cache():
        """清空所有失败的缓存记录"""
        try:
            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                keys_to_remove = [k for k, v in cache.items() if v.get("media_type") == "failed"]
                for k in keys_to_remove:
                    del cache[k]
                cache_manager.save_cache(cache)
            return jsonify({"status": "success", "removed": len(keys_to_remove)})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/failed_cache/folder_details', methods=['GET'])
    def get_folder_details():
        """
        获取指定文件夹内所有视频文件的处理详情（含成功与失败）。
        用于在失败缓存聚类中查看整个文件夹的文件状态，方便批量纠错。
        """
        folder_path = request.args.get('folder', '')
        if not folder_path:
            return jsonify({"status": "error", "message": "缺少 folder 参数"}), 400

        folder = Path(folder_path)
        if not folder.exists():
            return jsonify({"status": "error", "message": "文件夹不存在"}), 404

        config = config_manager.load_config(CONFIG_PATH)
        video_exts = {ext.lower() for ext in config.get("video_extensions", [])}

        # 1. 扫描文件夹内所有视频文件（含一级子目录）
        all_video_files = []
        for ext in video_exts:
            for f in folder.glob(f"*{ext}"):
                if f.is_file():
                    all_video_files.append(f)
            # 同时扫描一级子目录（如 Season 1/ 等）
            for sub_dir in folder.iterdir():
                if sub_dir.is_dir() and not sub_dir.name.startswith('.'):
                    for f in sub_dir.glob(f"*{ext}"):
                        if f.is_file():
                            all_video_files.append(f)

        # 去重（基于解析后的绝对路径）
        seen = set()
        unique_files = []
        for f in all_video_files:
            abs_path = str(f.resolve())
            if abs_path not in seen:
                seen.add(abs_path)
                unique_files.append(f)

        # 2. 加载缓存，关联处理状态
        cache = cache_manager.load_cache()
        file_details = []

        for f in unique_files:
            abs_path = str(f.resolve())
            entry = cache.get(abs_path)

            if entry and entry.get("media_type") != "failed":
                # 已成功处理
                target = entry.get("target", "")
                file_details.append({
                    "path": abs_path,
                    "name": f.name,
                    "status": "success",
                    "media_type": entry.get("media_type"),
                    "title": entry.get("title", ""),
                    "season": entry.get("season"),
                    "episode": entry.get("episode"),
                    "year": entry.get("year"),
                    "confidence": entry.get("confidence", 0),
                    "target": target,
                    "target_exists": Path(target).exists() if target else False,
                    "processed_time": entry.get("processed_time", 0)
                })
            elif entry and entry.get("media_type") == "failed":
                # 失败记录
                file_details.append({
                    "path": abs_path,
                    "name": f.name,
                    "status": "failed",
                    "reason": entry.get("failed_reason", "未知原因"),
                    "failed_time": entry.get("failed_time", 0)
                })
            else:
                # 尚未处理过（不在缓存中）
                file_details.append({
                    "path": abs_path,
                    "name": f.name,
                    "status": "unknown",
                    "reason": "未处理"
                })

        # 按文件名排序（便于用户查看）
        file_details.sort(key=lambda x: x["name"])

        return jsonify({
            "folder": str(folder),
            "total": len(file_details),
            "files": file_details
        })

    @app.route('/api/tmdb/search_proxy', methods=['GET'])
    def tmdb_search_proxy():
        """
        TMDB 搜索代理，供前端手动修正时使用。
        关键优化：仅当请求成功且有结果时才写入缓存，避免网络故障时缓存空结果。
        """
        query = request.args.get('query', '')
        media_type = request.args.get('media_type', 'tv')
        year = request.args.get('year', '')
        if not query:
            return jsonify({"results": []})

        # ---------- 1. 尝试从缓存读取 ----------
        from core import tmdb_cache
        cached_data = tmdb_cache.get_cached_result(query, media_type, year)
        if cached_data is not None:
            return jsonify(cached_data)

        config = config_manager.load_config(CONFIG_PATH)
        api_key = config["tmdb_api"]["api_key"]
        language = config["tmdb_api"].get("language", "zh-CN")
        base_url = config["image_base_url"]
        proxy = config.get("tmdb_api", {}).get("proxy")

        # ---------- 2. 真实请求 TMDB ----------
        formatted = []
        request_success = False
        error_msg = None

        try:
            raw_results = search_tmdb_multi(
                media_type, query, year, api_key, language, log_func=None, proxy=proxy
            )
            request_success = True  # API 调用成功，无网络异常
        except Exception as e:
            error_msg = f"TMDB 请求失败: {str(e)}"
            return jsonify({"results": [], "error": error_msg}), 500

        # ---------- 3. 格式化搜索结果 ----------
        for item in raw_results[:10]:
            tmdb_id = item.get("id")
            title = item.get("title") or item.get("name")
            item_year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
            overview = item.get("overview", "")[:100]
            poster_path = item.get("poster_path")

            result_item = {
                "id": tmdb_id,
                "title": title,
                "year": item_year,
                "media_type": media_type,
                "overview": overview,
                "poster_url": build_image_url(base_url, poster_path, "w200") if poster_path else None
            }

            # 剧集额外获取季详情（仅前5个）
            if media_type == "tv" and len(formatted) < 5:
                try:
                    details = get_tmdb_details(
                        media_type, tmdb_id, api_key, language,
                        include_alternative_titles=False, proxy=proxy
                    )
                    if details:
                        seasons = details.get("seasons", [])
                        seasons_detail = []
                        regular_seasons = []
                        for s in seasons:
                            sn = s.get("season_number", 0)
                            if sn > 0:
                                regular_seasons.append(s)
                                seasons_detail.append({
                                    "season_number": sn,
                                    "name": s.get("name") or f"第{sn}季",
                                    "episode_count": s.get("episode_count", 0)
                                })
                        special_season = next((s for s in seasons if s.get("season_number") == 0), None)
                        if special_season and special_season.get("episode_count", 0) > 0:
                            seasons_detail.append({
                                "season_number": 0,
                                "name": special_season.get("name") or "特辑",
                                "episode_count": special_season.get("episode_count", 0)
                            })
                        seasons_detail.sort(key=lambda x: x["season_number"])
                        result_item["seasons_count"] = len(regular_seasons)
                        result_item["episodes_count"] = sum(s.get("episode_count", 0) for s in regular_seasons)
                        result_item["seasons_detail"] = seasons_detail
                    else:
                        result_item["seasons_count"] = None
                        result_item["episodes_count"] = None
                        result_item["seasons_detail"] = []
                except Exception:
                    result_item["seasons_count"] = None
                    result_item["episodes_count"] = None
                    result_item["seasons_detail"] = []
            else:
                result_item["seasons_count"] = None
                result_item["episodes_count"] = None
                result_item["seasons_detail"] = []

            formatted.append(result_item)

        response_data = {"results": formatted}

        # ---------- 4. 仅当请求成功且有结果时才写入缓存 ----------
        if request_success and formatted:
            tmdb_cache.set_cached_result(query, media_type, year, response_data)

        return jsonify(response_data)

    @app.route('/api/failed_cache/correct', methods=['POST'])
    def correct_failed_item():
        """手动修正失败项并重新处理（单文件）"""
        try:
            data = request.json
            src_path = data.get('src_path')
            tmdb_id = data.get('tmdb_id')
            media_type = data.get('media_type', 'tv')
            season = data.get('season')
            episode = data.get('episode')

            if not src_path or not tmdb_id:
                return jsonify({"status": "error", "message": "缺少必要参数"}), 400

            src = Path(src_path)
            if not src.exists():
                return jsonify({"status": "error", "message": "源文件不存在"}), 404

            config = config_manager.load_config(CONFIG_PATH)
            cleanup_previous_artifacts(src, config)

            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                if src_path in cache:
                    del cache[src_path]

            wrapped_progress = _wrap_callback(progress_callback)
            success = process_video_with_manual_correction(
                src, config, cache, tmdb_id, media_type, season, episode, wrapped_progress
            )

            if success:
                with cache_manager.cache_lock:
                    cache_manager.save_cache(cache)
                return jsonify({"status": "success"})
            else:
                return jsonify({"status": "error", "message": "重新处理失败，请查看日志"}), 500

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"服务器内部错误: {str(e)}"}), 500

    @app.route('/api/failed_cache/batch_correct', methods=['POST'])
    def batch_correct_failed_items():
        """
        批量手动修正失败项（异步任务，支持自动跨季换算）
        前端可轮询 /api/status 获取实时进度和日志
        """
        try:
            data = request.json
            src_paths = data.get('src_paths', [])
            tmdb_id = data.get('tmdb_id')
            media_type = data.get('media_type', 'tv')
            season = data.get('season')                  # 允许为 None，表示自动换算
            start_episode = data.get('start_episode', 1)
            episode_increment = data.get('episode_increment', 1)

            if not src_paths or not tmdb_id:
                return jsonify({"status": "error", "message": "缺少必要参数"}), 400

            if is_task_running():
                return jsonify({
                    "status": "error",
                    "message": "已有任务在运行中。如果确定没有任务，请双击「停止任务」强制重置。"
                }), 409

            set_task_running()
            clear_stop_flag()
            progress_callback(0, len(src_paths), "开始批量手动修正...", "info")

            def batch_task():
                try:
                    config = config_manager.load_config(CONFIG_PATH)
                    api_key = config["tmdb_api"]["api_key"]
                    language = config["tmdb_api"].get("language", "zh-CN")
                    proxy = config.get("tmdb_api", {}).get("proxy")
                    wrapped_progress = _wrap_callback(progress_callback)

                    # 自动跨季换算模式：获取 TMDB 季结构
                    season_episode_counts = {}
                    cumulative_map = {}
                    auto_mode = (media_type == 'tv' and season is None)

                    # 初始化固定季号变量（如果自动模式失败将回退）
                    fixed_season = 1

                    if auto_mode:
                        try:
                            details = get_tmdb_details(
                                "tv", tmdb_id, api_key, language,
                                include_alternative_titles=False, proxy=proxy
                            )
                            if details:
                                regular_seasons = [s for s in details.get("seasons", [])
                                                   if s.get("season_number", 0) > 0]
                                cumulative = 0
                                for s in sorted(regular_seasons, key=lambda x: x["season_number"]):
                                    sn = s["season_number"]
                                    ep_count = s.get("episode_count", 0)
                                    if ep_count > 0:
                                        season_episode_counts[sn] = ep_count
                                        cumulative_map[cumulative + 1] = (sn, cumulative)
                                        cumulative += ep_count
                                progress_callback(0, len(src_paths),
                                                  f"📊 已获取剧集季结构: {season_episode_counts}", "info")
                        except Exception as e:
                            progress_callback(0, len(src_paths),
                                              f"⚠️ 获取季结构失败，将使用固定季号 (S01): {e}", "warning")
                            auto_mode = False
                            fixed_season = 1

                    success_count = 0
                    current_absolute_ep = start_episode

                    with cache_manager.cache_lock:
                        cache = cache_manager.load_cache()

                    for idx, src_path in enumerate(src_paths):
                        # 检查是否请求停止
                        if should_stop():
                            progress_callback(idx, len(src_paths), "⏹️ 用户停止了批量修正任务", "warning")
                            break

                        src = Path(src_path)
                        if not src.exists():
                            progress_callback(idx + 1, len(src_paths), f"⚠️ 文件不存在: {src.name}", "warning")
                            continue

                        # 确定当前文件的季和集
                        if auto_mode:
                            target_abs = current_absolute_ep
                            found_season = None
                            found_episode = None
                            for start_abs, (sn, cum_base) in sorted(cumulative_map.items()):
                                if target_abs >= start_abs:
                                    ep_count = season_episode_counts.get(sn, 0)
                                    if target_abs <= cum_base + ep_count:
                                        found_season = sn
                                        found_episode = target_abs - cum_base
                                        break
                            if found_season is None:
                                progress_callback(idx + 1, len(src_paths),
                                                  f"⚠️ 绝对集号 {target_abs} 超出范围，跳过: {src.name}", "warning")
                                continue
                            current_season = found_season
                            current_episode = found_episode
                            progress_callback(idx + 1, len(src_paths),
                                              f"🔄 绝对集号 {target_abs} → S{current_season:02d}E{current_episode:02d}: {src.name}", "info")
                            current_absolute_ep += episode_increment
                        else:
                            current_season = season if season is not None else fixed_season
                            current_episode = start_episode + idx * episode_increment

                        progress_callback(idx + 1, len(src_paths), f"🔄 处理: {src.name}", "info")

                        cleanup_previous_artifacts(src, config)

                        with cache_manager.cache_lock:
                            if src_path in cache:
                                del cache[src_path]

                        success = process_video_with_manual_correction(
                            src, config, cache, tmdb_id, media_type,
                            current_season, current_episode, wrapped_progress
                        )
                        if success:
                            success_count += 1
                            progress_callback(idx + 1, len(src_paths), f"✅ 成功: {src.name}", "success")
                        else:
                            progress_callback(idx + 1, len(src_paths), f"❌ 失败: {src.name}", "error")

                    with cache_manager.cache_lock:
                        cache_manager.save_cache(cache)

                    if should_stop():
                        progress_callback(len(src_paths), len(src_paths),
                                         f"批量修正已中止，成功处理 {success_count}/{len(src_paths)}", "warning")
                    else:
                        progress_callback(len(src_paths), len(src_paths),
                                         f"批量修正完成！成功 {success_count}/{len(src_paths)}", "success")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    progress_callback(0, len(src_paths), f"❌ 批量修正任务异常: {e}", "error")
                finally:
                    # 确保无论成功、失败、停止，都重置任务状态
                    reset_task_state()
                    clear_stop_flag()

            threading.Thread(target=batch_task, daemon=True).start()
            return jsonify({"status": "started", "total": len(src_paths)})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/processed_history', methods=['GET'])
    def get_processed_history():
        """返回所有成功处理的文件记录，含准确率，支持排序，最多返回300条"""
        sort_by = request.args.get('sort', 'processed_time')
        order = request.args.get('order', 'desc')
        limit = 300

        cache = cache_manager.load_cache()
        history = []
        for src_str, entry in cache.items():
            if entry.get("media_type") == "failed":
                continue
            target = Path(entry.get("target", ""))
            item = {
                "src": src_str,
                "src_name": Path(src_str).name,
                "target": str(target),
                "title": entry.get("title", ""),
                "media_type": entry.get("media_type"),
                "season": entry.get("season"),
                "episode": entry.get("episode"),
                "confidence": entry.get("confidence", 0),
                "processed_time": entry.get("processed_time", 0)
            }
            history.append(item)

        reverse = (order == 'desc')
        if sort_by == 'src_name':
            history.sort(key=lambda x: x['src_name'].lower(), reverse=reverse)
        else:
            history.sort(key=lambda x: x['processed_time'], reverse=reverse)

        history = history[:limit]
        return jsonify({"history": history})

    @app.route('/api/processed/retry', methods=['POST'])
    def retry_processed_item():
        """对已成功处理的文件进行重新处理"""
        try:
            data = request.json
            src_path = data.get('src_path')
            if not src_path:
                return jsonify({"status": "error", "message": "缺少源文件路径"}), 400

            src = Path(src_path)
            if not src.exists():
                return jsonify({"status": "error", "message": "源文件不存在"}), 404

            config = config_manager.load_config(CONFIG_PATH)
            cleanup_previous_artifacts(src, config)

            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                if src_path in cache:
                    del cache[src_path]
                    cache_manager.save_cache(cache)

            wrapped_progress = _wrap_callback(progress_callback)
            temp_cache = {}
            success = process_video(src, config, temp_cache, wrapped_progress)

            if success:
                with cache_manager.cache_lock:
                    cache = cache_manager.load_cache()
                    cache.update(temp_cache)
                    cache_manager.save_cache(cache)
                return jsonify({"status": "success"})
            else:
                return jsonify({"status": "error", "message": "重新处理失败，请查看日志"}), 500

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"服务器内部错误: {str(e)}"}), 500
