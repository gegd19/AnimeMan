"""Offline anime databases as a bridge from a release name to a TMDB season and episode.

People identify a release by first finding the work in an anime database (where romaji spellings,
English and Chinese names and every season as its own entry live), then translating that entry to
TMDB's season structure. This module does the same with three public datasets:

* manami-project/anime-offline-database (ODbL 1.0 + DbCL 1.0): titles, synonyms, type, year,
  episode count and length, with AniList / MyAnimeList / AniDB ids.
* bangumi-data (CC BY 4.0): Japanese, Chinese and English names, broadcast start, Bangumi ids and a
  TMDB link that names the TMDB season and first episode of each cour.
* anibridge/anibridge-mappings (MIT): episode ranges from AniList / MAL / AniDB entries to TMDB seasons.

The data is downloaded only on request (or by the weekly refresh once it exists) and indexed into
SQLite. Processing never reaches the network here, except the opt-in paid web search fallback.
A match is used only when every remaining candidate agrees on one TMDB show, season and episode.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests

from .failure_policy import note_error
from .log_redaction import redact
from .logger import get_logger

logger = get_logger(__name__)

LOG_INFO, LOG_SUCCESS, LOG_WARNING = "info", "success", "warning"
SCHEMA_VERSION = 2
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024

SOURCES = {
    "manami": {
        "file": "manami.json",
        "label": "manami anime-offline-database",
        "license": "ODbL 1.0 + DbCL 1.0",
        "urls": ["https://github.com/manami-project/anime-offline-database/releases/latest/download/anime-offline-database-minified.json"],
    },
    "anibridge": {
        "file": "anibridge.json",
        "label": "anibridge-mappings",
        "license": "MIT",
        "urls": ["https://github.com/anibridge/anibridge-mappings/releases/download/v3/mappings.min.json"],
    },
    "bangumi": {
        "file": "bangumi.json",
        "label": "bangumi-data",
        "license": "CC BY 4.0",
        "urls": ["https://cdn.jsdelivr.net/npm/bangumi-data@0/dist/data.json",
                 "https://unpkg.com/bangumi-data@0/dist/data.json",
                 "https://raw.githubusercontent.com/bangumi-data/bangumi-data/master/dist/data.json"],
    },
}

_update_lock = threading.Lock()
_update_state: Dict[str, Any] = {"running": False, "message": "", "error": None}
_local = threading.local()
_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {"folders": {}, "searches": 0, "search_cache": {}}


# ---------------------------------------------------------------- settings and paths

def settings(config: Dict[str, Any]) -> Dict[str, Any]:
    raw = config.get("anime_db") if isinstance(config.get("anime_db"), dict) else {}
    web = raw.get("web_search") if isinstance(raw.get("web_search"), dict) else {}
    return {
        "enabled": raw.get("enabled", True) is True,
        "update_days": raw.get("update_days", 7) if type(raw.get("update_days", 7)) is int else 7,
        "urls": raw.get("urls") if isinstance(raw.get("urls"), dict) else {},
        "proxy": raw.get("proxy") or (config.get("tmdb_api") or {}).get("proxy") or None,
        "web_search": {"enabled": web.get("enabled", False) is True,
                       "max_per_run": web.get("max_per_run", 30) if type(web.get("max_per_run", 30)) is int else 30},
    }


def data_dir() -> Path:
    override = os.environ.get("ANIME_DB_PATH")
    if override:
        return Path(override)
    from .runtime_paths import cache_file
    return Path(cache_file("anime_db", check_legacy=False))


def index_path() -> Path:
    return data_dir() / "index.sqlite"


def status() -> Dict[str, Any]:
    meta_file = data_dir() / "meta.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return {"available": index_path().is_file(), "meta": meta,
            "updating": _update_state["running"], "message": _update_state["message"], "error": _update_state["error"],
            "sources": {k: {"label": v["label"], "license": v["license"]} for k, v in SOURCES.items()}}


# ---------------------------------------------------------------- text helpers

def fold(text: Any) -> str:
    """Case, width and punctuation insensitive key."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[\W_]+", "", text)


