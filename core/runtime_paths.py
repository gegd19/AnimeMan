"""Resolve runtime storage at call time; migration is an explicit CLI action."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import uuid

CONFIG_NAME = "auto_config.json"
LOG_NAME = "auto_processor_errors.log"
CACHE_NAMES = (
    "auto_processed_cache.json", "ai_parse_cache.json", "folder_ai_parse_cache.json",
    "folder_ai_cache.json", "raw_scan_cache.json", "ai_preparse_cache.json",
    "tmdb_search_cache.json", "media_library_cache.json", "poster_cache.json",
    "tmdb_aliases.json", "recognition_user_rules_v1.json",
)


class MigrationRequired(OSError):
    pass


def _absolute(value):
    return Path(os.path.abspath(Path(value).expanduser()))


def _guard_legacy(destination, name, enabled):
    legacy = Path.cwd() / name
    if enabled and not destination.exists() and legacy.is_file() and legacy.absolute() != destination:
        raise MigrationRequired(
            f"发现旧数据 {legacy}，拒绝在 {destination} 创建空数据。"
            "请停止服务后运行 python -m core.runtime_paths migrate --legacy-dir <旧目录> --apply")
    return destination


def config_file(explicit=None, *, check_legacy=True):
    value = explicit if explicit is not None else os.environ.get("CONFIG_PATH") or CONFIG_NAME
    result = _absolute(value)
    return _guard_legacy(result, CONFIG_NAME, explicit is None and bool(os.environ.get("CONFIG_PATH"))) if check_legacy else result


def cache_file(name, *, check_legacy=True):
    directory = os.environ.get("CACHE_PATH")
    result = _absolute(Path(directory) / name if directory else name)
    return _guard_legacy(result, name, bool(directory)) if check_legacy else result


def log_file(*, check_legacy=True):
    directory = os.environ.get("LOG_PATH")
    result = _absolute(Path(directory) / LOG_NAME if directory else LOG_NAME)
    return _guard_legacy(result, LOG_NAME, bool(directory)) if check_legacy else result


def writable(path):
    """Create parent directories and report the exact failing storage path."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"无法创建运行数据目录 {path.parent}: {exc}") from exc
    return path


def effective_config(config):
    """Environment overrides affect this run, never silently rewrite the file."""
    result = deepcopy(config)
    if "SOURCE_FOLDERS" in os.environ:
        value = os.environ["SOURCE_FOLDERS"].strip()
        if value.startswith("["):
            folders = json.loads(value)
            if not isinstance(folders, list) or any(not isinstance(p, str) or not p.strip() for p in folders):
                raise ValueError("SOURCE_FOLDERS 必须为路径字符串组成的 JSON 数组")
            result["source_folders"] = folders
        elif value:
            result["source_folders"] = [value]
        else:
            result["source_folders"] = []
    for variable, field in (("TV_TARGET_FOLDER", "tv_target_folder"), ("MOVIE_TARGET_FOLDER", "movie_target_folder")):
        if variable in os.environ:
            if not os.environ[variable].strip():
                raise ValueError(f"{variable} 不能为空")
            result[field] = os.environ[variable]
    return result


def managed_media_fields():
    return [field for variable, field in (("SOURCE_FOLDERS", "source_folders"),
            ("TV_TARGET_FOLDER", "tv_target_folder"), ("MOVIE_TARGET_FOLDER", "movie_target_folder"))
            if variable in os.environ]


def migrate_legacy(legacy_dir, *, apply=False):
    """Preflight every source before copying; originals and backups are retained."""
    legacy = _absolute(legacy_dir)
    pairs = [(legacy / CONFIG_NAME, config_file(check_legacy=False))]
    pairs += [(legacy / name, cache_file(name, check_legacy=False)) for name in CACHE_NAMES]
    pairs += [(legacy / LOG_NAME, log_file(check_legacy=False)),
              (legacy / (LOG_NAME + ".1"), Path(str(log_file(check_legacy=False)) + ".1"))]
    pairs += [(path, cache_file(path.name, check_legacy=False))
              for path in legacy.glob("auto_processed_cache.json.t01-*.bak")]
    plan = []
    for source, destination in pairs:
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"迁移源必须是普通文件: {source}")
        data = source.read_bytes()
        if source.suffix == ".json":
            json.loads(data)
        state = "copy"
        if destination.is_symlink():
            raise ValueError(f"迁移目标不能是符号链接: {destination}")
        elif source.resolve() == destination.resolve():
            state = "same_path"
        elif destination.exists():
            if destination.read_bytes() != data:
                raise FileExistsError(f"新旧文件不同，拒绝覆盖: {destination}")
            state = "already_present"
        plan.append({"source": str(source), "destination": str(destination), "state": state})
    if not apply:
        return plan
    created = []
    token = uuid.uuid4().hex
    try:
        for item in plan:
            if item["state"] != "copy":
                continue
            source, destination = Path(item["source"]), Path(item["destination"])
            data = source.read_bytes()
            backup = writable(destination.parent / ".migration-backups" / (source.name + ".pre-t04-" + token + ".bak"))
            with backup.open("xb") as stream:
                stream.write(data)
            writable(destination)
            # Exclusive creation protects a destination appearing after preflight.
            with destination.open("xb") as stream:
                created.append(destination)
                stream.write(data)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return plan


def main():
    parser = argparse.ArgumentParser(description="AnimeMan 运行数据显式迁移（请先停止服务）")
    parser.add_argument("command", choices=["migrate"])
    parser.add_argument("--legacy-dir", required=True)
    parser.add_argument("--apply", action="store_true", help="执行复制；默认仅预览")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate_legacy(args.legacy_dir, apply=args.apply), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"迁移失败: {exc}\n")


if __name__ == "__main__":
    main()
