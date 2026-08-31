"""Cloud Commit 3 -- the generic cloud runtime contract (descriptor + runner)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.runtime import (
    RESULT_CONTRACT_VERSION,
    RUN_DESCRIPTOR_NAME,
    SUPPORTED_CLOUD_MODELS,
    CloudRuntimeError,
    build_cloud_runner,
    build_run_descriptor,
    cloud_run_command,
    descriptor_is_clean,
    is_supported_cloud_model,
)


# ── execution descriptor ─────────────────────────────────────────────────
def test_descriptor_carries_only_execution_inputs():
    d = build_run_descriptor(model="ISSM", run_target="runme.m")
    assert d == {
        "schema": "cryostack.cloud.run", "version": 1, "model": "issm",
        "run_target": "runme.m", "working_directory": ".",
        "result_contract_version": RESULT_CONTRACT_VERSION,
    }
    assert descriptor_is_clean(d) is True


@pytest.mark.parametrize("bad", [
    {"run_target": "/abs/runme.m"},
    {"run_target": "../escape.m"},
    {"run_target": ""},
    {"model": ""},
    {"run_target": "runme.m", "working_directory": "/abs"},
    {"run_target": "runme.m", "working_directory": "../up"},
])
def test_descriptor_rejects_unsafe_inputs(bad):
    kw = {"model": "issm", "run_target": "runme.m"}
    kw.update(bad)
    with pytest.raises(CloudRuntimeError):
        build_run_descriptor(**kw)


def test_descriptor_is_clean_flags_secrets_and_paths():
    assert descriptor_is_clean({"x": "/home/alice/thing"}) is False
    assert descriptor_is_clean({"x": "MLM_LICENSE_FILE=1711@server"}) is False
    assert descriptor_is_clean({"x": "aws_secret_access_key"}) is False
    assert descriptor_is_clean({"model": "issm", "run_target": "runme.m"}) is True


def test_supported_models():
    assert SUPPORTED_CLOUD_MODELS == ("issm",)
    assert is_supported_cloud_model("ISSM") is True
    assert is_supported_cloud_model("icepack") is False


# ── the runner ───────────────────────────────────────────────────────────
def test_runner_is_env_driven_and_backend_neutral():
    r = build_cloud_runner()
    for var in ("CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"):
        assert var in r
    # three phases: input sync -> model runtime -> output sync
    assert 'aws s3 sync "${CRYOSTACK_S3_RUN}/input/"' in r
    assert 'aws s3 sync "${OUTPUTS}/" "${CRYOSTACK_S3_RUN}/outputs/"' in r
    # nothing about which execution mode / SIF / cluster produced the run
    for token in ("apptainer", "srun", "sbatch", "ssh", "rsync", "spack"):
        assert token not in r


def test_runner_issm_runs_target_then_postprocess():
    r = build_cloud_runner()
    assert "with-issm matlab" in r
    assert "run('${RUN_TARGET}')" in r
    assert "run('${WORKDIR}/postprocess_icesee.m')" in r


def test_runner_propagates_true_exit_code_no_swallowing():
    lines = build_cloud_runner().splitlines()
    body = [l for l in lines if not l.lstrip().startswith("#")]
    joined = "\n".join(body)
    assert "|| true" not in joined                       # never swallow the science
    assert "rc=$?" in joined                             # capture the real code
    assert 'exit "${rc}"' in joined                      # ... and propagate it
    # the matlab invocation itself has no "|| true" / "; true" tail
    matlab_line = next(l for l in body if "with-issm matlab" in l)
    assert "true" not in matlab_line


def test_runner_uploads_outputs_even_on_failure():
    r = build_cloud_runner()
    # output sync is guarded only by "outputs dir exists", not by "rc == 0"
    idx_science = r.index("model runtime exit code")
    idx_upload = r.index('aws s3 sync "${OUTPUTS}/"')
    assert idx_upload > idx_science
    assert 'if [ -d "${OUTPUTS}" ]; then' in r


def test_runner_carries_no_license_value():
    r = build_cloud_runner()
    assert "1711@matlablic" not in r
    assert "MLM_LICENSE_FILE=" not in r                  # only ever from batch env


def test_runner_unsupported_model_errors_clearly():
    r = build_cloud_runner()
    assert 'fail 64 "Icepack cloud execution is not supported yet"' in r
    assert 'fail 64 "unsupported model: ${CRYOSTACK_MODEL}"' in r


def test_cloud_run_command_wraps_the_runner():
    cmd = cloud_run_command()
    assert cmd[:2] == ["bash", "-c"]
    assert cmd[2] == build_cloud_runner()
