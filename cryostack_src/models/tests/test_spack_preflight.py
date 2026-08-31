"""A scientific ICESEE-Spack run is blocked unless the live probe reports Ready.

Covers both transports; asserts no synchronous install ever runs at submission.
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


class _R:
    def __init__(self, out="", rc=0):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def _probe_reply(ready: bool) -> str:
    if not ready:
        return "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_ACTIVATE=ok\nCRYOSTACK_ENV_MODEL=fail:issm_exe_missing\n"
    return "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_ACTIVATE=ok\nCRYOSTACK_ENV_MODEL=ok\n"


@pytest.fixture
def example_dir():
    ex = Path(tempfile.mkdtemp()) / "SquareShelf"
    ex.mkdir()
    (ex / "runme.m").write_text("md.cluster=generic('name',oshostname(),'np',2);\n")
    return ex


@pytest.fixture
def render(monkeypatch, example_dir):
    box: dict[str, str] = {}
    calls: list[str] = []

    def fake_ssh(host, user, port, cmd, timeout=20):
        calls.append(cmd)
        if "os.path.abspath" in cmd or "spack_path" in cmd or cmd.strip().startswith("git"):
            return _R("/home/u/base\n")
        if "CRYOSTACK_ENV_REPO" in cmd:
            return _R(_probe_reply(box["ready"]))
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd), key=len, reverse=True):
                try:
                    box["sbatch"] = base64.b64decode(blob).decode()
                    break
                except Exception:
                    continue
            return _R("ok\n")
        if cmd.strip().startswith("sbatch"):
            return _R("Submitted batch job 4242\n")
        if cmd.strip().startswith("test -f"):
            return _R("FOUND\n")
        return _R("/home/u/base\n")

    def fake_connector_ssh(session_id, host, user, port, cmd, timeout=20, cluster_name="pace"):
        r = fake_ssh(host, user, port, cmd, timeout)
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}

    def fake_ensure_spack(host, user, port, parent, name, repo):
        return f"{parent}/{name}", (0, f"{parent}/{name}\n", "")

    monkeypatch.setattr(submission, "ssh_run", fake_ssh)
    monkeypatch.setattr(submission, "connector_ssh", fake_connector_ssh)
    monkeypatch.setattr(submission, "remote_ensure_spack", fake_ensure_spack)
    monkeypatch.setattr(submission, "resolve_remote_abs_path",
                        lambda host, user, port, p: p.replace("~", "/home/u"))
    monkeypatch.setattr(submission, "expand_remote_home", lambda x: x)
    monkeypatch.setattr(submission, "connector_stage_archive",
                        lambda *a, **k: {"ok": True, "stdout": "", "stderr": ""})
    monkeypatch.setattr(submission, "connector_slurm_submit",
                        lambda *a, **k: {"ok": True, "submitted": True, "jobid": "4242"})
    monkeypatch.setattr(submission, "subprocess",
                        types.SimpleNamespace(run=lambda *a, **k: _R()), raising=False)

    def _render(*, transport="direct", ready=True, model="issm"):
        box.clear()
        box["ready"] = ready
        calls.clear()
        common = dict(
            host="login", user="u", port=22,
            remote_base_dir="~/base", remote_tag="icesheets",
            backend="spack", model=model,
            example_dir=str(example_dir), exec_dir=str(example_dir),
            image_uri="", container_source="git",
            spack_enable=True,
            spack_repo_url="https://github.com/ICESEE-project/ICESEE-Spack.git",
            spack_dirname="ICESEE-Spack",
            spack_install_if_needed=False, spack_install_mode="--with-issm",
            spack_slurm_dir="", spack_pmix_dir="",
            slurm_time="01:00:00", slurm_job_name="J", slurm_nodes=1, slurm_ntasks=8,
            slurm_tpn=8, slurm_part="cpu", slurm_mem="16G", slurm_account="", slurm_mail="",
            test_mode=False, run_file="",
        )
        if transport == "connector":
            submission.submit_remote_icesheets_via_connector(session_id="s", **common)
        else:
            submission.submit_remote_icesheets(**common)
        return box.get("sbatch", ""), calls

    _render.box = box
    return _render


@pytest.mark.parametrize("transport", ["direct", "connector"])
def test_run_blocked_when_environment_not_ready(render, transport):
    with pytest.raises(RuntimeError, match="ICESEE-Spack is not ready"):
        render(transport=transport, ready=False)


@pytest.mark.parametrize("transport", ["direct", "connector"])
def test_run_succeeds_after_ready(render, transport):
    sbatch, _ = render(transport=transport, ready=True)
    assert "#SBATCH" in sbatch
    assert 'source "/home/u/base/ICESEE-Spack/scripts/activate.sh"' in sbatch


def test_no_synchronous_install_is_ever_run_at_submission(render):
    _, calls = render(transport="direct", ready=True)
    joined = "\n".join(calls)
    assert "install.sh" not in joined            # decision 5
    assert "./scripts/install.sh" not in joined


def test_direct_and_connector_block_identically(render):
    for transport in ("direct", "connector"):
        with pytest.raises(RuntimeError, match="Check or prepare the environment"):
            render(transport=transport, ready=False)