def loose(text: Any) -> str:
    """fold() that also ignores how long vowels are romanised (Shoukanjuu / Shokanju)."""
    key = fold(text)
    for a, b in (("ou", "o"), ("uu", "u"), ("oo", "o"), ("ā", "a"), ("ō", "o"), ("ū", "u")):
        key = key.replace(a, b)
    return key


_HEAD_SPLIT = re.compile(r"\s*(?:[:：~〜～]|\s-\s|\s–\s)\s*")
_SEQUEL_WORDS = re.compile(r"(?i)(?:\b(?:season|part|cour|act)\s*\d|\b\d+(?:st|nd|rd|th)\s+season|\b(?:II|III|IV|V|VI)\b|第\s*[\d一二三四五六七八九十]+\s*[季期部]|\s\d{1,2}$)")
_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
_ROMAN = {2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}


def season_titles(title: str, season: int) -> List[str]:
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(season, f"{season}th")
    cn = _CN.get(season, str(season))
    return [f"{title} Season {season}", f"{title} {ordinal} Season", f"{title} {season}", f"{title} {_ROMAN.get(season, season)}",
            f"{title} S{season}", f"{title} 第{season}季", f"{title} 第{cn}季", f"{title} 第{season}期", f"{title}（第{season}期）",
            f"{title} ({ordinal} Season)", f"{title}(第{season}期)"]


def stated_season(src: Path) -> Optional[int]:
    """A season the name actually states (not the parser's default season 1)."""
    from .parser_regex import explicit_season_number
    for text in (src.stem, src.parent.name):
        value = explicit_season_number(text)
        if value is not None:
            return value
        match = re.search(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)\s+season\b", text)
        if match:
            return int(match.group(1))
    return None


# ---------------------------------------------------------------- download and index

def _download(urls: Iterable[str], target: Path, proxy: Optional[str], log: Optional[Callable]) -> Tuple[bool, str]:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    last = ""
    for url in urls:
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with requests.get(url, stream=True, timeout=(15, 120), proxies=proxies) as resp:
                resp.raise_for_status()
                size = 0
                with open(tmp, "wb") as handle:
                    for chunk in resp.iter_content(1 << 20):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise ValueError("下载文件过大")
                        handle.write(chunk)
            os.replace(tmp, target)
            return True, url
        except Exception as error:  # try the next mirror
            note_error(error)
            last = f"{url}: {redact(error)}"
            if log:
                log(f"⚠️ 下载失败，尝试下一个地址：{last}", LOG_WARNING)
            try:
                tmp.unlink()
            except OSError:
                pass
    return False, last


def update(config: Dict[str, Any], log: Optional[Callable] = None) -> Dict[str, Any]:
    """Download the three datasets (keeping old copies when a download fails) and rebuild the index."""
    if not _update_lock.acquire(blocking=False):
        return {"started": False, "message": "番剧数据库正在更新"}
    _update_state.update(running=True, message="正在下载番剧数据库…", error=None)
    try:
        opts = settings(config)
        folder = data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        report = {}
        for name, source in SOURCES.items():
            override = opts["urls"].get(name)
            urls = ([override] if isinstance(override, str) and override.startswith(("http://", "https://")) else []) + source["urls"]
            _update_state["message"] = f"正在下载 {source['label']}…"
            ok, used = _download(urls, folder / source["file"], opts["proxy"], log)
            report[name] = {"ok": ok, "url": used if ok else None, "error": None if ok else used,
                            "kept_previous": (not ok) and (folder / source["file"]).is_file()}
        if not any((folder / s["file"]).is_file() for s in SOURCES.values()):
            raise RuntimeError("没有可用的番剧数据：" + "；".join(r["error"] or "" for r in report.values()))
        _update_state["message"] = "正在建立索引…"
        counts = build_index({name: folder / s["file"] for name, s in SOURCES.items()}, index_path())
        meta = {"schema": SCHEMA_VERSION, "updated_at": int(time.time()), "counts": counts, "sources": report}
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        _update_state.update(message=f"番剧数据库已更新：{counts['works']} 部作品", error=None)
        if log:
            log(f"📚 番剧数据库已更新：{counts['works']} 部作品，{counts['titles']} 个名称", LOG_SUCCESS)
        return {"started": True, **meta}
    except Exception as error:
        note_error(error)
        _update_state.update(message="番剧数据库更新失败", error=redact(error))
        logger.warning(f"番剧数据库更新失败: {error}")
        if log:
            log(f"⚠️ 番剧数据库更新失败：{redact(error)}", LOG_WARNING)
        return {"started": True, "error": redact(error)}
    finally:
        _update_state["running"] = False
        _update_lock.release()


