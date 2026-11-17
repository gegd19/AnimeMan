#!/usr/bin/env python3
"""R10 offline evaluation of the unchanged B00 fixtures, including warm/AI modes.

AI is a neutral deterministic mock. All media, configuration, caches and logs
are temporary; external network and ffprobe are disabled for every scenario.
"""
import argparse
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures/recognition_cases.json'
BASELINE=ROOT/'tests/fixtures/recognition_baseline.json'
EXTENSION=ROOT/'tests/fixtures/recognition_extension_cases.json'


def summarize(rows):
    passed=[row for row in rows if row['actual'] is not None]
    eligible=[row for row in rows if row['expected'] is not None]
    correct=sum(row['expected'] is not None and row['actual']==row['expected'] for row in rows)
    pending=sum(bool(row.get('pending') and row['expected'] and row['actual'] is None
                     and row['pending'].get('identity_status')=='confirmed'
                     and row['pending'].get('numbering_status')=='unknown'
                     and row['pending'].get('tmdb_id')==row['expected'].get('tmdb_id')
                     and row['pending'].get('media_type')==row['expected'].get('media_type')) for row in rows)
    return {'total':len(rows),'eligible_total':len(eligible),'must_review_total':len(rows)-len(eligible),
            'automatic_total':len(passed),'correct_auto':correct,'wrong_auto':len(passed)-correct,
            'unsafe_auto':sum(row['expected'] is None for row in passed),'review':len(rows)-len(passed),
            'identity_known_numbering_pending':pending,
            'auto_accuracy':correct/len(passed) if passed else None,
            'correct_coverage':correct/len(rows) if rows else None,
            'eligible_coverage':correct/len(eligible) if eligible else None,
            'ai_calls':sum(row['ai_calls'] for row in rows),
            'tmdb_calls':sum(row['tmdb_calls'] for row in rows),
            'tvmaze_calls':sum(row['tvmaze_calls'] for row in rows),
            'runtime_errors':sum(row.get('runtime_errors',0) for row in rows),
            'mock_elapsed_ms':round(sum(row.get('mock_elapsed_ms',0) for row in rows),3)}


def _component(value):
    if not isinstance(value,str) or value in ('','.','..') or Path(value).name!=value or '/' in value or '\\' in value:
        raise ValueError('fixture paths must be single safe components')
    return value


def _group(case):
    if case['category']=='special':return 'special'
    if case['category']=='movie' or (case.get('expected') or {}).get('media_type')=='movie':return 'movie'
    return 'tv'


