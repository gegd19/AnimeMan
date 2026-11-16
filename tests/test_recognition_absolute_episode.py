"""R04: explicit numbering provenance prevents accidental season changes."""
import pytest


def run_tv(tmp_path, config_file, monkeypatch, info, seasons):
    from core import config_manager, tmdb_client
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show.mkv'; src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], download_images=False)
    cfg['subtitle']['enabled'] = False
    calls = []
    def fetch(_id, season, *a, **kw):
        calls.append(season)
        return [{'episode_number': n, 'name': 'Test'} for n in range(1, seasons.get(season, 0)+1)]
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', fetch)
    details = {'seasons': [{'season_number': x} for x in seasons]}
    cache = {}
    result = process_tv_branch(src, cfg, cache, None, 'Show', '2020', 42, details, info, 85)
    assert src.read_bytes() == b'synthetic'
    return result, cache.get(str(src.resolve()), {}), calls, tmp_path


def test_relative_season_two_episode_one_stays_in_season_two(tmp_path,config_file,monkeypatch):
    result, entry, _, _ = run_tv(tmp_path, config_file, monkeypatch,
        {'season':2,'episode':1,'explicit_season':2,'total_episode':1,'numbering_source':'season_relative'}, {0:2,1:12,2:13})
    assert result and (entry['season'],entry['episode']) == (2,1)


def test_explicit_absolute_13_converts_to_season_two(tmp_path,config_file,monkeypatch):
    result, entry, calls, _ = run_tv(tmp_path, config_file, monkeypatch,
        {'season':2,'episode':13,'explicit_season':2,'total_episode':13,'numbering_source':'absolute'}, {0:5,1:12,2:13})
    assert result and (entry['season'],entry['episode']) == (2,1)
    assert 0 not in calls


def test_relative_13_stays_in_season_two(tmp_path,config_file,monkeypatch):
    result, entry, _, _ = run_tv(tmp_path, config_file, monkeypatch,
        {'season':2,'episode':13,'explicit_season':2,'total_episode':13,'numbering_source':'season_relative'}, {1:12,2:13})
    assert result and (entry['season'],entry['episode']) == (2,13)


@pytest.mark.parametrize('info,seasons', [
    ({'season':2,'episode':13,'explicit_season':2,'total_episode':13,'numbering_source':'absolute'}, {1:0,2:13}),
    ({'season':2,'episode':13,'explicit_season':2,'total_episode':13,'numbering_source':'absolute'}, {2:13}),
    ({'season':2,'episode':13,'explicit_season':2,'total_episode':13}, {1:12,2:13}),
])
def test_incomplete_or_legacy_total_is_not_guessed(tmp_path,config_file,monkeypatch,info,seasons):
    result, entry, _, root = run_tv(tmp_path, config_file, monkeypatch, info, seasons)
    assert not result
    assert entry.get('media_type') == 'failed'
    assert not list((root/'tv').rglob('*.mkv'))
    assert not list((root/'tv').rglob('*.nfo'))


def test_numbering_provenance_contract_is_trusted_only():
    from core.parse_contract import normalize_media
    value={'media_type':'tv','title':'Example','season':2,'episode':13,'total_episode':13,'numbering_source':'absolute'}
    assert normalize_media(value,trusted=True)['numbering_source'] == 'absolute'
    assert normalize_media(value).get('numbering_source') != 'absolute'


def test_chinese_second_season_first_episode_is_relative(tmp_path,config_file):
    from core import config_manager, parser_manager
    src=tmp_path/'Show'/'Show 第二季 第01集.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(src.parent)]
    result=parser_manager.parse_filename(src,cfg)
    assert result['numbering_source']=='season_relative'
    assert result['total_episode'] is None


def test_explicit_absolute_filename_has_trusted_provenance(tmp_path,config_file):
    from core import config_manager, parser_manager
    src=tmp_path/'Show'/'Show 第二季 全剧第13集.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(src.parent)]
    result=parser_manager.parse_filename(src,cfg)
    assert (result['numbering_source'],result['total_episode']) == ('absolute',13)
    assert (result['season'],result['episode']) == (2,13)


def test_absolute_lookup_timeout_preserves_transient_failure(tmp_path,config_file,monkeypatch):
    import requests
    from core import config_manager, tmdb_client
    from core.failure_policy import failure_scope
    from core.processor_tv import process_tv_branch
    src=tmp_path/'source'/'Show.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['subtitle']['enabled']=False
    class Session:
        def get(self,*args,**kwargs): raise requests.Timeout('synthetic timeout')
    monkeypatch.setattr(tmdb_client,'create_session',lambda *a:Session())
    monkeypatch.setattr(tmdb_client._tmdb_limiter,'wait',lambda:None)
    cache={}
    with failure_scope(cfg):
        result=process_tv_branch(src,cfg,cache,None,'Show','2020',42,
            {'seasons':[{'season_number':1},{'season_number':2}]},
            {'season':2,'episode':13,'explicit_season':2,'total_episode':13,'numbering_source':'absolute'},85)
    assert not result
    assert cache[str(src.resolve())]['failure_category']=='transient'
    assert cache[str(src.resolve())]['retry_after'] is not None
    assert src.read_bytes()==b'synthetic'
    assert not list((tmp_path/'tv').rglob('*.mkv'))


def test_absolute_conversion_rejects_gapped_episode_list(tmp_path,config_file,monkeypatch):
    from core import config_manager, tmdb_client
    from core.processor_tv import process_tv_branch
    src=tmp_path/'source'/'Show.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['subtitle']['enabled']=False
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda _id,season,*a,**kw:
        [{'episode_number':1},{'episode_number':3}] if season==1 else [{'episode_number':1}])
    cache={}
    assert not process_tv_branch(src,cfg,cache,None,'Show','2020',42,
        {'seasons':[{'season_number':1},{'season_number':2}]},
        {'season':2,'episode':3,'explicit_season':2,'total_episode':3,'numbering_source':'absolute'},85)
    assert cache[str(src.resolve())]['media_type']=='failed'
    assert not list((tmp_path/'tv').rglob('*.mkv'))
