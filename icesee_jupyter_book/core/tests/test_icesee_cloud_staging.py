"""Staged ICESEE cloud runs: the launcher's own ICESEE + the staged example +
params.yaml go to <s3-run>/input/, and the runner installs them over the
image's /opt/ICESEE (cloud_runner.py). No AWS is contacted."""
from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core import cloud_runner as cr
from icesee_jupyter_book.core.cloud_bridge_adapter import cloud_runtime_config
from icesee_jupyter_book.core.example_registry import EXAMPLES


def test_the_source_archive_carries_the_package_without_tests_or_data(tmp_path):
    names = tarfile.open(cr.build_icesee_source_archive(tmp_path / "x.tgz")).getnames()
    assert "ICESEE/__init__.py" in names and "ICESEE/src/postprocessing/outputs.py" in names
    assert "ICESEE/applications/icepack_model/examples/synthetic_ice_stream/run_da_icepack.py" in names
    assert not any("src/tests" in n or n.endswith((".h5", ".ipynb")) for n in names)


def test_staging_writes_params_archive_and_a_private_example(tmp_path):
    cfg = EXAMPLES["Icepack · synthetic_ice_stream"]
    inp, example_dir = cr.stage_cloud_input(cfg, tmp_path, {"enkf-parameters": {"Nens": 4}})
    assert sorted(p.name for p in inp.iterdir()) == ["example", "icesee-src.tgz", "params.yaml"]
    assert example_dir.as_posix() == "example/synthetic_ice_stream"
    assert (inp / example_dir / "run_da_icepack.py").is_file()


def test_cloud_examples_cover_lorenz_and_icepack():
    assert cr.ICESEE_CLOUD_EXAMPLES == {"lorenz96": "lorenz", "synthetic_ice_stream": "icepack"}
    assert cr.cloud_max_np() == 2


def test_staged_submit_uploads_input_and_names_the_model(tmp_path):
    calls = []

    def aws(cfg, args):
        calls.append(list(args))
        return (0, json.dumps({"jobId": "j-1"}) if "submit-job" in args else "{}", "")

    result = cr.submit_cloud_example(
        example_name="Icepack · synthetic_ice_stream", example_cfg=EXAMPLES["Icepack · synthetic_ice_stream"],
        config={"enkf-parameters": {"Nens": 4, "execution_mode": 1}}, region="us-east-2", profile=None,
        s3_prefix="s3://bucket/runs", job_queue="q", job_definition="jd", job_name="icesee",
        np=2, nens=4, model_nprocs=0, run_dir_base=tmp_path, run_dir_name="r1", aws=aws)
    sync = next(c for c in calls if c[:2] == ["s3", "sync"])
    assert sync[1:3] == ["sync", str(tmp_path / "r1" / "cloud-input")] and sync[3].endswith("/input/")
    submit = next(c for c in calls if "submit-job" in c)
    env = {e["name"]: e["value"] for e in json.loads(submit[submit.index("--container-overrides") + 1])["environment"]}
    assert env["ICESEE_EXAMPLE"] == "synthetic_ice_stream" and env["ICESEE_MODEL"] == "icepack"
    assert env["ICESEE_INPUT"] == "1" and env["ICESEE_EXAMPLE_DIR"] == "example/synthetic_ice_stream"
    assert env["ICESEE_NP"] == "2" and result.batch_job_id == "j-1"


def test_runtime_config_fits_the_image_without_parallel_hdf5():
    two, changes = cloud_runtime_config({"enkf-parameters": {"execution_mode": 2}}, np=2)
    assert two["enkf-parameters"]["execution_mode"] == 1 and "execution_mode: 2 -> 1" in changes
    one, _ = cloud_runtime_config({"enkf-parameters": {"execution_mode": 2}}, np=1)
    assert one["enkf-parameters"] == {"execution_mode": 0, "parallel_flag": "serial"}
    serial, _ = cloud_runtime_config({"enkf-parameters": {"execution_mode": 0}}, np=2)
    assert serial["enkf-parameters"]["execution_mode"] == 1
    kept, changes = cloud_runtime_config({"enkf-parameters": {"execution_mode": 1, "parallel_flag": "MPI_model"}}, np=2)
    assert kept["enkf-parameters"]["execution_mode"] == 1 and changes == []