def _run_pair(case, base, modules, ai_enabled):
    config_manager,processor,tmdb,parser,folder,search,ai,video,enhancer=modules
    case_root=base/_component(case['case_id'])/('ai_on' if ai_enabled else 'ai_off')
    source=case_root/_component(case['folder']);source.mkdir(parents=True)
    src=source/_component(case['filename']);src.write_bytes(b'synthetic video')
    for name in case.get('other_files',[]):
        other=source/_component(name)
        if other==src:raise ValueError('duplicate synthetic file')
        other.write_bytes(b'synthetic video')
    config=config_manager.load_config(case_root/'config.json',apply_environment=False,create_if_missing=False)
    config.update(source_folders=[str(source)],tv_target_folder=str(case_root/'tv'),
                  movie_target_folder=str(case_root/'movies'),dry_run=False,
                  download_images=False,special_mappings=[],ignore_patterns=[])
    config['ai_parser']['enabled']=ai_enabled
    config['ai_parser']['api_key']='synthetic-ai-key' if ai_enabled else ''
    config['subtitle']['enabled']=False;config['tmdb_api']['api_key']='synthetic-key'
    setup=case.get('setup',{})
    if setup.get('nfo_tmdb_id'):
        ident=setup['nfo_tmdb_id']
        if type(ident) is not int or ident<1:raise ValueError('invalid synthetic NFO identity')
        (source/'tvshow.nfo').write_text(f'<tvshow><uniqueid type="tmdb">{ident}</uniqueid></tvshow>',encoding='utf8')
        config['identity_hints']={'enabled':True}
    if setup.get('series_rule'):
        from core import user_recognition_rules
        rule=setup['series_rule'];config['user_rules']={'enabled':True}
        user_recognition_rules.create_rule(config,str(src),'series',rule['tmdb_id'],'tv',anchor_title=rule['anchor_title'])
    if setup.get('aliases'):
        from core import recognition_aliases
        record=setup['aliases'];config['recognition_aliases']={'enabled':True}
        for name in record['names']:recognition_aliases.add_alias(name,'tv',record['tmdb_id'],'manual')
    if setup.get('numbering'):
        from core import numbering_maps
        record=setup['numbering'];config['numbering_maps']={'enabled':True}
        numbering_maps.add_exact(config,str(source),case['details']['id'],record['source_label'],record['season'],record['episode'])
    if setup.get('numbering_enabled'):config['numbering_maps']={'enabled':True}
    if setup.get('all_optional_enabled'):
        config.update(identity_hints={'enabled':True},user_rules={'enabled':True},
                      recognition_aliases={'enabled':True},numbering_maps={'enabled':True})
    counts={'search':0,'details':0,'episodes':0,'ai':0,'tvmaze':0,'runtime_errors':0}
    original_error=processor.logger.error
    def record_error(*args,**kwargs):
        counts['runtime_errors']+=1
        return original_error(*args,**kwargs)
    seen_candidates=set()
    def search_mock(*a,**k):
        counts['search']+=1
        if case['network_error']:
            import requests
            raise requests.Timeout('synthetic TMDB timeout')
        seen_candidates.update(item['id'] for item in case['search_results'] if type(item.get('id')) is int and item['id']>0)
        return case['search_results']
    def details_mock(*args,**kwargs):
        counts['details']+=1
        if case['network_error']:return None
        ident=kwargs.get('tmdb_id',args[1] if len(args)>1 else None)
        if ident==case['details']['id']:return case['details']
        candidate=next((r for r in case['search_results'] if r['id']==ident),None)
        return {**case['details'],**candidate} if candidate is not None else None
    def episodes_mock(tmdb_id,season,*a,**k):
        counts['episodes']+=1
        return case['seasons'].get(str(season),[])
    def ai_mock(*a,**k):
        from core.ai_budget import consume_recognition_call
        consume_recognition_call();counts['ai']+=1
        return None
    def tvmaze_mock(*a,**k):counts['tvmaze']+=1;return None
    cache={};result={}
    with ExitStack() as stack:
        for obj,name,value in [(tmdb,'search_tmdb_multi',search_mock),(tmdb,'get_tmdb_details',details_mock),
                               (tmdb,'get_tv_season_episodes',episodes_mock),(video,'get_video_duration',lambda *a,**k:None),
                               (ai,'call_ai_api_with_messages',ai_mock),
                               (enhancer,'search_tvmaze',tvmaze_mock),(processor.logger,'error',record_error)]:
            stack.enter_context(patch.object(obj,name,value))
        processor._folder_tmdb_cache.clear();parser.AI_CACHE.clear();folder._tmdb_search_cache.clear();search._ai_selection_cache.clear()
        for temperature in ('cold','warm'):
            previous=dict(counts);seen_candidates.clear();started=time.perf_counter()
            success=processor.process_video(src,config,cache)
            elapsed=round((time.perf_counter()-started)*1000,3)
            entry=cache.get(str(src.resolve()),{})
            actual=None
            if success:
                if entry.get('media_type') not in ('tv','movie') or not entry.get('tmdb_id'):
                    raise RuntimeError('success without complete cache identity')
                actual={key:entry.get(key) for key in ('media_type','tmdb_id','season','episode')}
            pending=entry.get('recognition_pending') if not success else None
            if isinstance(pending,dict):
                pending={key:pending.get(key) for key in ('identity_status','numbering_status','media_type','tmdb_id')}
            else:pending=None
            delta={key:counts[key]-previous[key] for key in counts}
            diagnostic=entry.get('last_failure',entry)
            reason=diagnostic.get('failed_reason','') if isinstance(diagnostic,dict) else ''
            reason_code=('unsupported_numbering' if 'unsupported_episode_numbering' in reason else
                         'conflicting_season' if 'conflicting_season_evidence' in reason else
                         'missing_title' if 'missing_series_title' in reason else
                         'needs_confirmation' if '人工确认' in reason else
                         'no_match_or_details' if 'TMDB 搜索' in reason else
                         'other' if reason else None)
            result[temperature]={'actual':actual,'pending':pending,
                'decision':'automatic' if actual is not None else 'review', 'reason_code':reason_code,
                'candidate_ids':sorted(seen_candidates), 'score_origin':entry.get('score_origin') if success else None,
                'ai_calls':delta['ai'],'tmdb_calls':delta['search']+delta['details']+delta['episodes'],
                'tmdb_search_calls':delta['search'],'tmdb_details_calls':delta['details'],
                'tmdb_episode_calls':delta['episodes'],'tvmaze_calls':delta['tvmaze'],
                'runtime_errors':delta['runtime_errors'],
                'mock_elapsed_ms':elapsed}
    if not ai_enabled and counts['ai']:
        raise RuntimeError('unexpected AI call while disabled')
    return result