def update_in_background(config: Dict[str, Any], log: Optional[Callable] = None) -> bool:
    if _update_state["running"]:
        return False
    threading.Thread(target=update, args=(config, log), name="anime-db-update", daemon=True).start()
    return True


def maybe_refresh(config: Dict[str, Any], log: Optional[Callable] = None) -> bool:
    """Weekly refresh, only for data the user has already downloaded once."""
    opts = settings(config)
    if not opts["enabled"] or opts["update_days"] <= 0 or not index_path().is_file():
        return False
    try:
        updated = json.loads((data_dir() / "meta.json").read_text(encoding="utf-8")).get("updated_at", 0)
    except (OSError, ValueError):
        updated = 0
    if time.time() - updated < opts["update_days"] * 86400:
        return False
    return update_in_background(config, log)


def _manami_entries(path: Path):
    """Stream the entries of manami's 60 MB file without building the whole document at once."""
    text = path.read_text(encoding="utf-8")
    start = text.find('"data"')
    if start < 0:
        return
    pos = text.index("[", start) + 1
    decoder = json.JSONDecoder()
    length = len(text)
    while pos < length:
        while pos < length and text[pos] in " \r\n\t,":
            pos += 1
        if pos >= length or text[pos] == "]":
            return
        entry, pos = decoder.raw_decode(text, pos)
        yield entry


_ID_PATTERNS = (("anilist", re.compile(r"anilist\.co/anime/(\d+)")), ("mal", re.compile(r"myanimelist\.net/anime/(\d+)")),
                ("anidb", re.compile(r"anidb\.net/(?:anime/|a)(\d+)")), ("bgm", re.compile(r"bangumi\.tv/subject/(\d+)|bgm\.tv/subject/(\d+)")))


def ids_from_urls(urls: Iterable[str]) -> List[str]:
    found = []
    for url in urls:
        for provider, pattern in _ID_PATTERNS:
            match = pattern.search(url or "")
            if match:
                key = f"{provider}:{next(g for g in match.groups() if g)}"
                if key not in found:
                    found.append(key)
    return found


