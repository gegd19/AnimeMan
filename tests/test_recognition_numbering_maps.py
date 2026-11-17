"""E05: bounded, explicit mappings; all inputs and storage are temporary."""
import pytest


def source(tmp_path):
    root=tmp_path/'source'; folder=root/'Show'/'Part 2';folder.mkdir(parents=True)
    src=folder/'Show EP01.mkv';src.write_bytes(b'synthetic')
    return {'source_folders':[str(root)]},folder,src


def test_exact_mapping_keeps_decimal_literal_and_targets_special(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_exact(cfg, str(folder), 42, '12.5', 0, 3)
    rule=maps.match(cfg,src,42,'12.5')
    assert (rule['season'],rule['episode'],rule['source_label'])==(0,3,'12.5')
    assert maps.match(cfg,src,42,'12') is None
    assert src.read_bytes()==b'synthetic'


def test_different_source_and_target_conflicts_are_rejected(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_exact(cfg,str(folder),42,'1',1,13)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'1',1,14)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'2',1,13)
    with pytest.raises(maps.MappingConflict):maps.match(cfg,src,43,'1')


def test_range_is_bounded_and_rejects_overlap_and_duplicate_target(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_range(cfg,str(folder),42,1,3,1,13)
    assert maps.match(cfg,src,42,'2')['episode']==14
    assert maps.match(cfg,src,42,'4') is None
    with pytest.raises(maps.MappingConflict):maps.add_range(cfg,str(folder),42,3,5,2,1)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'9',1,14)
    with pytest.raises(ValueError):maps.add_range(cfg,str(folder),42,2,1,1,1)
    with pytest.raises(ValueError):maps.add_range(cfg,str(folder),42,1,1001,1,1)


def test_scopes_are_bounded_and_disabling_invalidates_revision(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    external=tmp_path/'outside';external.mkdir()
    with pytest.raises(ValueError):maps.add_exact(cfg,str(external),42,'1',1,1)
    link=folder/'link';link.symlink_to(external,target_is_directory=True)
    with pytest.raises(ValueError):maps.add_exact(cfg,str(link),42,'1',1,1)
    rule=maps.add_exact(cfg,str(folder),42,'1',1,13)
    before=maps.revision();maps.set_enabled(rule['id'],False)
    assert maps.revision()!=before and maps.match(cfg,src,42,'1') is None


def test_unsupported_store_is_never_overwritten(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    path=tmp_path/'recognition_numbering_maps_v1.json';path.write_text('{"schema":99,"rules":[]}')
    before=path.read_bytes()
    with pytest.raises(ValueError):maps.add_exact(cfg,str(folder),42,'1',1,13)
    assert path.read_bytes()==before


def test_conflicting_manually_edited_store_is_rejected(tmp_path):
    import json
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_exact(cfg,str(folder),42,'1',1,13)
    path=tmp_path/'recognition_numbering_maps_v1.json';state=json.loads(path.read_text())
    other=dict(state['rules'][0],id='other',source_label='2')
    state['rules'].append(other);path.write_text(json.dumps(state));before=path.read_bytes()
    with pytest.raises(maps.MappingConflict):maps.match(cfg,src,42,'1')
    assert path.read_bytes()==before
