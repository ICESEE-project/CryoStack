from contextlib import contextmanager
import json
from pathlib import Path
import pytest
from cryostack_src.workspace.s3_contents import fetch_s3_contents


@contextmanager
def allowed(size): yield


def transport(payload=b"result", *, key="runs/case/outputs/fields/h.csv", fail=False):
    calls=[]
    def invoke(args):
        calls.append(args)
        if args[1]=="list-objects-v2":
            return 0,json.dumps({"Contents":[{"Key":key,"Size":len(payload),"ETag":"test-etag"}]}),""
        assert args[1]=="get-object" and args[args.index("--if-match")+1]=="test-etag"
        if fail:return 1,"","failure"
        Path(args[-1]).write_bytes(payload)
        return 0,"{}",""
    return invoke,calls


def test_downloads_directly_and_replaces_only_after_success(tmp_path):
    destination=tmp_path/"cedar"/"outputs";destination.mkdir(parents=True)
    (destination/"old.txt").write_text("old")
    invoke,calls=transport()
    fetch_s3_contents("s3://bucket/runs/case",destination,invoke=invoke,reserve=allowed)
    assert (destination/"fields/h.csv").read_bytes()==b"result"
    assert not (destination/"old.txt").exists()
    assert Path(calls[-1][-1]).parent.parent.parent==destination.parent
    assert not list(destination.parent.glob(".cloud-incoming-*"))


def test_failed_transfer_preserves_previous_results(tmp_path):
    destination=tmp_path/"outputs";destination.mkdir()
    (destination/"old.txt").write_text("old")
    invoke,calls=transport(fail=True)
    with pytest.raises(RuntimeError):fetch_s3_contents("s3://bucket/runs/case",destination,invoke=invoke,reserve=allowed)
    assert (destination/"old.txt").read_text()=="old"
    assert not list(tmp_path.glob(".cloud-incoming-*"))


def test_quota_refusal_happens_before_download(tmp_path):
    invoke,calls=transport()
    @contextmanager
    def refused(size):raise RuntimeError("quota exceeded");yield
    with pytest.raises(RuntimeError,match="quota"):
        fetch_s3_contents("s3://bucket/runs/case",tmp_path/"outputs",invoke=invoke,reserve=refused)
    assert len(calls)==1
    assert not (tmp_path/"outputs").exists()


@pytest.mark.parametrize("key",["runs/case/outputs/../../escape","runs/other/outputs/file"])
def test_unexpected_s3_paths_are_refused_before_download(tmp_path,key):
    invoke,calls=transport(key=key)
    with pytest.raises(ValueError):fetch_s3_contents("s3://bucket/runs/case",tmp_path/"outputs",invoke=invoke,reserve=allowed)
    assert len(calls)==1
