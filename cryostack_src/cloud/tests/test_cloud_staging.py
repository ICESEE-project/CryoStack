"""Cloud Commit 3 -- S3 run-input staging.

stage_example_for_run() stays authoritative: the AWS layer only transports the
StagedExample tree it produced. All S3 calls are mocked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws.models import AWSConfig
from cryostack_src.cloud.drivers.aws.staging import (
    CloudRunStaging,
    CloudStagingError,
    stage_run_inputs,
)
from cryostack_src.models.issm.md_config import (
    OVERRIDE_SCRIPT_NAME, build_md_override_script,
)
from cryostack_src.models.issm import inject_override_step
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

CONFIG = AWSConfig(region="us-east-2")
BUCKET = "cryostack-runs-123456789012"
USER = WorkspaceUser(user_id="user-A", source="cryostack-auth")

_RUNME = (
    "md=model;\n"
    "md=triangle(md,'DomainOutline.exp',100000);\n"
    "md=parameterize(md,'Square.par');\n"
    "md=solve(md,'Stressbalance');\n"
)


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


class FakeS3:
    """Records every `aws s3 ...` invocation; can fail a chosen subcommand."""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, args):
        a = list(args)
        self.calls.append(a)
        if self.fail_on and a[:2] == ["s3", self.fail_on]:
            return (1, "", f"mock S3 {self.fail_on} failure")
        return (0, "", "")

    def synced(self):
        return [c for c in self.calls if c[:2] == ["s3", "sync"]]

    def copied(self):
        return [c for c in self.calls if c[:2] == ["s3", "cp"]]


def _mgr(root, example_dir):
    return WorkspaceManager(
        owner=USER, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(example_dir)), model=_Widget("issm"),
        backend=_Widget("aws"), file_picker=_Widget(), file_editor=_Widget(),
        log_output=None, results_output=None, cluster_host=_Widget(""),
        cluster_user=_Widget(""), cluster_port=_Widget(1), access_mode=_Widget(""),
        normalize_remote_path=lambda p: p, connector_fetch_archive=None,
        should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
        cluster_name=_Widget(""),
    )


@pytest.fixture
def canonical(tmp_path):
    ex = tmp_path / "shipped" / "SquareIceShelf"
    ex.mkdir(parents=True)
    (ex / "runme.m").write_text(_RUNME)
    (ex / "Square.par").write_text("% params\n")
    (ex / "DomainOutline.exp").write_text("## dummy\n1\n")
    return ex


def _staged_with_overrides_and_dataset(tmp_path, canonical):
    """A realistic StagedExample: canonical -> user working copy, Basic-mode
    override injected, a referenced dataset materialised under data/."""
    m = _mgr(tmp_path / "ws", canonical)
    m.save_datasets(({"name": "obs.csv", "content": b"x,y\n0,0\n"},))
    clone = m.clone_example_to_workspace(source=canonical, model="issm", name="run-ex")
    m.reference_dataset(example_path=str(clone), dataset_name="obs.csv",
                        as_path="obs.csv")
    script = build_md_override_script({"stressbalance.maxiter": 30})
    return m.stage_example_for_run(
        source_example=str(clone),
        extra_files={OVERRIDE_SCRIPT_NAME: script},
        entrypoint_transform=inject_override_step,
        overrides={"stressbalance.maxiter": 30},
    )


def _write_postprocess(staged):
    (Path(staged.path) / "postprocess_icesee.m").write_text(
        "% structured export\n", encoding="utf-8")


# ── happy path ─────────────────────────────────────────────────────────
def test_stages_the_staged_example_tree_to_input_prefix(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    s3 = FakeS3()

    result = stage_run_inputs(
        CONFIG, source=staged, model="issm", run_target="runme.m",
        bucket=BUCKET, s3=s3)

    assert isinstance(result, CloudRunStaging)
    assert result.s3_run == f"s3://{BUCKET}/runs/{result.run_id}"
    assert result.s3_input == f"{result.s3_run}/input"
    assert result.s3_outputs == f"{result.s3_run}/outputs"

    # exactly one recursive sync: local staged dir -> input/
    (sync,) = s3.synced()
    assert sync == ["s3", "sync", f"{staged.path}/", f"{result.s3_input}/",
                    "--only-show-errors"]
    # only two S3 prefixes are ever touched
    for call in s3.calls:
        joined = " ".join(call)
        assert "/input" in joined or "/outputs" not in joined
        assert f"s3://{BUCKET}/runs/{result.run_id}/" in joined or call[1] == "cp"


def test_basic_mode_files_dataset_and_postprocess_are_all_staged(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    result = stage_run_inputs(
        CONFIG, source=staged, model="issm", run_target="runme.m",
        bucket=BUCKET, s3=FakeS3())

    files = set(result.staged_files)
    assert OVERRIDE_SCRIPT_NAME in files                       # Basic-mode override
    assert "postprocess_icesee.m" in files                     # structured exporter
    assert "data/obs.csv" in files                             # referenced dataset
    assert "runme.m" in files
    assert "cryostack-run.json" in files                       # execution descriptor
    # the injected runme calls the override before solve()
    runme = (Path(staged.path) / "runme.m").read_text()
    assert f"run('{OVERRIDE_SCRIPT_NAME}')" in runme


def test_execution_descriptor_has_no_absolute_paths_or_secrets(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    s3 = FakeS3()
    result = stage_run_inputs(
        CONFIG, source=staged, model="issm", run_target="runme.m",
        bucket=BUCKET, s3=s3)

    (cp,) = s3.copied()
    assert cp[3] == f"{result.s3_input}/cryostack-run.json"
    local_descriptor = Path(cp[2])
    # the temp file is deleted after upload -- inspect the returned dict instead
    blob = json.dumps(result.descriptor)
    assert "/" not in result.descriptor["run_target"]
    assert result.descriptor["working_directory"] == "."
    for secret in ("1711@matlablic", "MLM_LICENSE", "aws_secret", "/home/",
                   str(staged.path)):
        assert secret not in blob
    assert not local_descriptor.exists()                       # temp cleaned up


def test_license_value_never_appears_in_staged_files_or_result(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    result = stage_run_inputs(
        CONFIG, source=staged, model="issm", run_target="runme.m",
        bucket=BUCKET, s3=FakeS3())

    for f in result.staged_files:
        p = Path(staged.path) / f
        if p.is_file():
            assert "1711@matlablic" not in p.read_text(errors="ignore")
            assert "MLM_LICENSE_FILE" not in p.read_text(errors="ignore")
    blob = repr(result) + " ".join(result.messages)
    assert "1711@matlablic" not in blob and "MLM_LICENSE" not in blob


def test_run_id_is_used_when_supplied(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    result = stage_run_inputs(
        CONFIG, source=staged, model="issm", run_target="runme.m",
        bucket=BUCKET, run_id="cloud-fixed-123", s3=FakeS3())
    assert result.run_id == "cloud-fixed-123"
    assert result.s3_run == f"s3://{BUCKET}/runs/cloud-fixed-123"


# ── failure behaviour ──────────────────────────────────────────────────
def test_failed_upload_raises_and_blocks_submission(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    with pytest.raises(CloudStagingError):
        stage_run_inputs(
            CONFIG, source=staged, model="issm", run_target="runme.m",
            bucket=BUCKET, s3=FakeS3(fail_on="sync"))


def test_failed_descriptor_upload_also_raises(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    with pytest.raises(CloudStagingError):
        stage_run_inputs(
            CONFIG, source=staged, model="issm", run_target="runme.m",
            bucket=BUCKET, s3=FakeS3(fail_on="cp"))


def test_unsupported_model_is_a_clear_error_before_any_upload(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    s3 = FakeS3()
    with pytest.raises(CloudStagingError) as exc:
        stage_run_inputs(
            CONFIG, source=staged, model="firedrake", run_target="run.py",
            bucket=BUCKET, s3=s3)
    assert "firedrake" in str(exc.value)
    assert s3.calls == []                                      # nothing uploaded


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_icepack_staging_succeeds(tmp_path):
    """Icepack staging needs no Basic-mode override machinery -- just its own
    example tree with a real run target, staged exactly like ISSM's."""
    example = tmp_path / "IcepackExample"
    example.mkdir()
    (example / "run.py").write_text("import icepack\nprint('hello icepack')\n")
    (example / "mesh.msh").write_text("dummy mesh\n")

    s3 = FakeS3()
    result = stage_run_inputs(
        CONFIG, source=example, model="icepack", run_target="run.py",
        bucket=BUCKET, s3=s3)

    assert isinstance(result, CloudRunStaging)
    assert result.descriptor["model"] == "icepack"
    assert result.descriptor["run_target"] == "run.py"
    files = set(result.staged_files)
    assert "run.py" in files and "mesh.msh" in files
    assert "cryostack-run.json" in files
    (sync,) = s3.synced()
    assert sync == ["s3", "sync", f"{example}/", f"{result.s3_input}/",
                    "--only-show-errors"]