def evaluate(raw, baseline, extension_raw=None):
    data=json.loads(raw);cases=data['cases']
    if not cases or len({case['case_id'] for case in cases})!=len(cases):raise ValueError('invalid fixture IDs')
    digest=hashlib.sha256(raw).hexdigest()
    if baseline['fixture_version']!=data['version'] or baseline['fixture_sha256']!=digest:
        raise ValueError('B00 baseline version/hash does not match fixtures')
    previous={row['case_id']:row for row in baseline['cases']}
    if set(previous)!={case['case_id'] for case in cases}:raise ValueError('B00 baseline case IDs differ')
    network_attempts=[];process_attempts=[]
    def deny(*a,**k):network_attempts.append(True);raise AssertionError('external network is forbidden')
    def deny_process(*a,**k):process_attempts.append(True);raise AssertionError('external process is forbidden')
    with tempfile.TemporaryDirectory(prefix='animeman-r10-') as directory:
        base=Path(directory);old_dir=Path.cwd();old_env=os.environ.copy()
        try:
            os.chdir(base)
            for key in ('SOURCE_FOLDERS','TV_TARGET_FOLDER','MOVIE_TARGET_FOLDER','OPENAI_API_KEY',
                        'TMDB_API_KEY','DEEPSEEK_API_KEY','ANTHROPIC_API_KEY'):
                os.environ.pop(key,None)
            os.environ.update(CONFIG_PATH=str(base/'config.json'),CACHE_PATH=str(base/'cache'),
                              LOG_PATH=str(base/'logs'),SECRET_KEY='synthetic-only')
            sys.path.insert(0,str(ROOT))
            with ExitStack() as stack:
                stack.enter_context(patch.object(socket.socket,'connect',deny))
                stack.enter_context(patch.object(socket.socket,'connect_ex',deny))
                stack.enter_context(patch.object(socket,'create_connection',deny))
                stack.enter_context(patch.object(subprocess,'run',deny_process))
                stack.enter_context(patch.object(subprocess,'Popen',deny_process))
                import requests
                stack.enter_context(patch.object(requests.sessions.Session,'request',deny))
                from core import config_manager,processor_core,tmdb_client,parser_manager,processor_folder_ai,processor_search,ai_client,video_info,search_enhancer
                modules=(config_manager,processor_core,tmdb_client,parser_manager,processor_folder_ai,processor_search,ai_client,video_info,search_enhancer)
                rows=[]
                for case in cases:
                    off=_run_pair(case,base,modules,False);on=_run_pair(case,base,modules,True)
                    rows.append({'case_id':case['case_id'],'category':case['category'],'media_group':_group(case),
                                 'split':case['split'],'expected':case['expected'],
                                 'baseline_actual':previous[case['case_id']]['actual'],
                                 'other_file_count':len(case.get('other_files',[])),
                                 'scenarios':{'ai_off_cold':off['cold'],'ai_off_warm':off['warm'],
                                              'ai_on_cold':on['cold'],'ai_on_warm':on['warm']}})
                extension_rows=[]
                if extension_raw is not None:
                    extension=json.loads(extension_raw)
                    extra=extension['cases']
                    if not extra or len({c['case_id'] for c in extra})!=len(extra) or set(c['case_id'] for c in extra)&set(previous):
                        raise ValueError('invalid extension case IDs')
                    for case in extra:
                        pairs={}
                        for mode, enabled in [('ai_off',False),('ai_on',True)]:
                            os.environ['CACHE_PATH']=str(base/'extension-cache'/case['case_id']/mode)
                            pairs[mode]=_run_pair(case,base,modules,enabled)
                        os.environ['CACHE_PATH']=str(base/'cache')
                        extension_rows.append({'case_id':case['case_id'],'category':case['category'],
                                               'media_group':_group(case),'expected':case['expected'],
                                               'scenarios':{'ai_off_cold':pairs['ai_off']['cold'],'ai_off_warm':pairs['ai_off']['warm'],
                                                            'ai_on_cold':pairs['ai_on']['cold'],'ai_on_warm':pairs['ai_on']['warm']}})
                if network_attempts or process_attempts:raise RuntimeError('unexpected external network/process attempted')
        finally:
            os.chdir(old_dir);os.environ.clear();os.environ.update(old_env)
    scenarios={};groups={};acceptance={}
    for scenario in ('ai_off_cold','ai_off_warm','ai_on_cold','ai_on_warm'):
        items=[dict(row['scenarios'][scenario],expected=row['expected']) for row in rows]
        scenarios[scenario]=summarize(items)
        groups[scenario]={kind:summarize([item for item,row in zip(items,rows) if row['media_group']==kind]) for kind in ('movie','tv','special')}
        regressions=[row['case_id'] for row in rows if row['expected'] is not None and row['baseline_actual']==row['expected'] and row['scenarios'][scenario]['actual']!=row['expected']]
        unsafe=[row['case_id'] for row in rows if row['expected'] is None and row['scenarios'][scenario]['actual'] is not None]
        runtime_errors=[row['case_id'] for row in rows if row['scenarios'][scenario]['runtime_errors']]
        acceptance[scenario]={'passed':not regressions and not unsafe and not runtime_errors,
                              'regressions':regressions,'unsafe_auto':unsafe,'runtime_errors':runtime_errors}
    differences=[{'case_id':row['case_id'],'category':row['category'],'expected':row['expected'],
                  'baseline':row['baseline_actual'],'current':row['scenarios']['ai_off_cold']['actual']}
                 for row in rows if row['baseline_actual']!=row['scenarios']['ai_off_cold']['actual']]
    temperature_differences={mode:[row['case_id'] for row in rows if row['scenarios'][mode+'_cold']['actual']!=row['scenarios'][mode+'_warm']['actual']]
                             for mode in ('ai_off','ai_on')}
    extension_report=None
    if extension_raw is not None:
        extension_summaries={};extension_groups={};extension_acceptance={}
        for scenario in ('ai_off_cold','ai_off_warm','ai_on_cold','ai_on_warm'):
            items=[dict(row['scenarios'][scenario],expected=row['expected']) for row in extension_rows]
            extension_summaries[scenario]=summarize(items)
            extension_groups[scenario]={kind:summarize([item for item,row in zip(items,extension_rows) if row['media_group']==kind]) for kind in ('movie','tv','special')}
            incorrect=[row['case_id'] for row in extension_rows if row['expected'] is not None and row['scenarios'][scenario]['actual']!=row['expected']]
            unsafe=[row['case_id'] for row in extension_rows if row['expected'] is None and row['scenarios'][scenario]['actual'] is not None]
            errors=[row['case_id'] for row in extension_rows if row['scenarios'][scenario]['runtime_errors']]
            extension_acceptance[scenario]={'passed':not incorrect and not unsafe and not errors,
                                            'missed_eligible':incorrect,'unsafe_auto':unsafe,'runtime_errors':errors}
        extension_differences={mode:[row['case_id'] for row in extension_rows if row['scenarios'][mode+'_cold']['actual'] != row['scenarios'][mode+'_warm']['actual']] for mode in ('ai_off','ai_on')}
        extension_report={'fixture_version':extension['version'],'fixture_sha256':hashlib.sha256(extension_raw).hexdigest(),
                          'cold_warm_decision_differences':extension_differences,
                          'scenarios':extension_summaries,'media_groups':extension_groups,
                          'acceptance':extension_acceptance,'cases':extension_rows}
    return {'fixture_version':data['version'],'fixture_sha256':digest,'baseline_metrics':baseline['metrics'],
            'scenarios':scenarios,'media_groups':groups,'acceptance':acceptance,'extension':extension_report,
            'baseline_differences':differences,'cold_warm_decision_differences':temperature_differences,
            'method':{'ai':'neutral low-level API mock returns no response; actual parser wrappers and AI budgets run normally','tmdb':'fixture mock',
                      'warm':'same file and caches immediately processed a second time',
                      'folder_counts':'one processed synthetic source per case; other fixture files are context',
                      'timing':'local mock milliseconds, not external network performance',
                      'movie_tv_special':'fixture expected type/category; unclassified review cases grouped as TV filename fixtures',
                      'network_attempts':0,'external_process_attempts':0},'cases':rows}



