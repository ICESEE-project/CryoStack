"""MATLAB licensing for ISSM container runs is injected from the compute profile.

The public ICESEE image is site-neutral (no license server). CryoStack passes
the compute-resource profile's value explicitly via ``apptainer exec --env`` for
ISSM container runs -- direct and connector, test mode and normal -- and fails
fast (before any Slurm allocation) when no license is configured. Icepack /
Firedrake paths are untouched.
"""
from __future__ import annotations

import base64
import re
import sys
import tempfile
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import cryostack_src.models.submission as submission
from cryostack_src.resources.profiles import ComputeProfile, get_compute_profile

_PACE_VALUE = "1711@matlablic.ecs.gatech.edu"


class _R:
    def __init__(self, out: str = "", rc: int = 0) -> None:
        self.returncode, self.stdout, self.stderr = rc, out, ""


def _decode_sbatch(cmd: str) -> str | None:
    if "run_icesheets.sbatch" not in cmd or "b64decode" not in cmd:
        return None
    for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd), key=len, reverse=True):
        try:
            return base64.b64decode(blob).decode()
        except Exception:
            continue
    return None


@pytest.fixture
def example_dir():
    ex = Path(tempfile.mkdtemp()) / "SquareShelf"
    ex.mkdir()
    (ex / "runme.m").write_text("md.cluster=generic('name',oshostname(),'np',2);\n")
    return ex


@pytest.fixture
def render(monkeypatch, example_dir):
    """Render the sbatch for a container run via either transport."""
    box: dict[str, str] = {}

    def fake_ssh(host, user, port, cmd, timeout=20):
        sb = _decode_sbatch(cmd)
        if sb is not None:
            box["sbatch"] = sb
        if cmd.strip().startswith("sbatch"):
            return _R("Submitted batch job 42\n")
        if cmd.strip().startswith("test -f"):
            return _R("FOUND\n")
        return _R("/home/u/base\n")

    def fake_connector_ssh(session_id, host, user, port, cmd, timeout=20, cluster_name="pace"):
        sb = _decode_sbatch(cmd)
        if sb is not None:
            box["sbatch"] = sb
        return {"ok": True, "stdout": "/home/u/base\n", "stderr": ""}

    monkeypatch.setattr(submission, "ssh_run", fake_ssh)
    monkeypatch.setattr(submission, "resolve_remote_abs_path", lambda *a, **k: "/home/u/base")
    monkeypatch.setattr(submission, "expand_remote_home", lambda x: x)
    monkeypatch.setattr(submission, "subprocess",
                        types.SimpleNamespace(run=lambda *a, **k: _R()), raising=False)
    monkeypatch.setattr(submission, "connector_ssh", fake_connector_ssh)
    monkeypatch.setattr(submission, "connector_stage_archive",
                        lambda *a, **k: {"ok": True, "stdout": "", "stderr": ""})
    monkeypatch.setattr(submission, "connector_slurm_submit",
                        lambda *a, **k: {"ok": True, "submitted": True, "jobid": "42"})

    def _render(*, transport="direct", model="issm", test_mode=False,
                container_source="docker", matlab_license=None):
        box.pop("sbatch", None)
        common = dict(
            host="login", user="u", port=22,
            remote_base_dir="~/base", remote_tag="icesheets",
            backend="container", model=model,
            example_dir=str(example_dir), exec_dir=str(example_dir),
            image_uri="", container_source=container_source,
            spack_enable=False, spack_repo_url="", spack_dirname="ICESEE-Spack",
            spack_install_if_needed=False, spack_install_mode="",
            spack_slurm_dir="", spack_pmix_dir="",
            slurm_time="04:00:00", slurm_job_name="J", slurm_nodes=1, slurm_ntasks=8,
            slurm_tpn=8, slurm_part="cpu", slurm_mem="16G", slurm_account="", slurm_mail="",
            test_mode=test_mode, run_file="", matlab_license=matlab_license,
        )
        if transport == "connector":
            submission.submit_remote_icesheets_via_connector(session_id="s", **common)
        else:
            submission.submit_remote_icesheets(**common)
        return box.get("sbatch", "")

    return _render


def _exec_line(sbatch: str) -> str:
    return next(ln for ln in sbatch.splitlines() if "apptainer exec" in ln and "with-issm" in ln)


# ── 1. PACE profile → configured value on the apptainer exec line ─────────
@pytest.mark.parametrize("transport", ["direct", "connector"])
@pytest.mark.parametrize("test_mode", [False, True])
def test_pace_profile_injects_license_env(render, transport, test_mode):
    if transport == "connector" and test_mode:
        pytest.skip("connector transport has no ISSM container test-mode path")
    sbatch = render(transport=transport, test_mode=test_mode,
                    matlab_license=get_compute_profile("pace").matlab_license_config())
    assert f"--env MLM_LICENSE_FILE={_PACE_VALUE} " in _exec_line(sbatch)
    assert "[container] MATLAB licensing: configured" in sbatch


# ── 2. another profile → its own value ──────────────────────────────────
def test_other_profile_uses_its_own_value(render):
    other = ComputeProfile(name="tacc", matlab_license_value="27000@license.tacc.utexas.edu")
    sbatch = render(matlab_license=other.matlab_license_config())
    assert "--env MLM_LICENSE_FILE=27000@license.tacc.utexas.edu " in _exec_line(sbatch)
    assert _PACE_VALUE not in sbatch


# ── 3. no configured license → clear preflight failure, nothing submitted ─
@pytest.mark.parametrize("transport", ["direct", "connector"])
def test_missing_license_fails_before_submission(render, transport):
    with pytest.raises(RuntimeError, match="MATLAB licensing is not configured"):
        render(transport=transport, matlab_license=None)


def test_missing_license_message_is_actionable(render):
    with pytest.raises(RuntimeError) as ei:
        render(matlab_license={"env_var": "MLM_LICENSE_FILE", "value": "  "})
    assert "[container][ERROR]" in str(ei.value)


# ── 4. connector == direct ─────────────────────────────────────────────
def test_connector_and_direct_inject_identically(render):
    cfg = get_compute_profile("pace").matlab_license_config()
    d = _exec_line(render(transport="direct", matlab_license=cfg))
    c = _exec_line(render(transport="connector", matlab_license=cfg))
    frag = f"--env MLM_LICENSE_FILE={_PACE_VALUE} "
    assert frag in d and frag in c


# ── 5. test mode == normal mode for the license fragment ────────────────
def test_test_mode_and_normal_mode_match_for_license(render):
    cfg = get_compute_profile("pace").matlab_license_config()
    frag = f"--env MLM_LICENSE_FILE={_PACE_VALUE} "
    assert frag in _exec_line(render(test_mode=False, matlab_license=cfg))
    assert frag in _exec_line(render(test_mode=True, container_source="git", matlab_license=cfg))


# ── 6. Icepack is unaffected ───────────────────────────────────────────
def test_icepack_container_run_needs_no_license(render):
    sbatch = render(model="icepack", container_source="git", matlab_license=None)  # no raise
    assert "--env MLM_LICENSE_FILE" not in sbatch
    assert "MATLAB licensing" not in sbatch
    assert "with-icepack" in sbatch


# ── 7. the value never leaks into the log / provenance echoes ───────────
def test_license_value_appears_only_on_the_exec_line(render):
    sbatch = render(matlab_license=get_compute_profile("pace").matlab_license_config())
    hits = [ln for ln in sbatch.splitlines() if _PACE_VALUE in ln]
    assert hits == [_exec_line(sbatch)]
    assert not re.search(r'echo[^\n]*' + re.escape(_PACE_VALUE), sbatch)
