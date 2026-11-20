"""Offline input/output/log guards; real UID dropping is qualified in Docker."""
import io
import json
from pathlib import Path
import stat
import zipfile
import pytest
from cryostack_src.cloud import pilot_worker as worker


def zipped(entries):
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return content.getvalue()


def test_clean_input_keeps_relative_and_unicode_names(tmp_path):
    data = zipped([('run.py', b'print(1)'), ('data/shelf notes Δ.json', b'{}')])
    root = worker.safe_extract(data, tmp_path / 'model', uid=None)
    assert (root / 'data/shelf notes Δ.json').read_bytes() == b'{}'


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../../escape', 'a\\b', 'outputs/old.json', 'a//b'])
def test_unsafe_and_preexisting_output_paths_are_refused_before_extract(tmp_path, name):
    root = tmp_path / 'model'
    with pytest.raises(ValueError):
        worker.safe_extract(zipped([(name, b'x')]), root, uid=None)
    assert not root.exists()


def test_duplicate_paths_are_refused(tmp_path):
    with pytest.raises(ValueError, match='duplicate'):
        worker.safe_extract(zipped([('run.py', b'a'), ('run.py', b'b')]), tmp_path/'model', uid=None)


def test_symlink_archive_entry_is_refused(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        link = zipfile.ZipInfo('data/link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, '/outside')
    with pytest.raises(ValueError):
        worker.safe_extract(output.getvalue(), tmp_path/'model', uid=None)


def test_expansion_is_bounded_before_destination_is_created(tmp_path):
    data = zipped([('data/big', b'0'*4096)])
    with pytest.raises(ValueError):
        worker.safe_extract(data, tmp_path/'model', uid=None, byte_limit=1024)
    assert not (tmp_path/'model').exists()


def test_secret_redaction_survives_arbitrary_pipe_chunk_boundaries():
    writes=[]
    log=worker.BoundedLog(writes.append, limit=64, secrets=[b'PRIVATE-CAPABILITY'])
    for data in (b'prefix PRIV', b'ATE-CAPA', b'BILITY suffix'):
        log.feed(data)
    log.feed(b'', final=True)
    assert b''.join(writes)==b'prefix [redacted] suffix'


def test_log_forwarding_is_bounded_even_after_truncation():
    writes=[]
    log=worker.BoundedLog(writes.append, limit=64)
    for _ in range(4):log.feed(b'x'*1000)
    log.feed(b'', final=True)
    assert len(b''.join(writes))==64 and log.truncated and log.written==64


@pytest.mark.parametrize('name', sorted(worker.CREDENTIAL_ENV))
def test_task_role_or_credential_injection_is_refused(name):
    with pytest.raises(PermissionError):worker.assert_no_task_credentials({name:'synthetic-canary'})


def test_child_only_gets_image_runtime_environment(tmp_path):
    result=worker.child_environment({'PATH':'/bin','PETSC_DIR':'/opt/petsc',
        'CRYOSTACK_TRANSFER_TOKEN':'private','CRYOSTACK_SESSION_SECRET':'private',
        'GOOGLE_CLIENT_SECRET':'private','PYTHONSTARTUP':'/private.py'},tmp_path)
    assert result['PETSC_DIR']=='/opt/petsc'
    assert not set(result)&{'CRYOSTACK_TRANSFER_TOKEN','CRYOSTACK_SESSION_SECRET','GOOGLE_CLIENT_SECRET','PYTHONSTARTUP'}
    assert result['HOME']==str(tmp_path/'home')


def test_gateway_user_cannot_run_the_container_supervisor(monkeypatch,tmp_path):
    monkeypatch.setattr(worker.os,'geteuid',lambda:1000)
    with pytest.raises(PermissionError):worker.run_science(['/bin/true'],tmp_path,seconds=1)


def test_outputs_preserve_nested_names_and_private_receipt(tmp_path):
    root=tmp_path/'outputs';root.mkdir()
    for name in ('a/same.txt','b/same.txt'):
        path=root/name;path.parent.mkdir();path.write_text(name)
    result=worker.package_outputs(root,tmp_path/'out.zip',{'model_processes_stopped':True,'exit_code':0})
    with zipfile.ZipFile(result) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={'a/same.txt','b/same.txt','.cryostack-worker.json'}


def test_outputs_are_not_collected_while_model_processes_remain(tmp_path):
    with pytest.raises(PermissionError):worker.package_outputs(tmp_path,tmp_path/'out.zip',{'model_processes_stopped':False})
    assert not(tmp_path/'out.zip').exists()


def test_output_links_and_oversize_are_refused(tmp_path):
    root=tmp_path/'outputs';root.mkdir();(root/'link').symlink_to(tmp_path/'private')
    with pytest.raises(ValueError):worker.package_outputs(root,tmp_path/'out.zip',{'model_processes_stopped':True})
    (root/'link').unlink();(root/'big').write_bytes(b'x'*2048)
    with pytest.raises(ValueError):worker.package_outputs(root,tmp_path/'out.zip',{'model_processes_stopped':True},byte_limit=1024)


@pytest.mark.parametrize('origin', ['http://example.com','https://user:password@example.com',
    'https://example.com/path','https://example.com?token=private','file:///private'])
def test_transfer_refuses_unreviewed_origin_forms_before_network(origin):
    with pytest.raises(ValueError):worker.transfer(origin,'a'*32,'input','x'*43)
