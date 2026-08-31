"""RemoteBridge ICESEE-Spack lifecycle: environment_status + prepare (direct == connector)."""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import cryostack_src.remote.bridge as bridge_mod
from cryostack_src.remote import RemoteBridge
from cryostack_src.remote.spack_env import EnvStatus

_BASE_ABS = "/home/u/base"
_REPO = f"{_BASE_ABS}/ICESEE-Spack"


class _R:
    def __init__(self, out="", rc=0):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class FakeResource:
    """One in-memory HPC resource, driven through either transport."""

    def __init__(self, *, repo_present=False, activate_ok=True, model_ok=True):
        self.repo_present = repo_present
        self.activate_ok = activate_ok
        self.model_ok = model_ok
        self.submitted_scripts: list[str] = []
        self.written: dict[str, str] = {}
        self._next_file = None

    def run(self, script: str) -> tuple[int, str, str]:
        if "os.path.abspath" in script:
            return 0, _BASE_ABS + "\n", ""
        if "CRYOSTACK_ENV_REPO" in script:                       # probe
            if not self.repo_present:
                return 0, "CRYOSTACK_ENV_REPO=absent\n", ""
            lines = ["CRYOSTACK_ENV_REPO=present", "CRYOSTACK_ENV_MARKER=absent"]
            if not self.activate_ok:
                lines.append("CRYOSTACK_ENV_ACTIVATE=fail:source_error")
                return 0, "\n".join(lines) + "\n", ""
            lines.append("CRYOSTACK_ENV_ACTIVATE=ok")
            lines.append("CRYOSTACK_ENV_MODEL=ok" if self.model_ok
                         else "CRYOSTACK_ENV_MODEL=fail:issm_exe_missing")
            return 0, "\n".join(lines) + "\n", ""
        if script.startswith("mkdir -p"):
            return 0, "", ""
        if "base64.b64decode" in script and "write_text" in script:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{40,}={0,2}", script), key=len, reverse=True):
                try:
                    self.written["last"] = base64.b64decode(blob).decode("utf-8")
                    break
                except Exception:
                    continue
            return 0, "/home/u/base/ICESEE-Spack-setup/spack_setup.sbatch\n", ""
        if script.startswith("sbatch "):
            self.submitted_scripts.append(script)
            return 0, "Submitted batch job 555\n", ""
        return 0, "", ""


@pytest.fixture
def wire(monkeypatch):
    def _wire(resource: FakeResource, mode: str):
        def fake_ssh(host, user, port, cmd, timeout=20):
            rc, out, err = resource.run(cmd)
            return _R(out, rc)

        def fake_connector_ssh(session_id, host, user, port, cmd, timeout=20, cluster_name="pace"):
            rc, out, err = resource.run(cmd)
            return {"ok": rc == 0, "returncode": rc, "stdout": out, "stderr": err}

        def fake_connector_submit(session_id, host, user, port, script_path, timeout=60):
            resource.submitted_scripts.append(f"sbatch {script_path}")
            return {"ok": True, "submitted": True, "jobid": "555"}

        monkeypatch.setattr(bridge_mod, "ssh_run", fake_ssh)
        monkeypatch.setattr(bridge_mod, "connector_ssh", fake_connector_ssh)
        monkeypatch.setattr(bridge_mod, "connector_slurm_submit", fake_connector_submit)
        return RemoteBridge(
            mode=mode, host="login", user="u", port=22,
            session_id="s" if mode == "connector" else None,
        )
    return _wire


MODES = ["direct", "connector"]


@pytest.mark.parametrize("mode", MODES)
def test_fresh_resource_is_not_installed(wire, mode):
    b = wire(FakeResource(repo_present=False), mode)
    r = b.environment_status(model="issm", remote_base="~/base")
    assert r.status is EnvStatus.NOT_INSTALLED


@pytest.mark.parametrize("mode", MODES)
def test_cloned_but_unbuilt_is_repo_only(wire, mode):
    b = wire(FakeResource(repo_present=True, model_ok=False), mode)
    assert b.environment_status(model="issm", remote_base="~/base").status is EnvStatus.REPO_ONLY


@pytest.mark.parametrize("mode", MODES)
def test_valid_issm_install_is_ready(wire, mode):
    b = wire(FakeResource(repo_present=True, model_ok=True), mode)
    assert b.environment_status(model="issm", remote_base="~/base").is_ready


@pytest.mark.parametrize("mode", MODES)
def test_valid_icepack_install_is_ready(wire, mode):
    b = wire(FakeResource(repo_present=True, model_ok=True), mode)
    assert b.environment_status(model="icepack", remote_base="~/base").is_ready


@pytest.mark.parametrize("mode", MODES)
def test_prepare_on_fresh_resource_submits_a_setup_job(wire, mode):
    res = FakeResource(repo_present=False)
    b = wire(res, mode)
    out = b.prepare_spack_environment(
        model="issm", remote_base="~/base",
        matlab_license={"env_var": "MLM_LICENSE_FILE", "value": "1711@x"},
    )
    assert out["status"] is EnvStatus.INSTALLING
    assert out["job"]["job_id"] == "555"
    assert any(s.startswith("sbatch ") for s in res.submitted_scripts)
    # the setup script is an sbatch job, never a synchronous install.sh call
    body = res.written.get("last", "")
    assert "install.sh --with-issm" in body
    assert out["job"]["log_file"].endswith("spack-setup-555.out")


@pytest.mark.parametrize("mode", MODES)
def test_prepare_on_ready_resource_reuses_without_rebuild(wire, mode):
    res = FakeResource(repo_present=True, model_ok=True)
    b = wire(res, mode)
    out = b.prepare_spack_environment(model="issm", remote_base="~/base")
    assert out["status"] is EnvStatus.READY
    assert out["reused"] is True
    assert res.submitted_scripts == []          # nothing rebuilt


def test_direct_and_connector_produce_the_same_classification(wire):
    d = wire(FakeResource(repo_present=True, model_ok=True), "direct")
    c = wire(FakeResource(repo_present=True, model_ok=True), "connector")
    assert (d.environment_status(model="issm", remote_base="~/base").status
            == c.environment_status(model="issm", remote_base="~/base").status)