def build_index(files: Dict[str, Path], target: Path) -> Dict[str, int]:
    parent: Dict[str, str] = {}

    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(keys):
        keys = list(keys)
        for other in keys[1:]:
            a, b = find(keys[0]), find(other)
            if a != b:
                parent[b] = a

    records: List[Dict[str, Any]] = []
    manami_file, bangumi_file, bridge_file = files.get("manami"), files.get("bangumi"), files.get("anibridge")
    if manami_file and Path(manami_file).is_file():
        for entry in _manami_entries(Path(manami_file)):
            ids = ids_from_urls(entry.get("sources") or [])
            if not ids:
                continue
            duration = entry.get("duration") or {}
            seconds = duration.get("value") if duration.get("unit", "SECONDS") == "SECONDS" else None
            records.append({"ids": ids, "titles": [entry.get("title")] + list(entry.get("synonyms") or []),
                            "type": entry.get("type"), "episodes": entry.get("episodes"),
                            "year": (entry.get("animeSeason") or {}).get("year"), "duration": seconds,
                            "name": entry.get("title")})
    if bangumi_file and Path(bangumi_file).is_file():
        data = json.loads(Path(bangumi_file).read_text(encoding="utf-8"))
        items = data.get("items", []) if isinstance(data, dict) else data
        keymap = {"bangumi": "bgm", "mal": "mal", "aniList": "anilist", "anidb": "anidb"}
        for item in items:
            ids, tmdb = [], []
            for site in item.get("sites") or []:
                if site.get("site") in keymap and site.get("id"):
                    ids.append(f"{keymap[site['site']]}:{site['id']}")
                elif site.get("site") == "tmdb" and isinstance(site.get("id"), str):
                    tmdb.append(site["id"])
            if not ids:
                continue
            titles = [item.get("title")]
            for values in (item.get("titleTranslate") or {}).values():
                titles.extend(values)
            begin = item.get("begin") or ""
            records.append({"ids": ids, "titles": titles, "type": (item.get("type") or "").upper() or None,
                            "year": int(begin[:4]) if begin[:4].isdigit() else None, "bgm_tmdb": tmdb,
                            "name": item.get("title")})
    for record in records:
        union(record["ids"])
    groups: Dict[str, Dict[str, Any]] = {}
    for record in records:
        group = groups.setdefault(find(record["ids"][0]), {"ids": set(), "titles": set(), "names": [], "types": set(),
                                                          "years": set(), "episodes": None, "duration": None, "bgm_tmdb": []})
        group["ids"].update(record["ids"])
        group["titles"].update(t for t in record["titles"] if isinstance(t, str) and t.strip())
        if record.get("name") and len(group["names"]) < 3:
            group["names"].append(record["name"])
        if record.get("type"):
            group["types"].add(record["type"])
        if type(record.get("year")) is int:
            group["years"].add(record["year"])
        if type(record.get("episodes")) is int and record["episodes"] > 0:
            group["episodes"] = max(group["episodes"] or 0, record["episodes"])
        if type(record.get("duration")) is int and record["duration"] > 0:
            group["duration"] = record["duration"]
        group["bgm_tmdb"].extend(t for t in record.get("bgm_tmdb", []) if t not in group["bgm_tmdb"])
    bridge = {}
    if bridge_file and Path(bridge_file).is_file():
        raw = json.loads(Path(bridge_file).read_text(encoding="utf-8"))
        for key, targets in raw.items():
            if key.startswith("$") or not isinstance(targets, dict):
                continue
            parts = key.split(":")
            if parts[0] == "anidb" and (len(parts) != 3 or parts[2] != "R"):
                continue
            if parts[0] not in ("anidb", "anilist", "mal"):
                continue
            keep = {t: r for t, r in targets.items() if t.startswith(("tmdb_show:", "tmdb_movie:"))}
            if keep:
                bridge[f"{parts[0]}:{parts[1]}"] = keep
    tmp = target.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE works (gid INTEGER PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE titles (key TEXT NOT NULL, gid INTEGER NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE ids (key TEXT PRIMARY KEY, gid INTEGER NOT NULL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE tmdb (tmdb_id INTEGER NOT NULL, gid INTEGER NOT NULL);
    """)
    title_rows = 0
    for gid, group in enumerate(groups.values(), 1):
        maps = {key: bridge[key] for key in sorted(group["ids"]) if key in bridge}
        data = {"names": group["names"], "titles": sorted(group["titles"])[:40], "types": sorted(group["types"]),
                "years": sorted(group["years"]), "episodes": group["episodes"], "duration": group["duration"],
                "ids": sorted(group["ids"]), "maps": maps, "bgm_tmdb": group["bgm_tmdb"]}
        db.execute("INSERT INTO works VALUES (?, ?)", (gid, json.dumps(data, ensure_ascii=False)))
        db.executemany("INSERT OR IGNORE INTO ids VALUES (?, ?)", [(key, gid) for key in group["ids"]])
        shows = {int(m.group(1)) for targets in maps.values() for target in targets
                 for m in [re.match(r"tmdb_show:(\d+):", target)] if m}
        shows |= {int(m.group(1)) for link in group["bgm_tmdb"] for m in [re.match(r"tv/(\d+)", link)] if m}
        db.executemany("INSERT INTO tmdb VALUES (?, ?)", [(show, gid) for show in shows])
        keys = set()
        for title in group["titles"]:
            keys.add((fold(title), "exact"))
            keys.add((loose(title), "loose"))
            head = _HEAD_SPLIT.split(title.strip())[0]
            if head and head != title.strip() and len(fold(head)) >= 4:
                keys.add((loose(head), "head"))
        rows = [(key, gid, kind) for key, kind in keys if key]
        title_rows += len(rows)
        db.executemany("INSERT INTO titles VALUES (?, ?, ?)", rows)
    db.execute("CREATE INDEX titles_key ON titles(key)")
    db.execute("CREATE INDEX tmdb_show ON tmdb(tmdb_id)")
    db.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    db.commit()
    db.close()
    backup = target.with_suffix(".schema-v1.sqlite")
    if target.is_file() and not backup.exists():
        try:
            with closing(sqlite3.connect(f"file:{target}?mode=ro", uri=True)) as previous:
                schema = previous.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        except sqlite3.Error as error:
            note_error(error)
            schema = None
        if schema != (str(SCHEMA_VERSION),):
            os.link(target, backup)
    os.replace(tmp, target)
    _local.__dict__.clear()
    return {"works": len(groups), "titles": title_rows, "mapped_ids": len(bridge)}


# ---------------------------------------------------------------- lookups

def _connection() -> Optional[sqlite3.Connection]:
    path = index_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = getattr(_local, "conn", None)
    if cached is not None and getattr(_local, "mtime", None) == mtime and getattr(_local, "path", None) == str(path):
        return cached
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    _local.conn, _local.mtime, _local.path = conn, mtime, str(path)
    return conn


def _works(conn, gids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    gids = sorted(set(gids))
    if not gids:
        return {}
    rows = conn.execute(f"SELECT gid, data FROM works WHERE gid IN ({','.join('?' * len(gids))})", gids).fetchall()
    return {gid: json.loads(data) for gid, data in rows}


def _by_title(conn, title: str) -> Tuple[set, str]:
    for kind, key in (("exact", fold(title)), ("loose", loose(title))):
        if not key:
            continue
        rows = conn.execute("SELECT gid FROM titles WHERE key = ? AND kind = ?", (key, kind)).fetchall()
        if rows:
            return {r[0] for r in rows}, kind
    key = loose(title)
    rows = conn.execute("SELECT gid FROM titles WHERE key = ? AND kind = 'head'", (key,)).fetchall() if len(key) >= 6 else []
    return ({r[0] for r in rows}, "head") if len({r[0] for r in rows}) == 1 else (set(), "")


def _in_range(episode: int, source: str) -> Optional[int]:
    """Offset of episode inside a source range like '1', '1-12' or '14-', else None."""
    first, dash, last = source.partition("-")
    if not first.isdigit():
        return None
    first_n = int(first)
    if episode < first_n:
        return None
    if not dash:
        return 0 if episode == first_n else None
    if last and (not last.isdigit() or episode > int(last)):
        return None
    return episode - first_n


def _target_episode(offset: int, target: str) -> Optional[int]:
    spec, _, ratio = target.partition("|")
    if ratio and ratio not in ("1",):
        return None  # several episodes per file or the reverse: not a one-to-one episode
    for segment in spec.split(","):
        first, dash, last = segment.partition("-")
        if not first.isdigit():
            return None
        if dash and not last:
            return int(first) + offset
        size = (int(last) - int(first) + 1) if dash else 1
        if offset < size:
            return int(first) + offset
        offset -= size
    return None


def map_episode(work: Dict[str, Any], episode: int, season_hint: Optional[int]) -> Tuple[set, str]:
    """TMDB (show, season, episode) for an episode of this work, from episode-level mappings first."""
    hits = set()
    for targets in (work.get("maps") or {}).values():
        for target, ranges in targets.items():
            match = re.match(r"tmdb_show:(\d+):s(\d+)$", target)
            if not match:
                continue
            show, season = int(match.group(1)), int(match.group(2))
            if not ranges:
                hits.add((show, season, episode))
                continue
            for source, dest in ranges.items():
                offset = _in_range(episode, source)
                if offset is None or not dest:
                    continue
                value = _target_episode(offset, dest)
                if value:
                    hits.add((show, season, value))
    if hits:
        return hits, "anibridge"
    links = [link for link in work.get("bgm_tmdb") or [] if link.startswith("tv/")]
    if len(links) == 1:
        match = re.match(r"tv/(\d+)(?:/season/(\d+)(?:/episode/(\d+))?)?$", links[0])
        if match:
            show = int(match.group(1))
            if match.group(3):
                return {(show, int(match.group(2)), int(match.group(3)) + episode - 1)}, "bangumi-data"
            if match.group(2):
                return {(show, int(match.group(2)), episode)}, "bangumi-data"
            sequel = any(_SEQUEL_WORDS.search(name or "") for name in work.get("names") or [])
            if not sequel:
                return {(show, season_hint or 1, episode)}, "bangumi-data（作品级）"
    return set(), ""


def _label(work: Dict[str, Any]) -> str:
    return (work.get("names") or work.get("titles") or ["?"])[0]


def _year_of(info: Dict[str, Any], src: Path) -> Optional[int]:
    for value in (info.get("year"), info.get("year_guess")):
        if isinstance(value, (int, str)) and str(value).isdigit() and 1950 <= int(value) <= 2100:
            return int(value)
    match = re.search(r"[(\[ .](19[5-9]\d|20\d{2})[)\] .]", f" {src.stem} {src.parent.name} ")
    return int(match.group(1)) if match else None


_CJK = r"\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff"


def bilingual_parts(title: str) -> List[str]:
    """Chinese/Japanese fansub names often carry two names: "摇曳露营△ Yuru Camp△", "Lycoris Recoil 莉可麗絲"."""
    cjk = re.findall(rf"[{_CJK}][{_CJK}\s△☆！!?？・·：～~]*", title)
    latin = re.findall(rf"[A-Za-z][^{_CJK}]*", title)
    parts = [p.strip(" -:：") for p in cjk + latin]
    return [p for p in parts if len(fold(p)) >= 2 and p != title.strip()] if cjk and latin else []


def candidate_titles(info: Dict[str, Any]) -> List[str]:
    titles = []
    for value in [info.get("title"), info.get("search_title"), *(info.get("alternative_titles") or [])]:
        if isinstance(value, str) and value.strip() and value.strip().casefold() != "unknown":
            for item in [value.strip(), *bilingual_parts(value.strip())]:
                if item not in titles:
                    titles.append(item)
    return titles[:8]


def resolve(src: Path, info: Dict[str, Any], config: Dict[str, Any], log: Optional[Callable] = None,
            duration: Optional[Callable[[], Optional[float]]] = None) -> Optional[Dict[str, Any]]:
    """{'status': 'match'|'ambiguous'|'conflict', ...} or None when the databases say nothing."""
    opts = settings(config)
    episode = info.get("episode")
    if not opts["enabled"] or info.get("media_type") not in ("tv", None) or type(episode) is not int or episode < 1:
        return None
    try:
        conn = _connection()
        if conn is None:
            return None
        season = stated_season(src)
        titles = candidate_titles(info)
        year = _year_of(info, src)
        if year:
            # Remakes are often listed as "Title (2020)".
            titles = [variant for title in titles for variant in (f"{title} ({year})", title)]
        gids, how = set(), ""
        if season and season > 1:
            for title in titles:
                for variant in season_titles(title, season):
                    found, kind = _by_title(conn, variant)
                    if found and kind != "head":
                        gids |= found
                        how = "名称+季号"
                if gids:
                    break
        if not gids:
            matched_title = ""
            for title in titles:
                found, kind = _by_title(conn, title)
                if found:
                    gids, how = found, {"exact": "名称", "loose": "名称（长音写法不同）", "head": "名称（不含副标题）"}[kind]
                    matched_title = title
                    break
            if gids and season and season > 1 and not _SEQUEL_WORDS.search(matched_title):
                # The name without its season matched only the work's other seasons; their episode
                # numbers would land in the wrong season, so let the normal search decide.
                works = _works(conn, gids)
                if not any(any(t[1] == season for t in map_episode(w, episode, season)[0]) for w in works.values()):
                    gids = set()
        if not gids and opts["web_search"]["enabled"]:
            gids, how = _web_search(conn, titles, config, opts, log)
        if not gids:
            return None
        works = _works(conn, gids)
        candidates = []
        for gid, work in works.items():
            types = set(work.get("types") or [])
            if types and types <= {"MOVIE"}:
                continue
            hits, source = map_episode(work, episode, season)
            if hits:
                candidates.append({"gid": gid, "work": work, "hits": hits, "source": source})
        if not candidates:
            return None
        notes = []
        if year:
            # A stated year rules out entries known to be from other years (a 1991 series for a 2020 remake).
            fits = [c for c in candidates if not c["work"].get("years") or any(abs(y - year) <= 1 for y in c["work"]["years"])]
            if not fits:
                return None
            if len(fits) > 1:
                fits = [c for c in fits if year in (c["work"].get("years") or [])] or fits
            if len(fits) < len(candidates):
                notes.append(f"年份 {year}")
            candidates = fits
        if len(candidates) > 1 and duration is not None:
            local = duration()
            if local:
                fits = [c for c in candidates if not c["work"].get("duration")
                        or not (abs(local - c["work"]["duration"] / 60) > 8 and max(local, c["work"]["duration"] / 60) / max(1, min(local, c["work"]["duration"] / 60)) > 2)]
                if fits and len(fits) < len(candidates):
                    candidates, _ = fits, notes.append(f"时长 {local:.0f} 分钟")
        if len(candidates) > 1 and not season:
            firsts = [c for c in candidates if not any(_SEQUEL_WORDS.search(n or "") for n in c["work"].get("names") or [])]
            if firsts and len(firsts) < len(candidates):
                candidates, _ = firsts, notes.append("文件名未写季号，取第一季条目")
        results = set().union(*(c["hits"] for c in candidates))
        names = "、".join(dict.fromkeys(_label(c["work"]) for c in candidates))
        if len(results) != 1:
            return {"status": "ambiguous", "candidates": sorted(results)[:6], "names": names,
                    "message": f"离线番剧库有 {len(results)} 种可能（{names}），需要人工确认"}
        show, tmdb_season, tmdb_episode = next(iter(results))
        evidence = f"离线番剧库：按{how}对应「{names}」，由 {candidates[0]['source']} 换算为 TMDB S{tmdb_season:02d}E{tmdb_episode:02d}"
        if notes:
            evidence += "（" + "，".join(notes) + "）"
        conflict = _note_folder(src, titles[0] if titles else "", season, show)
        if conflict:
            return {"status": "conflict", "message": f"同一文件夹里同名文件对应到不同作品（TMDB {conflict} 与 {show}），需要人工确认"}
        if log:
            log(f"📚 {evidence}", LOG_SUCCESS)
        return {"status": "match", "tmdb_id": show, "season": tmdb_season, "episode": tmdb_episode,
                "evidence": evidence, "names": names}
    except sqlite3.Error as error:
        note_error(error)
        if log:
            log(f"⚠️ 番剧数据库不可用：{redact(error)}", LOG_WARNING)
        return None


def known_under_other_name(tmdb_id: int, titles: List[str], official_names: List[str]) -> bool:
    """Check that the TMDB details corroborate the name of a different indexed show."""
    if type(tmdb_id) is not int:
        return False
    keys = {k for title in titles for k in (fold(title), loose(title)) if k}
    official_keys = {fold(name) for name in official_names if name}
    if not keys or not official_keys:
        return False
    try:
        conn = _connection()
        if conn is None or not conn.execute(
            "SELECT 1 FROM meta WHERE key = 'schema' AND value = ?", (str(SCHEMA_VERSION),)
        ).fetchone():
            return False
        names = list(conn.execute(
            "SELECT titles.key, titles.kind FROM titles JOIN tmdb USING (gid) WHERE tmdb.tmdb_id = ?",
            (tmdb_id,),
        ))
        return (any(kind == "exact" and key in official_keys for key, kind in names)
                and all(key not in keys for key, _ in names))
    except sqlite3.Error as error:
        note_error(error)
        return False


# ---------------------------------------------------------------- per-run state

def reset_run() -> None:
    with _run_lock:
        _run_state.update(folders={}, searches=0, search_cache={})


def _note_folder(src: Path, title: str, season: Optional[int], show: int) -> Optional[int]:
    key = (str(src.parent), fold(title), season)
    with _run_lock:
        known = _run_state["folders"].setdefault(key, show)
    return known if known != show else None


# ---------------------------------------------------------------- opt-in paid web search

_SEARCH_SITES = "site:anilist.co OR site:myanimelist.net OR site:bangumi.tv OR site:anidb.net"


def _web_search(conn, titles: List[str], config: Dict[str, Any], opts: Dict[str, Any], log: Optional[Callable]) -> Tuple[set, str]:
    """Ask DeepSeek Search for the anime-database page of a title; the program writes the query,
    reads only titles and snippets, and keeps a result only if it shows the title."""
    ai = config.get("ai_parser") or {}
    key = ai.get("api_key")
    if ai.get("provider", "deepseek") != "deepseek" or not isinstance(key, str) or not key or key == "YOUR_API_KEY" or not titles:
        return set(), ""
    title = titles[0]
    cache_key = loose(title)
    with _run_lock:
        if cache_key in _run_state["search_cache"]:
            return _run_state["search_cache"][cache_key], "联网搜索（本次已搜过）"
        if _run_state["searches"] >= opts["web_search"]["max_per_run"]:
            if log:
                log("联网搜索已达本次上限，跳过", LOG_INFO)
            return set(), ""
        _run_state["searches"] += 1
    gids = set()
    try:
        base = (ai.get("base_url") or "https://api.deepseek.com").rstrip("/")
        proxies = {"http": opts["proxy"], "https": opts["proxy"]} if opts["proxy"] else None
        query = re.sub(r'["~]', " ", title).strip()
        resp = requests.post(f"{base}/v1/tools/search", timeout=30, proxies=proxies,
                             headers={"Authorization": f"Bearer {key}"},
                             json={"query": f'"{query}" {_SEARCH_SITES}'[:128], "count": 10, "need_content": False})
        resp.raise_for_status()
        wanted = loose(title)
        for item in resp.json().get("results") or []:
            if wanted not in loose(f"{item.get('title') or ''} {item.get('snippet') or ''}"):
                continue
            for id_key in ids_from_urls([item.get("url") or ""]):
                row = conn.execute("SELECT gid FROM ids WHERE key = ?", (id_key,)).fetchone()
                if row:
                    gids.add(row[0])
        if log:
            log(f"🔎 联网搜索「{title}」：{len(gids)} 个番剧库条目", LOG_INFO)
    except Exception as error:
        note_error(error)
        if log:
            log(f"⚠️ 联网搜索失败：{redact(error)}", LOG_WARNING)
    with _run_lock:
        _run_state["search_cache"][cache_key] = gids
    return gids, "联网搜索番剧库页面"
