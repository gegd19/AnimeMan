#!/usr/bin/env python3
"""Evaluate real recognition decisions using synthetic files and offline fixtures."""
import argparse
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/recognition_cases.json'


def metrics(rows):
    passed = [r for r in rows if r['actual'] is not None]
    correct = sum(r['actual'] == r['expected'] for r in passed)
    unsafe = sum(r['expected'] is None for r in passed)
    return {'total': len(rows), 'correct_auto': correct,
            'incorrect_auto': len(passed) - correct,
            'review_expected_but_auto': unsafe,
            'review': len(rows) - len(passed),
            'ai_calls': sum(r['ai_calls'] for r in rows),
            'tmdb_calls': sum(r['tmdb_calls'] for r in rows),
            'auto_accuracy': correct / len(passed) if passed else None,
            'correct_coverage': correct / len(rows) if rows else None}


def _component(value):
    if not isinstance(value, str) or value in ('', '.', '..') or Path(value).name != value or '/' in value or '\\' in value:
        raise ValueError('fixture paths must be single safe components')
    return value


def run_case(case, temp, modules):
    config_manager, processor, tmdb, parser, folder, search, ai, video = modules
    case_root = temp / _component(case['case_id'])
    source = case_root / _component(case['folder'])
    source.mkdir(parents=True)
    src = source / _component(case['filename'])
    src.write_bytes(b'synthetic video')
    for name in case.get('other_files', []):
        other = source / _component(name)
        if other == src:
            raise ValueError('duplicate synthetic file')
        other.write_bytes(b'synthetic video')
    config = config_manager.load_config(case_root / 'config.json', apply_environment=False, create_if_missing=False)
    config.update(source_folders=[str(source)], tv_target_folder=str(case_root/'tv'),
                  movie_target_folder=str(case_root/'movies'), dry_run=False,
                  download_images=False, special_mappings=[], ignore_patterns=[])
    config['ai_parser']['enabled'] = False
    config['subtitle']['enabled'] = False
    config['tmdb_api']['api_key'] = 'synthetic-key'
    counts = {'tmdb': 0, 'ai': 0}
    def search_mock(*args, **kwargs):
        counts['tmdb'] += 1
        if case['network_error']:
            import requests
            raise requests.Timeout('synthetic TMDB timeout')
        return case['search_results']
    def details_mock(*args, **kwargs):
        counts['tmdb'] += 1
        if case['network_error']:
            return None
        requested_id = kwargs.get('tmdb_id', args[1] if len(args) > 1 else None)
        if requested_id == case['details']['id']:
            return case['details']
        candidate = next((r for r in case['search_results'] if r['id'] == requested_id), None)
        if candidate is None:
            return None
        return {**case['details'], **candidate}
    def episodes_mock(tmdb_id, season, *args, **kwargs):
        counts['tmdb'] += 1
        return case['seasons'].get(str(season), [])
    def ai_mock(*args, **kwargs):
        counts['ai'] += 1
        raise AssertionError('unexpected AI call in AI-disabled fixture')
    cache = {}
    with ExitStack() as stack:
        for obj, name, value in [(tmdb, 'search_tmdb_multi', search_mock),
                                 (tmdb, 'get_tmdb_details', details_mock),
                                 (tmdb, 'get_tv_season_episodes', episodes_mock),
                                 (video, 'get_video_duration', lambda *a, **k: None),
                                 (ai, 'call_ai_api', ai_mock)]:
            stack.enter_context(patch.object(obj, name, value))
        processor._folder_tmdb_cache.clear()
        parser.AI_CACHE.clear()
        folder._tmdb_search_cache.clear()
        search._ai_selection_cache.clear()
        success = processor.process_video(src, config, cache)
    if counts['ai']:
        raise RuntimeError('unexpected AI call')
    entry = cache.get(str(src.resolve()), {})
    actual = None
    if success:
        if entry.get('media_type') not in ('tv', 'movie') or not entry.get('tmdb_id'):
            raise RuntimeError('success without a complete cache identity')
        actual = {k: entry.get(k) for k in ('media_type', 'tmdb_id', 'season', 'episode')}
    return {'case_id': case['case_id'], 'category': case['category'],
            'split': case['split'], 'expected': case['expected'], 'actual': actual,
            'ai_calls': counts['ai'], 'tmdb_calls': counts['tmdb']}


def evaluate(raw):
    data = json.loads(raw)
    cases = data['cases']
    if not cases or len({c['case_id'] for c in cases}) != len(cases):
        raise ValueError('fixture cases must have unique IDs')
    network_attempts = []
    def deny(*args, **kwargs):
        network_attempts.append(True)
        raise AssertionError('network disabled during offline evaluation')
    with tempfile.TemporaryDirectory(prefix='animeman-b00-') as directory:
        temp = Path(directory)
        old_dir = Path.cwd()
        old_env = os.environ.copy()
        try:
            os.chdir(temp)
            for key in ('SOURCE_FOLDERS','TV_TARGET_FOLDER','MOVIE_TARGET_FOLDER',
                        'OPENAI_API_KEY','TMDB_API_KEY','DEEPSEEK_API_KEY','ANTHROPIC_API_KEY'):
                os.environ.pop(key, None)
            os.environ.update(CONFIG_PATH=str(temp/'config.json'), CACHE_PATH=str(temp/'cache'),
                              LOG_PATH=str(temp/'logs'), SECRET_KEY='synthetic-only')
            sys.path.insert(0, str(ROOT))
            with ExitStack() as stack:
                stack.enter_context(patch.object(socket.socket, 'connect', deny))
                stack.enter_context(patch.object(socket.socket, 'connect_ex', deny))
                stack.enter_context(patch.object(socket, 'create_connection', deny))
                import requests
                stack.enter_context(patch.object(requests.sessions.Session, 'request', deny))
                from core import config_manager, processor_core, tmdb_client, parser_manager, processor_folder_ai, processor_search, ai_client, video_info
                modules = (config_manager, processor_core, tmdb_client, parser_manager, processor_folder_ai, processor_search, ai_client, video_info)
                rows = [run_case(case, temp, modules) for case in cases]
                if network_attempts:
                    raise RuntimeError('unexpected network access attempted')
            return {'fixture_version': data['version'], 'fixture_sha256': hashlib.sha256(raw).hexdigest(),
                    'metrics': metrics(rows),
                    'splits': {name: metrics([r for r in rows if r['split'] == name])
                               for name in ('development', 'heldout')}, 'cases': rows}
        finally:
            os.chdir(old_dir)
            os.environ.clear()
            os.environ.update(old_env)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', help='report path; default stdout')
    args = ap.parse_args()
    with redirect_stdout(io.StringIO()):
        report = evaluate(FIXTURES.read_bytes())
    result = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if args.output:
        Path(args.output).write_text(result, encoding='utf-8')
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
