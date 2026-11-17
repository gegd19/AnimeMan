"""E03: bounded, source-scoped folder evidence from synthetic scanned files."""
from pathlib import Path


def make_files(tmp_path, names):
    root = tmp_path / 'source'
    folder = root / 'Show'
    folder.mkdir(parents=True)
    files = []
    for name in names:
        path = folder / name
        path.write_bytes(b'synthetic')
        files.append(path)
    return root, folder, files


def test_mixed_titles_are_grouped_without_majority_override(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, ['Show S01E01.mkv', 'Show S01E02.mkv', 'Other S01E01.mkv'])
    result = collect_folder_evidence(folder, files, {'source_folders':[str(root)]})
    assert result['complete'] and result['identity_status'] == 'conflict'
    assert sorted(group['title'] for group in result['groups']) == ['Other', 'Show']


def test_release_groups_do_not_create_independent_identity_evidence(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, ['[A] Show S01E01.mkv', '[B] Show S01E02.mkv'])
    result = collect_folder_evidence(folder, files, {'source_folders':[str(root)]})
    assert len(result['groups']) == 1 and result['identity_status'] == 'unconfirmed'
    assert 'confidence' not in result


def test_sampling_is_bounded_stable_and_no_file_content_read(tmp_path, monkeypatch):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, [f'Show S01E{i:02}.mkv' for i in range(1, 70)])
    monkeypatch.setattr(Path, 'open', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not open media')))
    first = collect_folder_evidence(folder, files, {'source_folders':[str(root)]}, limit=5)
    second = collect_folder_evidence(folder, list(reversed(files)), {'source_folders':[str(root)]}, limit=5)
    assert first == second and first['sampled'] == 5 and not first['complete']
    assert first['identity_status'] == 'unconfirmed'


def test_fingerprint_changes_after_file_replacement_or_addition(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, ['Show S01E01.mkv'])
    cfg={'source_folders':[str(root)]}
    before=collect_folder_evidence(folder, files, cfg)['fingerprint']
    files[0].unlink(); files[0].write_bytes(b'replacement')
    replaced=collect_folder_evidence(folder, files, cfg)['fingerprint']
    more=folder/'Show S01E02.mkv';more.write_bytes(b'synthetic')
    added=collect_folder_evidence(folder, files+[more], cfg)['fingerprint']
    assert len({before,replaced,added}) == 3


def test_outside_source_and_symlink_are_not_evidence(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files=make_files(tmp_path, ['Show S01E01.mkv'])
    other=tmp_path/'Other S01E01.mkv';other.write_bytes(b'synthetic')
    link=folder/'Other S01E01.mkv';link.symlink_to(other)
    result=collect_folder_evidence(folder, files+[other,link], {'source_folders':[str(root)]})
    assert result['sampled']==1 and len(result['groups'])==1
