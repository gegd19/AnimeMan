"""T11: only temporary media, mocked ffmpeg/ffs, no user data or network."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core import subtitle_handler as sub
from core.cancellation import ProcessingCancelled


@pytest.fixture
def media(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    video = source / '[Group] Show.mkv'
    video.write_bytes(b'fake video')
    subtitle = source / '[Group] Show.chs.ass'
    subtitle.write_text('color=&H00FFFF&')
    library = tmp_path / 'library'
    library.mkdir()
    target = library / 'Episode.mkv'
    target.write_bytes(b'fake target video')
    cfg = {'source_folders': [str(source)], 'tv_target_folder': str(library),
           'subtitle_center': {'link_mode': 'copy', 'overwrite_existing': True},
           'subtitle': {'auto_sync': True}, 'link_type': 'symlink'}
    return video, subtitle, target, cfg


@pytest.fixture
def fake_sync(monkeypatch, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    monkeypatch.setattr(sub.tempfile, 'tempdir', str(work))
    monkeypatch.setattr(sub, 'FFSUBSYNC_AVAILABLE', True)
    # Force the formerly destructive ASS repair path.
    def parse(text):
        if '&H00FFFF&' in text:
            raise ValueError('invalid literal for int() with base 16')
    monkeypatch.setitem(sys.modules, 'pysubs2', SimpleNamespace(
        SSAFile=SimpleNamespace(from_string=parse), load=lambda path: parse(Path(path).read_text())))
    monkeypatch.setitem(sys.modules, 'chardet', SimpleNamespace(detect=lambda raw: {'encoding': 'utf-8'}))
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == 'ffprobe':
            return SimpleNamespace(returncode=0, stdout='{"format":{"duration":"3601"}}')
        if cmd[0] == 'ffs':
            assert '&H00FFFF&' not in Path(cmd[cmd.index('-i') + 1]).read_text()
            Path(cmd[cmd.index('-o') + 1]).write_bytes(b'synced subtitle')
        elif cmd[0] == 'ffmpeg' and '-y' in cmd:
            Path(cmd[-1]).write_bytes(b'trimmed video')
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(sub.subprocess, 'run', run)
    return work, calls, run


def organize(subtitle, target, cfg, **kwargs):
    return sub.execute_subtitle_organization(str(subtitle), {
        'target_path': str(target), 'target_dir': str(target.parent)}, cfg, **kwargs)


@pytest.mark.parametrize('automatic', [False, True])
def test_sync_readonly_source_unchanged_language_and_cleanup(media, fake_sync, automatic):
    video, subtitle, target, cfg = media
    original = subtitle.read_bytes()
    source_listing = set(video.parent.iterdir())
    video.parent.chmod(0o555)
    subtitle.chmod(0o444)
    try:
        if automatic:
            cfg['subtitle']['link_subtitles'] = True
            assert sub.process_subtitles_for_video(video, target, target.parent, cfg) == 1
        else:
            cfg['subtitle_center']['link_mode'] = 'symlink'
            assert organize(subtitle, target, cfg, auto_sync=True)
        assert subtitle.read_bytes() == original
        assert set(video.parent.iterdir()) == source_listing
        output = target.with_suffix('.chs.ass')
        assert output.read_bytes() == b'synced subtitle'
        assert not output.is_symlink()
        assert list(fake_sync[0].iterdir()) == []
    finally:
        video.parent.chmod(0o755)
        subtitle.chmod(0o644)


@pytest.mark.parametrize('kind', ['hard', 'symlink', 'broken'])
@pytest.mark.parametrize('automatic', [False, True])
def test_overwrite_replaces_entry_without_writing_old_source(media, kind, automatic):
    video, subtitle, target, cfg = media
    cfg['subtitle']['auto_sync'] = False
    cfg['subtitle']['link_subtitles'] = False
    old_source = video.parent / 'old.ass'
    old_source.write_bytes(b'old source')
    output = target.with_suffix('.chs.ass')
    if kind == 'hard':
        os.link(old_source, output)
    else:
        output.symlink_to(old_source if kind == 'symlink' else video.parent / 'missing.ass')
    if automatic:
        assert sub.process_subtitles_for_video(video, target, target.parent, cfg) == 1
    else:
        assert organize(subtitle, target, cfg)
    assert old_source.read_bytes() == b'old source'
    assert output.read_bytes() == subtitle.read_bytes()
    assert not output.is_symlink()


def test_copy_failure_preserves_existing_target(media, monkeypatch):
    video, subtitle, target, cfg = media
    output = target.with_suffix('.chs.ass')
    output.write_bytes(b'old target')
    def failed_copy(src, dst, *a, **kw):
        Path(dst).write_bytes(b'partial')
        raise OSError('disk full')
    monkeypatch.setattr(sub.shutil, 'copy2', failed_copy)
    assert not organize(subtitle, target, cfg)
    assert output.read_bytes() == b'old target'
    assert set(target.parent.iterdir()) == {target, output}


@pytest.mark.parametrize('command', ['ffs', 'trim'])
@pytest.mark.parametrize('error', ['timeout', 'cancel'])
def test_sync_failure_closes_all_temporary_files(media, fake_sync, monkeypatch, command, error):
    video, subtitle, target, cfg = media
    def fail(cmd, **kwargs):
        if (command == 'ffs' and cmd[0] == 'ffs') or (command == 'trim' and '-y' in cmd):
            if error == 'cancel':
                raise ProcessingCancelled()
            raise subprocess.TimeoutExpired(cmd, 1)
        return fake_sync[2](cmd, **kwargs)
    monkeypatch.setattr(sub.subprocess, 'run', fail)
    if error == 'cancel':
        with pytest.raises(ProcessingCancelled):
            organize(subtitle, target, cfg, auto_sync=True)
    else:
        # Existing fallback to the original subtitle remains available.
        assert organize(subtitle, target, cfg, auto_sync=True)
    assert subtitle.read_text() == 'color=&H00FFFF&'
    assert list(fake_sync[0].iterdir()) == []


def test_literal_brackets_discovery_and_extensions(media):
    video, subtitle, target, cfg = media
    extra = video.parent / 'Subs'
    extra.mkdir()
    nested = extra / (video.stem + '.eng.SRT')
    nested.write_text('subtitle')
    (video.parent / '[Group] Show2.srt').write_text('different episode')
    (video.parent / (video.stem + '.vtt')).mkdir()
    assert set(sub.find_subtitle_files(video, cfg)) == {subtitle, nested}


def rename_item(old, new):
    return {'old_path': str(old), 'new_path': str(new)}


@pytest.mark.parametrize('preview', [False, True])
@pytest.mark.parametrize('conflict', ['duplicate', 'existing', 'cycle', 'outside', 'extension', 'symlink', 'duplicate_source'])
def test_batch_preflight_rejects_without_data_loss(media, tmp_path, preview, conflict):
    video, first, target, cfg = media
    cfg['dry_run'] = preview
    second = first.with_name('second.ass')
    second.write_bytes(b'second')
    new = first.with_name('new.ass')
    items = [rename_item(first, new)]
    if conflict == 'duplicate':
        items.append(rename_item(second, new))
    elif conflict == 'existing':
        items = [rename_item(first, second)]
    elif conflict == 'cycle':
        items = [rename_item(first, second), rename_item(second, first)]
    elif conflict == 'outside':
        items.append(rename_item(second, tmp_path / 'outside.ass'))
    elif conflict == 'extension':
        items.append(rename_item(video, video.with_suffix('.srt')))
    elif conflict == 'symlink':
        link = first.with_name('link.ass')
        link.symlink_to(second)
        items.append(rename_item(link, first.with_name('link-new.ass')))
    else:
        items.append(rename_item(first, first.with_name('another.ass')))
    before = {str(p): p.read_bytes() for p in first.parent.iterdir() if p.is_file()}
    result = sub.batch_rename_subtitles(items, config=cfg)
    assert result['success'] == 0
    assert result['failed'] == len(items)
    assert result.get('planned', 0) == 0
    assert len(result['results']) == len(items)
    assert all(row['error'] for row in result['results'])
    assert {str(p): p.read_bytes() for p in first.parent.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('preview', [False, True])
def test_valid_batch_reports_each_item(media, preview):
    video, old, target, cfg = media
    cfg['dry_run'] = preview
    new = old.with_name('renamed.CHS.ASS')
    before = old.read_bytes()
    result = sub.batch_rename_subtitles([rename_item(old, new)], config=cfg)
    assert result['failed'] == 0
    assert result['success'] == (0 if preview else 1)
    assert result.get('planned', 0) == (1 if preview else 0)
    assert result['results'][0]['status'] == ('planned' if preview else 'success')
    assert old.exists() is preview
    if not preview:
        assert new.read_bytes() == before


def test_rename_destination_race_is_not_overwritten(media, monkeypatch):
    video, old, target, cfg = media
    new = old.with_name('new.ass')
    original = os.link
    def race(src, dst, **kwargs):
        if Path(dst) == new:
            new.write_bytes(b'concurrent file')
        return original(src, dst, **kwargs)
    monkeypatch.setattr(os, 'link', race)
    result = sub.batch_rename_subtitles([rename_item(old, new)], config=cfg)
    assert result['failed'] == 1 and result['success'] == 0
    assert old.exists() and new.read_bytes() == b'concurrent file'


def test_api_returns_per_item_rename_errors(media, client, config_file):
    from core.config_manager import save_config
    video, old, target, cfg = media
    cfg['auth'] = {'enabled': True, 'username': 'test-user', 'password': 'test-pass'}
    save_config(cfg, config_file)
    response = client.post('/api/subtitle/batch_rename', auth=('test-user', 'test-pass'), json={
        'renames': [rename_item(old, video)]})
    assert response.status_code == 200
    assert response.json['failed'] == 1
    assert response.json['results'][0]['error']
    assert old.exists() and video.read_bytes() == b'fake video'


def test_direct_sync_result_owns_metadata_and_explicit_lifetime(media, fake_sync):
    video, subtitle, target, cfg = media
    with sub.sync_subtitle_with_ffsubsync(video, subtitle, cfg) as result:
        assert result.original == subtitle and result.language_suffix == '.chs'
        assert Path(result).read_bytes() == b'synced subtitle'
        path = result.path
    assert not path.exists() and list(fake_sync[0].iterdir()) == []


@pytest.mark.parametrize('kind', ['hard', 'symlink', 'broken'])
def test_no_overwrite_keeps_existing_entry_even_if_broken(media, kind):
    video, subtitle, target, cfg = media
    cfg['subtitle_center']['overwrite_existing'] = False
    old = subtitle.with_name('previous.ass')
    old.write_bytes(b'previous subtitle')
    output = target.with_suffix('.chs.ass')
    if kind == 'hard':
        os.link(old, output)
    else:
        output.symlink_to(old if kind == 'symlink' else old.with_name('missing.ass'))
    stat = output.lstat()
    assert not organize(subtitle, target, cfg)
    assert output.lstat().st_ino == stat.st_ino
    assert old.read_bytes() == b'previous subtitle'


@pytest.mark.parametrize('mode', ['hard', 'symlink', 'copy'])
def test_unsynced_link_modes_remain_readable_after_staging_cleanup(media, mode):
    video, subtitle, target, cfg = media
    cfg['subtitle_center']['link_mode'] = mode
    assert organize(subtitle, target, cfg)
    output = target.with_suffix('.chs.ass')
    assert output.read_bytes() == subtitle.read_bytes()
    assert output.is_symlink() is (mode == 'symlink')
    if mode == 'hard':
        assert os.path.samefile(output, subtitle)
    assert set(target.parent.iterdir()) == {target, output}


def test_automatic_copy_failure_keeps_old_target(media, monkeypatch):
    video, subtitle, target, cfg = media
    cfg['subtitle'].update(auto_sync=False, link_subtitles=False)
    output = target.with_suffix('.chs.ass')
    output.write_bytes(b'old subtitle')
    def fail(src, dst):
        Path(dst).write_bytes(b'partial')
        raise OSError('disk full')
    monkeypatch.setattr(sub.shutil, 'copy2', fail)
    assert sub.process_subtitles_for_video(video, target, target.parent, cfg) == 0
    assert output.read_bytes() == b'old subtitle'
    assert set(target.parent.iterdir()) == {target, output}


def test_no_overwrite_publication_race_is_exclusive(media, monkeypatch):
    video, subtitle, target, cfg = media
    cfg['subtitle_center']['overwrite_existing'] = False
    output = target.with_suffix('.chs.ass')
    original = os.link
    def race(src, dst, **kwargs):
        if Path(dst) == output:
            output.write_bytes(b'concurrent subtitle')
        return original(src, dst, **kwargs)
    monkeypatch.setattr(os, 'link', race)
    assert not organize(subtitle, target, cfg)
    assert output.read_bytes() == b'concurrent subtitle'
    assert set(target.parent.iterdir()) == {target, output}


def test_rename_unlink_error_rolls_back_new_entry(media, monkeypatch):
    video, old, target, cfg = media
    new = old.with_name('renamed.ass')
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path == old:
            raise PermissionError('read-only source folder')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail)
    result = sub.batch_rename_subtitles([rename_item(old, new)], config=cfg)
    assert result['success'] == 0 and result['failed'] == 1
    assert old.read_text() == 'color=&H00FFFF&' and not new.exists()
    assert 'read-only' in result['results'][0]['error']


@pytest.mark.parametrize('case', ['no_roots', 'escape_parent', 'broken_target', 'malformed'])
def test_rename_invalid_paths_never_modify_source(media, tmp_path, case):
    video, old, target, cfg = media
    new = old.with_name('renamed.ass')
    items = [rename_item(old, new)]
    if case == 'no_roots':
        cfg['source_folders'] = []
    elif case == 'escape_parent':
        outside = tmp_path / 'outside'
        outside.mkdir()
        parent = old.parent / 'escape'
        parent.symlink_to(outside, target_is_directory=True)
        items = [rename_item(old, parent / 'new.ass')]
    elif case == 'broken_target':
        new.symlink_to(tmp_path / 'nonexistent.ass')
    else:
        items = [{'old_path': str(old)}, None]
    result = sub.batch_rename_subtitles(items, config=cfg)
    assert result['success'] == 0 and result['failed'] == len(items)
    assert old.read_text() == 'color=&H00FFFF&'
    assert all(row['error'] for row in result['results'])


def test_successful_sync_then_publication_failure_cleans_workspace(media, fake_sync, monkeypatch):
    video, subtitle, target, cfg = media
    output = target.with_suffix('.chs.ass')
    output.write_bytes(b'old target')
    original = sub.shutil.copy2
    def fail(source, destination, *args, **kwargs):
        if Path(source).name == 'synced.ass':
            raise OSError('publish failed')
        return original(source, destination, *args, **kwargs)
    monkeypatch.setattr(sub.shutil, 'copy2', fail)
    assert not organize(subtitle, target, cfg, auto_sync=True)
    assert output.read_bytes() == b'old target'
    assert list(fake_sync[0].iterdir()) == []
    assert set(target.parent.iterdir()) == {target, output}


def test_cancel_before_replace_preserves_old_target_and_cleans_staging(media, monkeypatch):
    video, subtitle, target, cfg = media
    output = target.with_suffix('.chs.ass')
    output.write_bytes(b'old target')
    copied = False
    original = sub.shutil.copy2
    def copy(source, destination, *args, **kwargs):
        nonlocal copied
        result = original(source, destination, *args, **kwargs)
        copied = True
        return result
    def cancelled():
        if copied:
            raise ProcessingCancelled()
    monkeypatch.setattr(sub.shutil, 'copy2', copy)
    monkeypatch.setattr(sub, 'check_cancelled', cancelled)
    with pytest.raises(ProcessingCancelled):
        organize(subtitle, target, cfg)
    assert output.read_bytes() == b'old target'
    assert set(target.parent.iterdir()) == {target, output}
