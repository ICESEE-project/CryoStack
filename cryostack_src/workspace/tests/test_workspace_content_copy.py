import os
from pathlib import Path
import pytest
from cryostack_src.workspace.copying import copy_workspace_file, copy_workspace_tree


def test_content_only_file_and_tree_need_no_chmod_or_utime(tmp_path,monkeypatch):
    import shutil
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_CONTENT_ONLY","1")
    def unsupported(*a,**k): raise PermissionError("SMB metadata denied")
    monkeypatch.setattr(shutil,"copystat",unsupported)
    source=tmp_path/"source"
    (source/"data").mkdir(parents=True)
    (source/"data/input.csv").write_bytes(b"x,y\n1,2\n")
    destination=tmp_path/"copied"
    copy_workspace_tree(source,destination)
    assert (destination/"data/input.csv").read_bytes()==b"x,y\n1,2\n"
    copy_workspace_file(source/"data/input.csv",destination/"second.csv")
    assert (destination/"second.csv").read_bytes()==b"x,y\n1,2\n"


def test_content_only_tree_refuses_symlinks_before_copy(tmp_path,monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_CONTENT_ONLY","1")
    source=tmp_path/"source";source.mkdir()
    (source/"link").symlink_to(tmp_path/"outside")
    with pytest.raises(ValueError,match="symbolic links"):
        copy_workspace_tree(source,tmp_path/"destination")
    assert not (tmp_path/"destination").exists()


def test_ordinary_local_copy_retains_executable_mode(tmp_path,monkeypatch):
    monkeypatch.delenv("CRYOSTACK_WORKSPACE_CONTENT_ONLY",raising=False)
    source=tmp_path/"script.sh";source.write_text("#!/bin/sh\n")
    source.chmod(0o700)
    copy_workspace_file(source,tmp_path/"copy.sh")
    assert (tmp_path/"copy.sh").stat().st_mode & 0o777 == 0o700


def test_copy_size_counts_files_reached_through_links_and_refuses_cycles(tmp_path):
    from cryostack_src.workspace.copying import workspace_copy_size
    source=tmp_path/"source";source.mkdir()
    outside=tmp_path/"large.bin";outside.write_bytes(b"x"*100)
    (source/"data.bin").symlink_to(outside)
    assert workspace_copy_size(source)==100
    (source/"cycle").symlink_to(source,target_is_directory=True)
    with pytest.raises(ValueError,match="Cyclic"):
        workspace_copy_size(source)


def _managed_mount(tmp_path, monkeypatch):
    import json
    from cryostack_src.workspace.storage_mount import MARKER, SCHEMA
    mount=tmp_path/'managed-volume';mount.mkdir()
    (mount/MARKER).write_text(json.dumps({'schema':SCHEMA,'volume_id':'test-volume'}))
    monkeypatch.delenv('CRYOSTACK_WORKSPACE_CONTENT_ONLY',raising=False)
    monkeypatch.setenv('CRYOSTACK_WORKSPACE_MOUNT',str(mount))
    monkeypatch.setenv('CRYOSTACK_WORKSPACE_VOLUME_ID','test-volume')
    monkeypatch.setattr(os.path,'ismount',lambda p:Path(p).resolve()==mount.resolve())
    return mount


def test_verified_managed_mount_automatically_uses_content_copies(tmp_path,monkeypatch):
    import shutil
    mount=_managed_mount(tmp_path,monkeypatch)
    def unsupported(*_args,**_kwargs):raise PermissionError('forced SMB metadata')
    monkeypatch.setattr(shutil,'copystat',unsupported)
    source=tmp_path/'source';(source/'nested').mkdir(parents=True)
    (source/'runme.m').write_text("md=solve(md,'Stressbalance');\n")
    (source/'nested/input.dat').write_bytes(b'input')
    copy_workspace_tree(source,mount/'working')
    assert (mount/'working/runme.m').read_bytes()==(source/'runme.m').read_bytes()
    assert (mount/'working/nested/input.dat').read_bytes()==b'input'
    copy_workspace_file(source/'nested/input.dat',mount/'input.dat')
    assert (mount/'input.dat').read_bytes()==b'input'


def test_managed_mount_mode_does_not_change_local_destination_metadata(tmp_path,monkeypatch):
    _managed_mount(tmp_path,monkeypatch)
    source=tmp_path/'local.sh';source.write_text('#!/bin/sh\n');source.chmod(0o700)
    copy_workspace_file(source,tmp_path/'local-copy.sh')
    assert (tmp_path/'local-copy.sh').stat().st_mode & 0o777==0o700


def test_managed_mount_copy_fails_closed_if_volume_identity_changes(tmp_path,monkeypatch):
    from cryostack_src.workspace.storage_mount import WorkspaceStorageUnavailable
    mount=_managed_mount(tmp_path,monkeypatch)
    monkeypatch.setenv('CRYOSTACK_WORKSPACE_VOLUME_ID','different-volume')
    source=tmp_path/'source';source.mkdir();(source/'file.txt').write_text('input')
    with pytest.raises(WorkspaceStorageUnavailable):copy_workspace_tree(source,mount/'working')
    assert not (mount/'working').exists()


def test_automatic_content_copy_rejects_symlinks_before_writing(tmp_path,monkeypatch):
    mount=_managed_mount(tmp_path,monkeypatch)
    source=tmp_path/'source';source.mkdir()
    (source/'outside').symlink_to(tmp_path/'outside-file')
    with pytest.raises(ValueError,match='symbolic links'):
        copy_workspace_tree(source,mount/'working')
    assert not (mount/'working').exists()


def test_native_notebook_stages_on_managed_mount_without_metadata_operations(tmp_path,monkeypatch):
    import nbformat,shutil
    from cryostack_src.models.icepack.notebook import materialize_notebook_workspace
    mount=_managed_mount(tmp_path,monkeypatch)
    def unsupported(*_args,**_kwargs):raise PermissionError('forced SMB metadata')
    monkeypatch.setattr(shutil,'copystat',unsupported)
    source=tmp_path/'participant.ipynb'
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell('print(42)')]),source)
    assert materialize_notebook_workspace(source,dest_dir=mount/'working')=='run.py'
    assert (mount/'working/participant.ipynb').read_bytes()==source.read_bytes()
    assert 'print(42)' in (mount/'working/run.py').read_text()