def render_markdown(report):
    def pct(value):return 'N/A' if value is None else f'{value*100:.2f}%'
    def identity(value):
        if value is None:return '待确认'
        kind=value.get('media_type');ident=value.get('tmdb_id')
        if kind=='tv':return f"TV {ident} S{value.get('season'):02d}E{value.get('episode'):02d}"
        return f"{kind} {ident}"
    current=report['scenarios']['ai_off_cold']; regressions=report['acceptance']['ai_off_cold']['regressions']
    verdict='通过' if report['acceptance']['ai_off_cold']['passed'] else '未通过'
    lines=['# AnimeMan 识别策略 R10 离线评估', '',
           f"识别代码基线：`{report.get('source_revision') or '未指定'}`。",
           f"B00 固定集：`{report['fixture_version']}`，SHA-256 `{report['fixture_sha256']}`；共 {len(report['cases'])} 例。",
           f"扩展集：`{report['extension']['fixture_version']}`，SHA-256 `{report['extension']['fixture_sha256']}`；与固定集分开统计。", '',
           f"**固定集 AI 关 / 冷验收结果：{verdict}。** 原先正确但本次未正确自动通过：{', '.join(regressions) if regressions else '无'}。", '',
           '自动准确率 = 正确自动通过 / 全部自动通过；总覆盖率 = 正确自动通过 / 全部案例；可自动处理覆盖率 = 正确自动通过 / 预期可自动处理案例。自动通过数为零时准确率记 N/A。', '',
           f"固定集 {current['total']} 例中，{current['eligible_total']} 例预期可自动处理，{current['must_review_total']} 例必须待确认。基准和当前结果均含必须待确认案例。", '',
           '| 固定集场景 | 正确自动 | 自动准确率 | 总覆盖率 | 可自动处理覆盖率 | 错误自动 | 应拒绝却通过 | 待确认 | 作品正确但季集未决 | AI 调用 | TMDB 调用 | TVmaze 调用 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    base=report['baseline_metrics'];base_accuracy=pct(base['auto_accuracy']);base_coverage=pct(base['correct_coverage'])
    lines.append(f"| B00 冷缓存、AI 关 | {base['correct_auto']} | {base_accuracy} | {base_coverage} | {pct(base['correct_auto']/current['eligible_total']) if current['eligible_total'] else 'N/A'} | {base['incorrect_auto']} | {base['review_expected_but_auto']} | {base['review']} | 未记录 | {base['ai_calls']} | {base['tmdb_calls']} | 未记录 |")
    names={'ai_off_cold':'AI 关 / 冷','ai_off_warm':'AI 关 / 热','ai_on_cold':'AI 开 / 冷','ai_on_warm':'AI 开 / 热'}
    for name,label in names.items():
        m=report['scenarios'][name]
        lines.append(f"| {label} | {m['correct_auto']} | {pct(m['auto_accuracy'])} | {pct(m['correct_coverage'])} | {pct(m['eligible_coverage'])} | {m['wrong_auto']} | {m['unsafe_auto']} | {m['review']} | {m['identity_known_numbering_pending']} | {m['ai_calls']} | {m['tmdb_calls']} | {m['tvmaze_calls']} |")
    changes=report['cold_warm_decision_differences']
    unsafe_scenarios=[names[name] for name in names if report['acceptance'][name]['unsafe_auto']]
    failed_scenarios=[names[name] for name in names if not report['acceptance'][name]['passed']]
    lines += ['', f"固定集冷热决策差异：AI 关 {', '.join(changes['ai_off']) if changes['ai_off'] else '无'}；AI 开 {', '.join(changes['ai_on']) if changes['ai_on'] else '无'}。",
              f"存在安全样例误放行的场景：{', '.join(unsafe_scenarios) if unsafe_scenarios else '无'}；未通过验收的场景：{', '.join(failed_scenarios) if failed_scenarios else '无'}。", '',
              '## 按媒体分组（固定集）', '',
              '| 场景 | 组别 | 总数 | 预期可自动 | 正确自动 | 正确覆盖率 | 待确认 | AI 调用 | TMDB 调用 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,label in names.items():
        for group in ('movie','tv','special'):
            m=report['media_groups'][name][group]
            lines.append(f"| {label} | {group} | {m['total']} | {m['eligible_total']} | {m['correct_auto']} | {pct(m['correct_coverage'])} | {m['review']} | {m['ai_calls']} | {m['tmdb_calls']} |")
    lines += ['', '## 固定集逐例决策变化（B00 → 当前 AI 关 / 冷）', '',
              '| 案例 | 类别 | 预期 | B00 | 当前 |','|---|---|---|---|---|']
    for item in report['baseline_differences']:
        lines.append(f"| {item['case_id']} | {item['category']} | {identity(item['expected'])} | {identity(item['baseline'])} | {identity(item['current'])} |")
    lines += ['', '回退仅指旧结果与预期一致而当前未正确自动通过；旧结果错误后转为待确认不计为正确案例回退。', '',
              '## 独立扩展集', '',
              f"{report['extension']['scenarios']['ai_off_cold']['total']} 个合成案例中，{report['extension']['scenarios']['ai_off_cold']['eligible_total']} 例预期可自动处理，{report['extension']['scenarios']['ai_off_cold']['must_review_total']} 例必须待确认。覆盖显式 NFO、已确认系列规则、多语言别名、小数编号映射、多集拒绝和电影；不与 B00 分母合并。", '',
              '| 场景 | 正确自动 | 自动准确率 | 总覆盖率 | 可自动处理覆盖率 | 错误自动 | 应拒绝却通过 | 待确认 | AI 调用 | TMDB 调用 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,label in names.items():
        m=report['extension']['scenarios'][name]
        lines.append(f"| {label} | {m['correct_auto']} | {pct(m['auto_accuracy'])} | {pct(m['correct_coverage'])} | {pct(m['eligible_coverage'])} | {m['wrong_auto']} | {m['unsafe_auto']} | {m['review']} | {m['ai_calls']} | {m['tmdb_calls']} |")
    extension_diffs=report['extension']['cold_warm_decision_differences']
    lines += ['', f"扩展集冷热决策差异：AI 关 {', '.join(extension_diffs['ai_off']) if extension_diffs['ai_off'] else '无'}；AI 开 {', '.join(extension_diffs['ai_on']) if extension_diffs['ai_on'] else '无'}。样本很少，结果不能外推为实际识别率。", '', '## 方法与限制', '',
              '- 每例处理一个临时合成媒体文件；同目录其他合成文件仅作为上下文。JSON 中逐例列出每次文件处理及对应目录的 AI、TMDB、TVmaze 调用数。',
              '- TMDB、TVmaze 和 AI 均为 mock，AI 开启时底层返回无响应，不代表真实模型能力；ffprobe 和外部进程被阻断。',
              '- 热缓存是在同一进程中对相同文件再次运行，不代表生产增量扫描或重启后的性能。movie / TV / special 按固定集预期类型及案例类别归组；必须待确认的其他视频命名案例归入 TV。',
              '- 每例 `mock_elapsed_ms` 是本机 mock 执行时间，不能代表真实外网耗时。测试未读取真实配置、密钥或用户媒体。',
              '- 假设修复 C46、C49 需要可靠别名或 TMDB 备用标题证据；扩展案例 X03 验证了显式提供合成别名的路径，不能证明真实数据均可自动识别。',
              '- [完整逐例数据](recognition-r10-results.json) 包括每种场景的决策、候选 ID、原因类别、调用数与本机 mock 用时。', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='report path; default stdout')
    parser.add_argument('--markdown',help='optional Markdown report path')
    parser.add_argument('--source-revision',help='recognition code revision under evaluation')
    args=parser.parse_args()
    if args.output and args.markdown and Path(args.output).resolve()==Path(args.markdown).resolve():
        parser.error('JSON and Markdown output paths must differ')
    for path in (args.output,args.markdown):
        if path and os.path.lexists(path):
            parser.error(f'output already exists; refusing to overwrite: {path}')
    with redirect_stdout(io.StringIO()):
        result=evaluate(FIXTURES.read_bytes(),json.loads(BASELINE.read_text(encoding='utf8')),EXTENSION.read_bytes())
    result['source_revision']=args.source_revision
    output=json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    if args.markdown:
        with Path(args.markdown).open('x',encoding='utf8') as stream:stream.write(render_markdown(result))
    if args.output:
        with Path(args.output).open('x',encoding='utf8') as stream:stream.write(output)
    else:print(output,end='')


if __name__=='__main__':main()
