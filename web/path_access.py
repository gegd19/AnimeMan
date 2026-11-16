"""Request paths are validated as a complete batch before any side effects."""

from pathlib import Path
from flask import g, request

from core.path_safety import absolute_link_path, source_roots, target_roots


class PathAccessError(PermissionError):
    pass


def require_path(value, roots, *, follow=True):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("路径不能为空")
    path = Path(value).resolve() if follow else absolute_link_path(value)
    if not any(path == root or root in path.parents for root in roots):
        raise PathAccessError("Forbidden path")
    return path


def enforce_path_access():
    if not hasattr(g, "request_config"):
        return
    config = g.request_config
    sources = source_roots(config)
    video_sources = source_roots({"source_folders": config.get("source_folders", [])})
    targets = target_roots(config, "subtitle")
    endpoint = request.endpoint
    if endpoint == "get_folder_details":
        require_path(request.args.get("folder"), video_sources)
        return
    if request.method != "POST":
        return
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        if endpoint in {"correct_failed_item", "retry_processed_item", "retry_processed_cache_item",
                        "batch_correct_failed_items", "scan_subtitle_folder", "execute_subtitle",
                        "batch_rename_subtitles", "ai_match_subtitles", "ai_parse_subtitles"}:
            raise ValueError("Expected object")
        return
    if endpoint in {"correct_failed_item", "retry_processed_item", "retry_processed_cache_item"}:
        require_path(data.get("src_path"), video_sources)
    elif endpoint == "batch_correct_failed_items":
        for path in data.get("src_paths", []):
            require_path(path, video_sources)
    elif endpoint == "scan_subtitle_folder":
        folder = data.get("folder") or config.get("subtitle_center", {}).get("default_source_folder")
        if folder:
            require_path(folder, sources)
    elif endpoint == "execute_subtitle":
        for item in data.get("items", []):
            require_path(item["subtitle_path"], sources)
            media = item["target_media"]
            directory = require_path(media["target_dir"], targets)
            video = require_path(media["target_path"], targets, follow=False)
            if video.parent != directory:
                raise PathAccessError("Target directory mismatch")
            require_path(media["target_path"], targets + sources)
    elif endpoint == "batch_rename_subtitles":
        for item in data.get("renames", []):
            require_path(item["old_path"], sources)
            require_path(item["new_path"], sources)
    elif endpoint in {"ai_match_subtitles", "ai_parse_subtitles"}:
        for item in data.get("files", []):
            if isinstance(item, dict) and item.get("path"):
                require_path(item["path"], sources)
