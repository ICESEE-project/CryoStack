"""Remote + ICESEE-Spack Environment block callbacks (fake bridge)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ipywidgets as W

from cryostack_src.frontend.cryolauncher.spack_runtime import build_spack_runtime_callbacks
from cryostack_src.remote.spack_env import EnvReport, EnvStatus, SetupSlurmOpts


class FakeBridge:
    def __init__(self, *, report, prepare_result=None, job_state="running", log_text=""):
        self._report = report
        self._prepare = prepare_result
        self._job_state = job_state
        self._log = log_text
        self.prepared = False

    def environment_status(self, **_):
        return self._report

    def prepare_spack_environment(self, **_):
        self.prepared = True
        return self._prepare

    def status(self, **_):
        return type("S", (), {"state": self._job_state})()

    def logs(self, **_):
        return {"stdout": self._log, "ok": True}


class Widgets:
    def __init__(self):
        self.badge = W.HTML()
        self.label = W.HTML()
        self.view_btn = W.Button(layout=W.Layout(display="none"))
        self.status = W.HTML()


def _cb(bridge, status=None):
    status = status or {}
    wx = Widgets()
    cbs = build_spack_runtime_callbacks(
        runtime_status=status,
        log_output=W.Output(),
        status_widget=wx.status,
        status_html=lambda s: s,
        bridge_factory=lambda: bridge,
        ensure_connector_session=lambda: None,
        env_badge=wx.badge,
        setup_job_label=wx.label,
        view_log_button=wx.view_btn,
        model_value=lambda: "issm",
        remote_base_value=lambda: "~/base",
        spack_dirname_value=lambda: "ICESEE-Spack",
        spack_repo_value=lambda: "https://example/ICESEE-Spack.git",
        setup_slurm_opts=lambda: SetupSlurmOpts(),
        matlab_license_for=lambda m: {"env_var": "MLM_LICENSE_FILE", "value": "1711@x"},
    )
    return cbs, status, wx


def _ready():
    return EnvReport(EnvStatus.READY, "issm", ("ready",))


def _not_installed():
    return EnvReport(EnvStatus.NOT_INSTALLED, "issm", ("absent",))


def test_check_sets_badge_from_probe():
    cbs, _, wx = _cb(FakeBridge(report=_not_installed()))
    cbs.check()
    assert "Not installed" in wx.badge.value
    assert wx.status.value == "fail"


def test_check_ready_marks_done():
    cbs, _, wx = _cb(FakeBridge(report=_ready()))
    cbs.check()
    assert "Ready" in wx.badge.value
    assert wx.status.value == "done"


def test_prepare_on_ready_reuses_without_job():
    b = FakeBridge(report=_ready(),
                   prepare_result={"status": EnvStatus.READY, "reused": True, "report": _ready()})
    cbs, status, wx = _cb(b)
    cbs.prepare()
    assert "spack_setup_jobid" not in status
    assert "Ready" in wx.badge.value


def test_prepare_on_fresh_records_setup_job_and_shows_view_log():
    job = {"job_id": "777", "setup_dir": "/s", "log_file": "/s/spack-setup-777.out"}
    b = FakeBridge(
        report=_not_installed(),
        prepare_result={"status": EnvStatus.INSTALLING, "reused": False, "job": job},
    )
    cbs, status, wx = _cb(b)
    cbs.prepare()
    assert status["spack_setup_jobid"] == "777"
    assert status["spack_setup_log"].endswith("spack-setup-777.out")
    assert "Installing" in wx.badge.value and "777" in wx.badge.value
    assert wx.view_btn.layout.display == ""


def test_view_setup_log_completed_and_verified_marks_ready():
    b = FakeBridge(
        report=_ready(), job_state="completed",
        log_text="[spack-setup] ...\nCRYOSTACK_ENV_DEEP=ok\n[spack-setup] READY model=issm\n",
    )
    cbs, status, wx = _cb(b, {"spack_setup_jobid": "777", "spack_setup_dir": "/s",
                              "spack_setup_log": "/s/spack-setup-777.out",
                              "spack_setup_model": "issm"})
    cbs.view_setup_log()
    assert "Ready" in wx.badge.value
    assert wx.status.value == "done"


def test_view_setup_log_completed_but_probe_not_ready_is_failed():
    b = FakeBridge(report=_not_installed(), job_state="completed",
                   log_text="CRYOSTACK_ENV_DEEP=ok\n")
    cbs, status, wx = _cb(b, {"spack_setup_jobid": "777", "spack_setup_dir": "/s",
                              "spack_setup_log": "/s/x.out", "spack_setup_model": "issm"})
    cbs.view_setup_log()
    assert "Failed" in wx.badge.value


def test_view_setup_log_failed_job_reports_failed():
    b = FakeBridge(report=_not_installed(), job_state="failed",
                   log_text="install.sh: error\n")
    cbs, status, wx = _cb(b, {"spack_setup_jobid": "777", "spack_setup_dir": "/s",
                              "spack_setup_log": "/s/x.out", "spack_setup_model": "issm"})
    cbs.view_setup_log()
    assert "Failed" in wx.badge.value
    assert wx.status.value == "fail"


def test_view_setup_log_without_job_is_graceful():
    cbs, _, _ = _cb(FakeBridge(report=_not_installed()))
    cbs.view_setup_log()  # no job -> friendly message, no exception
