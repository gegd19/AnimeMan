"""E04: typed alias provenance and semantic search variants."""
import pytest


def test_alias_records_allow_ambiguous_names_and_keep_identity_types(tmp_path):
    from core import recognition_aliases as aliases
    aliases.add_alias('同名', 'tv', 42, 'manual', year='2001')
    aliases.add_alias('同名', 'movie', 43, 'tmdb', year='2002')
    aliases.add_alias('同名', 'tv', 44, 'nfo', year='2003')
    result = aliases.find_aliases(' 同名 ')
    assert {(r['media_type'],r['tmdb_id'],r['year']) for r in result} == {('tv',42,'2001'),('movie',43,'2002'),('tv',44,'2003')}


def test_alias_normalization_preserves_roman_numerals_and_multilingual_names(tmp_path):
    from core import recognition_aliases as aliases
    for title in ['作品', '作品 II', 'Title III', 'タイトル', 'Sakuhin']:
        aliases.add_alias(title,'tv',42,'manual')
    assert aliases.find_aliases('作品 ii')[0]['name']=='作品 II'
    assert aliases.find_aliases('作品 i') == []
    assert aliases.find_aliases('タイトル')[0]['tmdb_id']==42
    assert aliases.find_aliases('ＳＡＫＵＨＩＮ')[0]['tmdb_id']==42


def test_ai_alias_is_search_hint_only_and_empty_values_rejected(tmp_path):
    from core import recognition_aliases as aliases
    aliases.add_alias('hint','tv',42,'ai')
    assert aliases.find_aliases('hint')[0]['trusted'] is False
    with pytest.raises(ValueError): aliases.add_alias('  ','tv',42,'manual')
    with pytest.raises(ValueError): aliases.add_alias('title','tv',True,'manual')
    with pytest.raises(ValueError): aliases.add_alias('title','tv',42,'invented')


def test_alias_hot_updates_and_legacy_file_is_untouched(tmp_path):
    import json
    from core import recognition_aliases as aliases
    old=tmp_path/'tmdb_aliases.json'; old.write_text(json.dumps({'Old':{'tmdb_id':9,'media_type':'tv'}}))
    raw=old.read_bytes();before=aliases.revision()
    aliases.add_alias('New','tv',42,'manual')
    assert aliases.revision()!=before and aliases.find_aliases('new')[0]['tmdb_id']==42
    assert old.read_bytes()==raw
    legacy=aliases.find_aliases('old')[0]
    assert legacy['source']=='legacy' and legacy['trusted'] is False
    old.write_text(json.dumps({'Other':{'tmdb_id':8,'media_type':'movie'}}))
    assert aliases.find_aliases('old')==[] and aliases.find_aliases('other')[0]['tmdb_id']==8


def test_bad_alias_schema_is_rejected_without_replacing_data(tmp_path):
    from core import recognition_aliases as aliases
    path=tmp_path/'recognition_aliases_v1.json';path.write_text('{"schema":99,"records":[]}')
    raw=path.read_bytes()
    with pytest.raises(ValueError): aliases.add_alias('Show','tv',42,'manual')
    assert path.read_bytes()==raw


def test_scoped_alias_is_never_applied_outside_scope(tmp_path):
    from core import recognition_aliases as aliases
    root=tmp_path/'source'; scoped=root/'show'; outside=root/'other'
    scoped.mkdir(parents=True); outside.mkdir()
    aliases.add_alias('Show','tv',42,'manual',scope=str(scoped))
    assert aliases.find_aliases('show',src=scoped/'file.mkv')[0]['tmdb_id']==42
    assert aliases.find_aliases('show',src=outside/'file.mkv')==[]
    assert aliases.find_aliases('show')==[]


def test_duplicate_records_are_idempotent(tmp_path):
    from core import recognition_aliases as aliases
    aliases.add_alias('Show','tv',42,'manual')
    before=aliases.revision()
    aliases.add_alias('Show','tv',42,'manual')
    assert aliases.revision()==before and len(aliases.find_aliases('Show'))==1
