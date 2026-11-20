"""Downloads must respect storage, retain last good bundles and preserve names."""
import os
from pathlib import Path
import zipfile
import pytest
from test_workspace_files import _mgr,USER_A
from cryostack_src.workspace.models import RunInfo
from cryostack_src.workspace import result_archive,storage_policy
from cryostack_src.workspace.manager import WorkspaceManager
from icesee_jupyter_book.applications.frozen_legacies.radar import quota as Q

class Output:
    def clear_output(self):pass
    def __enter__(self):return self
    def __exit__(self,*args):return False

@pytest.fixture
def case(tmp_path,monkeypatch):
    monkeypatch.delenv('CRYOSTACK_STREAM_DOWNLOADS',raising=False)
    monkeypatch.setenv(Q.STORAGE_DB_ENV,str(tmp_path/'quota.db'))
    monkeypatch.setattr(Q,'disk_status',lambda root:{'free_bytes':100*Q.GIB})
    m=_mgr(USER_A,tmp_path/'workspace',tmp_path);m.results_output=Output()
    run=m.register_run(RunInfo(id='archive-safety',name='Archive',model='icepack',backend='container',execution_mode='local'))
    outputs=run.workspace_directory/'outputs';outputs.mkdir();(outputs/'metrics.txt').write_text('native result')
    m.select_run(run.id)
    monkeypatch.setattr(m,'_auto_download',lambda *args:None)
    cache=run.workspace_directory/'cache';cache.mkdir(exist_ok=True)
    return m,outputs,cache


def test_result_packaging_cannot_bypass_lowered_quota(case):
    m,outputs,cache=case;store,_=storage_policy.policy();store.set_override(USER_A.user_id,1)
    assert m.package_and_download(outputs,cache_dir=cache) is False
    assert not(cache/'results_bundle.zip').exists()
    assert not list(cache.glob('._result-archive-*'))
    assert (outputs/'metrics.txt').read_text()=='native result'


def test_failed_archive_rebuild_preserves_previous_bundle(case,monkeypatch):
    m,outputs,cache=case;cache.mkdir(exist_ok=True);target=cache/'results_bundle.zip';target.write_bytes(b'previous completed archive')
    def fail(*args,**kwargs):raise OSError('Synthetic interrupted compression')
    monkeypatch.setattr(m,'_make_zip',fail)
    assert m.package_and_download(outputs,cache_dir=cache) is False
    assert target.read_bytes()==b'previous completed archive'
    assert not list(cache.glob('._result-archive-*'))


def test_figure_bundle_preserves_nested_duplicate_names_and_uppercase(case,monkeypatch):
    m,outputs,cache=case
    for relative in ('first/figure.png','second/figure.png','UPPER.PNG'):
        p=outputs/relative;p.parent.mkdir(exist_ok=True);p.write_bytes(b'\x89PNG\r\n'+relative.encode())
    bundles=[]
    def capture(path,name):
        with zipfile.ZipFile(path) as z:bundles.append({n:z.read(n) for n in z.namelist()});assert z.testzip() is None
    monkeypatch.setattr(m,'_auto_download',capture)
    m.download_figures()
    assert len(bundles)==1
    assert set(bundles[0])=={'first/figure.png','second/figure.png','UPPER.PNG'}
    assert bundles[0]['first/figure.png']!=bundles[0]['second/figure.png']
    assert not(cache/'_figures_only').exists()


def test_inline_archive_size_checked_before_encoding(tmp_path,monkeypatch):
    p=tmp_path/'large.zip';p.write_bytes(b'x'*2048)
    monkeypatch.setattr(result_archive,'INLINE_ARCHIVE_LIMIT',1024)
    monkeypatch.setattr('cryostack_src.workspace.manager.display',lambda *args:pytest.fail('Do not encode oversized archives'))
    with pytest.raises(result_archive.ArchiveLimitError):WorkspaceManager._auto_download(p)


def test_compression_growth_cannot_exceed_hold_or_destroy_previous_bundle(case,monkeypatch):
    m,outputs,cache=case;cache.mkdir(exist_ok=True);old=cache/'results_bundle.zip';old.write_bytes(b'last-good')
    (outputs/'random.bin').write_bytes(os.urandom(2048))
    monkeypatch.setattr(result_archive,'INLINE_ARCHIVE_LIMIT',256)
    assert m.package_and_download(outputs,cache_dir=cache) is False
    assert old.read_bytes()==b'last-good'
    assert not list(cache.glob('._result-archive-*'))


def test_archive_destination_cannot_escape_owner_or_enter_source(case,tmp_path):
    m,outputs,cache=case
    with pytest.raises(result_archive.UnsafeArchiveError):
        result_archive.prepare_archive(outputs,tmp_path/'outside.zip',owner_root=m._owner_root,user_id=USER_A.user_id,zip_writer=m._make_zip)
    with pytest.raises(result_archive.UnsafeArchiveError):
        result_archive.prepare_archive(outputs,outputs/'recursive.zip',owner_root=m._owner_root,user_id=USER_A.user_id,zip_writer=m._make_zip)
    assert not(outputs/'recursive.zip').exists()


def test_archive_entry_limit_refuses_before_writing(tmp_path,monkeypatch):
    output=tmp_path/'output';output.mkdir()
    for i in range(3):(output/str(i)).write_text('x')
    monkeypatch.setattr(result_archive,'ARCHIVE_ENTRY_LIMIT',2)
    with pytest.raises(result_archive.ArchiveLimitError):result_archive.write_zip(output,tmp_path/'blocked.zip')
    assert not(tmp_path/'blocked.zip').exists()
