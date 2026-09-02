"""C6-D: the manual cloud runtime buttons report actionable failures."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.frontend.cryolauncher.cloud_runtime import (
    build_cloud_runtime_callbacks,
)


class _Out:
    def __init__(self):
        self.lines = []

    def clear_output(self):
        self.lines.clear()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    # `print(..., file=?)` isn't used; the code does `with out: print(...)`,
    # which writes to real stdout. Capture via a builtins.print shim instead.


class _Btn:
    def __init__(self):
        self.description = ""
        self.icon = ""
        self.button_style = ""
        self.disabled = False


def _mk(bridge, capsys):
    env = type("E", (), {k: type("W", (), {"value": ""})()
                         for k in ("account_status", "storage_status",
                                   "registry_status", "compute_status")}
              | {"test_button": _Btn(), "prepare_button": _Btn()})()
    cb = build_cloud_runtime_callbacks(
        runtime_status={"batch_job_id": "job-1", "cloud_run": "s3://b/runs/x"},
        log_output=_Out(), status_widget=type("S", (), {"value": ""})(),
        status_html=lambda s: s, bridge_factory=lambda: bridge,
        cloud_environment=env, set_cloud_status=lambda *a, **k: None,
        bucket_value=lambda: "cryostack-b", results_output=_Out(),
        smoke_button=_Btn(), set_chip=lambda _k: None,
        spawn=lambda coro: __import__("asyncio").run(coro),
    )
    return cb


class _BadBridge:
    def __init__(self, exc):
        self._exc = exc

    def status(self, **kw):
        raise self._exc

    def logs(self, **kw):
        raise self._exc

    def terminate(self, **kw):
        raise self._exc

    def results(self, **kw):
        raise self._exc

    def check_environment(self):
        raise self._exc


def test_status_failure_is_classified(capsys):
    cb = _mk(_BadBridge(RuntimeError("Unable to locate credentials")), capsys)
    cb.status()
    out = capsys.readouterr().out
    assert "credentials are not configured" in out
    assert "[cloud][detail] Unable to locate credentials" in out


def test_results_failure_is_classified(capsys):
    cb = _mk(_BadBridge(RuntimeError("An error occurred (NoSuchBucket)")), capsys)
    cb.results()
    out = capsys.readouterr().out
    assert "S3 bucket is missing" in out


def test_check_environment_failure_is_classified(capsys):
    cb = _mk(_BadBridge(RuntimeError("AccessDenied on batch:DescribeJobs")), capsys)
    cb.check_environment()
    out = capsys.readouterr().out
    assert "Access denied" in out