def test_icepack_staging_rejects_a_missing_run_target_same_as_issm(tmp_path):
    example = tmp_path / "IcepackExample"
    example.mkdir()
    (example / "run.py").write_text("import icepack\n")
    with pytest.raises(CloudStagingError):
        stage_run_inputs(
            CONFIG, source=example, model="icepack", run_target="missing.py",
            bucket=BUCKET, s3=FakeS3())


def test_missing_run_target_is_rejected(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    with pytest.raises(CloudStagingError):
        stage_run_inputs(
            CONFIG, source=staged, model="issm", run_target="nope.m",
            bucket=BUCKET, s3=FakeS3())


def test_accepts_a_plain_path_too(tmp_path, canonical):
    staged = _staged_with_overrides_and_dataset(tmp_path, canonical)
    _write_postprocess(staged)
    result = stage_run_inputs(
        CONFIG, source=str(staged.path), model="issm", run_target="runme.m",
        bucket=BUCKET, s3=FakeS3())
    assert result.run_id.startswith("cloud-")


# ── Icepack cloud checkpoint: the output collector rides with run inputs,
#    never inline in the Batch runner command (fixed "Container Overrides
#    length must be at most 8192") ──────────────────────────────────────
class RealFileTransferS3:
    """A fake ``aws s3 ...`` that performs REAL file copies between local
    directories keyed by an ``s3://bucket/key`` path -- the same end-to-end
    guarantee ``aws s3 sync`` gives in production (a file present at the
    sync source is present, byte-for-byte, at the destination), without
    contacting AWS. Lets a test prove a file survives staging's upload AND
    the cloud runner's own download, through the identical transport call
    both actually use."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[list[str]] = []

    def _local(self, uri_or_path: str) -> Path:
        if uri_or_path.startswith("s3://"):
            return self.root / uri_or_path[len("s3://"):]
        return Path(uri_or_path)

    def __call__(self, args):
        a = list(args)
        self.calls.append(a)
        if a[:2] == ["s3", "sync"]:
            src, dst = self._local(a[2]), self._local(a[3])
            dst.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        target = dst / f.relative_to(src)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(f.read_bytes())
            return (0, "", "")
        if a[:2] == ["s3", "cp"]:
            src, dst = self._local(a[2]), self._local(a[3])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            return (0, "", "")
        return (0, "", "")


def test_icepack_postprocess_helper_is_staged_and_locatable_after_input_sync(tmp_path):
    """The full contract, end to end, with REAL file transport (no AWS):

    WorkspaceManager.stage_example_for_run(extra_files=...) writes the
    collector alongside run.py in the LOCAL working copy
    -> stage_run_inputs uploads that whole tree verbatim to s3://.../input/
       (the SAME sync stage_run_inputs already performs for every other
       staged file)
    -> the cloud runner's own phase 1 (``aws s3 sync .../input/ WORKDIR/``,
       simulated here with the identical transport) downloads it back down

    and the file the job's Icepack branch looks for
    (``${WORKDIR}/cryostack_icepack_postprocess.py``) is present, with the
    real collector source -- not a stub, not merely "some file exists"."""
    from cryostack_src.cloud.runtime import (
        ICEPACK_POSTPROCESS_FILENAME,
        RUN_DESCRIPTOR_NAME,
        icepack_postprocess_extra_files,
    )
    from cryostack_src.models.icepack.postprocess import build_postprocess

    canon = tmp_path / "shipped" / "IcepackExample"
    canon.mkdir(parents=True)
    (canon / "run.py").write_text("print('hello icepack')\n")

    mgr = _mgr(tmp_path / "ws", canon)
    mgr.model.value = "icepack"
    staged = mgr.stage_example_for_run(
        source_example=str(canon), entrypoint="run.py",
        extra_files=icepack_postprocess_extra_files(),
    )
    # staged onto disk alongside run.py, in the user's OWN working copy --
    # exactly the same mechanism as ISSM's postprocess_icesee.m
    assert (Path(staged.path) / ICEPACK_POSTPROCESS_FILENAME).is_file()
    assert (Path(staged.path) / ICEPACK_POSTPROCESS_FILENAME).read_text() \
        == build_postprocess()

    s3 = RealFileTransferS3(tmp_path / "fake-s3")
    result = stage_run_inputs(
        CONFIG, source=staged, model="icepack", run_target="run.py",
        bucket=BUCKET, s3=s3)
    assert ICEPACK_POSTPROCESS_FILENAME in set(result.staged_files)

    # the cloud runner's own phase 1: sync input/ -> WORKDIR
    workdir = tmp_path / "workdir"
    code, _, _ = s3(["s3", "sync", f"{result.s3_input}/", f"{workdir}/",
                     "--only-show-errors"])
    assert code == 0

    located = workdir / ICEPACK_POSTPROCESS_FILENAME
    assert located.is_file(), (
        "the job cannot locate the staged postprocess helper after "
        "downloading its inputs from S3"
    )
    assert located.read_text() == build_postprocess()
    assert (workdir / "run.py").is_file()          # run.py travels the same way
    assert (workdir / RUN_DESCRIPTOR_NAME).is_file()   # the execution descriptor too


def test_icepack_run_without_the_collector_still_stages_and_locates_run_py(tmp_path):
    """A caller that does not pass extra_files (e.g. an older code path)
    must not be blocked -- run.py itself always stages and locates fine;
    the runner's own graceful skip (tested in test_cloud_runtime.py) is the
    other half of this contract."""
    from cryostack_src.cloud.runtime import ICEPACK_POSTPROCESS_FILENAME

    canon = tmp_path / "shipped" / "IcepackExample2"
    canon.mkdir(parents=True)
    (canon / "run.py").write_text("print('hello icepack')\n")
    mgr = _mgr(tmp_path / "ws", canon)
    mgr.model.value = "icepack"
    staged = mgr.stage_example_for_run(source_example=str(canon), entrypoint="run.py")
    assert not (Path(staged.path) / ICEPACK_POSTPROCESS_FILENAME).exists()

    s3 = RealFileTransferS3(tmp_path / "fake-s3")
    result = stage_run_inputs(
        CONFIG, source=staged, model="icepack", run_target="run.py",
        bucket=BUCKET, s3=s3)
    assert ICEPACK_POSTPROCESS_FILENAME not in set(result.staged_files)
    workdir = tmp_path / "workdir2"
    s3(["s3", "sync", f"{result.s3_input}/", f"{workdir}/", "--only-show-errors"])
    assert (workdir / "run.py").is_file()
