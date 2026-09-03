"""Visible feedback for the three Cloud environment operations
(Test connection / Prepare cloud / Infrastructure smoke test).

All UI-only: fake buttons / rows / chip, fake bridges + workers. The
coordinator is driven with a *deferred* ``spawn`` so the busy state can be
observed before the async part runs, and with a real background loop for the
re-entrancy tests.
"""
from __future__ import annotations

import asyncio
import io
import sys
import threading
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.frontend.cryolauncher.cloud_runtime import (
    build_cloud_environment_ops,
    build_cloud_runtime_callbacks,
)


# ── fakes ───────────────────────────────────────────────────────────────
class _Btn:
    def __init__(self, description="", icon="", button_style="", disabled=False):
        self.description = description
        self.icon = icon
        self.button_style = button_style
        self.disabled = disabled

    def snapshot(self):
        return (self.description, self.icon, self.button_style, self.disabled)


class _HtmlW:
    def __init__(self):
        self.value = ""


class _Out:
    """A minimal stand-in for ipywidgets.Output: `with out: print(...)` is
    captured into `out.text`."""

    def __init__(self):
        self._buf = io.StringIO()
        self._redir = None

    @property
    def text(self):
        return self._buf.getvalue()

    def clear_output(self):
        self._buf = io.StringIO()

    def __enter__(self):
        self._redir = redirect_stdout(self._buf)
        self._redir.__enter__()
        return self

    def __exit__(self, *a):
        self._redir.__exit__(*a)
        self._redir = None
        return False


class _Chip:
    def __init__(self):
        self.kinds = []

    def __call__(self, kind):
        self.kinds.append(kind)

    @property
    def last(self):
        return self.kinds[-1] if self.kinds else None


class _Rows:
    def __init__(self):
        self.state = {}          # id(widget) -> (state, label)
        self.by_name = {}

    def bind(self, name, widget):
        self.by_name[name] = widget

    def __call__(self, widget, *, state, label):
        self.state[id(widget)] = (state, label)

    def of(self, name):
        return self.state.get(id(self.by_name[name]))


def _harness(*, spawn=None):
    rows_widgets = {k: _HtmlW() for k in ("account", "storage", "registry", "compute")}
    rows = _Rows()
    for k, w in rows_widgets.items():
        rows.bind(k, w)
    buttons = {
        "test": _Btn("Test connection", "plug", "", False),
        "prepare": _Btn("Prepare cloud", "cloud", "primary", False),
        "smoke": _Btn("Infrastructure smoke test", "stethoscope", "", False),
    }
    chip = _Chip()
    log = _Out()
    deferred = []
    _spawn = spawn or (lambda coro: deferred.append(coro))
    ops = build_cloud_environment_ops(
        buttons=buttons, rows=rows_widgets, set_row=rows, set_chip=chip,
        status_widget=_HtmlW(), status_html=lambda s: s, log_output=log,
        to_thread=_immediate, spawn=_spawn,
    )
    return dict(ops=ops, buttons=buttons, rows=rows, chip=chip, log=log,
                deferred=deferred)


async def _immediate(fn):
    return fn()


def _drain(deferred):
    for coro in list(deferred):
        asyncio.run(coro)
    deferred.clear()


# ── 1-3: immediate busy state, per operation ────────────────────────────
def test_test_connection_busy_state():
    h = _harness()
    h["ops"].test_connection(lambda: _Caps(True), lambda r: None)
    assert h["chip"].last == "testing"
    assert h["rows"].of("account") == ("running", "Checking…")
    b = h["buttons"]
    assert b["test"].disabled and b["test"].description == "Testing…" and b["test"].icon == "spinner"
    assert b["prepare"].disabled and b["smoke"].disabled
    _drain(h["deferred"])


def test_prepare_busy_state():
    h = _harness()
    h["ops"].prepare_cloud(lambda: {"success": True}, lambda r: None)
    assert h["chip"].last == "preparing"
    assert h["rows"].of("account") == ("running", "Checking…")
    for k in ("storage", "registry", "compute"):
        assert h["rows"].of(k) == ("running", "Preparing…")
    b = h["buttons"]
    assert b["prepare"].disabled and b["prepare"].description == "Preparing…" and b["prepare"].icon == "spinner"
    assert b["test"].disabled and b["smoke"].disabled
    _drain(h["deferred"])


def test_smoke_busy_state():
    h = _harness()
    h["ops"].smoke_test(lambda: _Report(True), lambda r: None)
    assert h["chip"].last == "smoke_testing"
    for k in ("account", "storage", "registry", "compute"):
        assert h["rows"].of(k) == ("running", "Checking…")
    b = h["buttons"]
    assert all(b[x].disabled for x in ("test", "prepare", "smoke"))
    assert b["smoke"].description == "Testing…" and b["smoke"].icon == "spinner"
    _drain(h["deferred"])


# ── 4-5: success / failure dispatch ────────────────────────────────────
class _Caps:
    def __init__(self, authed, storage=False, registry=False, batch=False):
        self.authenticated = authed
        self.storage_ready = storage
        self.registry_ready = registry
        self.batch_ready = batch
        self.messages = ["msg-a"]


class _Report:
    def __init__(self, ready):
        from cryostack_src.cloud.smoke import SmokeCheck
        self._ready = ready
        self.checks = [
            SmokeCheck("AWS identity", "PASS"),
            SmokeCheck("S3 write + read (your prefix)", "PASS" if ready else "FAIL"),
            SmokeCheck("S3 cleanup", "PASS"),
            SmokeCheck("Batch job queue", "PASS"),
            SmokeCheck("Batch job definition", "PASS"),
            SmokeCheck("ECR image", "PASS" if ready else "FAIL"),
        ]

    @property
    def infrastructure_ready(self):
        return self._ready

    def lines(self):
        return [f"  [{c.status}] {c.name}" for c in self.checks]


def _full(**over):
    """A build_cloud_runtime_callbacks harness with fake bridge + workers."""
    env = type("E", (), {
        "account_status": _HtmlW(), "storage_status": _HtmlW(),
        "registry_status": _HtmlW(), "compute_status": _HtmlW(),
        "test_button": _Btn("Test connection", "plug"),
        "prepare_button": _Btn("Prepare cloud", "cloud", "primary"),
    })()
    rows = _Rows()
    rows.bind("account", env.account_status)
    rows.bind("storage", env.storage_status)
    rows.bind("registry", env.registry_status)
    rows.bind("compute", env.compute_status)
    chip = _Chip()
    log = _Out()
    kw = dict(
        runtime_status={}, log_output=log, status_widget=_HtmlW(),
        status_html=lambda s: s, cloud_environment=env,
        set_cloud_status=rows, bucket_value=lambda: "cryostack-runs-1",
        results_output=_Out(), smoke_button=_Btn("smoke"),
        set_chip=chip, spawn=lambda coro: asyncio.run(coro),
    )
    kw.update(over)
    cb = build_cloud_runtime_callbacks(**kw)
    return cb, dict(env=env, rows=rows, chip=chip, log=log)


def test_test_connection_success_uses_real_capabilities():
    called = []
    cb, h = _full(bridge_factory=lambda: type("B", (), {
        "check_environment": staticmethod(lambda: _Caps(True))})())
    cb.check_environment()
    assert h["chip"].kinds[-1] == "connected"
    assert h["rows"].of("account") == ("done", "Connected")
    # not overclaimed: storage/compute were NOT checked -> stay "Not prepared"
    assert h["rows"].of("storage") == ("fail", "Not prepared")
    assert "[cloud][ERROR]" not in h["log"].text


def test_prepare_success_reflects_the_returned_capabilities():
    cb, h = _full(bridge_factory=lambda: type("B", (), {
        "prepare_environment": staticmethod(lambda *, bucket: {
            "success": True, "messages": ["ok"],
            "capabilities": _Caps(True, storage=True, registry=True, batch=True)})})())
    cb.prepare_environment()
    assert h["chip"].kinds[-1] == "ready"
    for k in ("account", "storage", "registry", "compute"):
        assert h["rows"].of(k)[0] == "done"


def test_prepare_partial_result_is_not_forced_to_ready():
    cb, h = _full(bridge_factory=lambda: type("B", (), {
        "prepare_environment": staticmethod(lambda *, bucket: {
            "success": True, "messages": [],
            "capabilities": _Caps(True, storage=True, registry=False, batch=False)})})())
    cb.prepare_environment()
    assert h["rows"].of("storage")[0] == "done"
    assert h["rows"].of("compute") == ("fail", "Not prepared")


def test_failure_classifies_and_marks_failed():
    cb, h = _full(bridge_factory=lambda: type("B", (), {
        "check_environment": staticmethod(
            lambda: (_ for _ in ()).throw(RuntimeError("AccessDenied calling sts")))})())
    cb.check_environment()
    assert h["chip"].kinds[-1] == "failed"
    assert h["rows"].of("account") == ("fail", "Failed")
    # test only checks identity -> storage row must NOT be claimed failed
    assert h["rows"].of("storage") is None
    assert "Access denied" in h["log"].text
    assert "[cloud][detail] AccessDenied calling sts" in h["log"].text


def test_prepare_early_stage_failure_does_not_falsely_fail_downstream_rows():
    # bootstrap aborts on storage; Containers/Compute were never attempted and
    # must NOT read as an independent failure (they show neutral "Not prepared").
    partial = {
        "success": False,
        "capabilities": None,
        "row_status": {"account": "connected", "storage": "failed",
                       "registry": "not_attempted", "compute": "not_attempted"},
        "messages": [
            "AWS account connected.",
            "[cloud][ERROR] Could not prepare the cloud environment (stage: storage). "
            "See the detail below and the AWS role's permissions.",
            "[cloud][detail] An error occurred (AccessDenied) when calling the "
            "CreateBucket operation",
        ],
    }
    cb, h = _full(bridge_factory=lambda: type("B", (), {
        "prepare_environment": staticmethod(lambda *, bucket: partial)})())
    cb.prepare_environment()
    assert h["rows"].of("account") == ("done", "Connected")
    assert h["rows"].of("storage") == ("fail", "Failed")
    assert h["rows"].of("registry") == ("idle", "Not prepared")
    assert h["rows"].of("compute") == ("idle", "Not prepared")
    assert h["chip"].kinds[-1] == "failed"
    # the underlying reason reaches the existing Run Log
    assert "stage: storage" in h["log"].text
    assert "AccessDenied" in h["log"].text


def test_prepare_unhandled_exception_marks_account_not_all_four():
    # a raw exception before any structured result (e.g. a broken connection)
    # -> account Failed, downstream rows neutral, sanitized reason in the log.
    cb, h = _full(bridge_factory=lambda: type("B", (), {
        "prepare_environment": staticmethod(
            lambda *, bucket: (_ for _ in ()).throw(
                RuntimeError("Your AWS connection could not be refreshed")))})())
    cb.prepare_environment()
    assert h["rows"].of("account") == ("fail", "Failed")
    assert h["rows"].of("storage") == ("idle", "Not prepared")
    assert h["rows"].of("registry") == ("idle", "Not prepared")
    assert h["rows"].of("compute") == ("idle", "Not prepared")
    assert "Could not prepare the cloud environment" in h["log"].text
    assert "could not be refreshed" in h["log"].text.lower()


# ── 6-7: exact button restoration ─────────────────────────────────────
def test_buttons_restore_to_their_exact_original_state_on_success():
    h = _harness()
    b = h["buttons"]
    b["test"].description = "Test conn"
    b["prepare"].disabled = True                 # legitimately disabled beforehand!
    b["prepare"].button_style = "warning"
    b["smoke"].icon = "flask"
    originals = {k: v.snapshot() for k, v in b.items()}

    h["ops"].test_connection(lambda: _Caps(True), lambda r: None)
    _drain(h["deferred"])
    for k, v in b.items():
        assert v.snapshot() == originals[k], k


def test_buttons_restore_after_worker_exception():
    h = _harness()
    b = h["buttons"]
    b["smoke"].disabled = True
    originals = {k: v.snapshot() for k, v in b.items()}

    def _boom():
        raise RuntimeError("AccessDenied")

    h["ops"].prepare_cloud(_boom, lambda r: None)
    _drain(h["deferred"])
    for k, v in b.items():
        assert v.snapshot() == originals[k], k
    assert not h["ops"].is_busy()


# ── 8-9: finally safety ───────────────────────────────────────────────
def test_guard_and_buttons_recover_when_on_success_raises():
    h = _harness()
    originals = {k: v.snapshot() for k, v in h["buttons"].items()}

    def _bad_success(_r):
        raise ValueError("on_success blew up")

    h["ops"].test_connection(lambda: _Caps(True), _bad_success)
    _drain(h["deferred"])
    assert not h["ops"].is_busy()
    for k, v in h["buttons"].items():
        assert v.snapshot() == originals[k]


def test_guard_recovers_when_the_reporter_raises():
    # _report writes into log_output; a log_output that raises on __enter__
    class _RaisingOut:
        def clear_output(self):
            pass

        def __enter__(self):
            raise RuntimeError("log is broken")

        def __exit__(self, *a):
            return False

    rows_widgets = {k: _HtmlW() for k in ("account", "storage", "registry", "compute")}
    buttons = {"test": _Btn("t"), "prepare": _Btn("p"), "smoke": _Btn("s")}
    originals = {k: v.snapshot() for k, v in buttons.items()}
    deferred = []
    ops = build_cloud_environment_ops(
        buttons=buttons, rows=rows_widgets, set_row=lambda *a, **k: None,
        set_chip=lambda _k: None, log_output=_RaisingOut(),
        to_thread=_immediate, spawn=deferred.append,
    )

    def _boom():
        raise RuntimeError("AccessDenied")

    ops.prepare_cloud(_boom, lambda r: None)
    with pytest.raises(RuntimeError):
        _drain(deferred)                          # the reporter itself raises
    # even so, the guard is released and the buttons are restored
    assert not ops.is_busy()
    for k, v in buttons.items():
        assert v.snapshot() == originals[k]


# ── 10-12: re-entrancy / exclusion / release ──────────────────────────
def test_duplicate_same_operation_schedules_once():
    h = _harness()
    calls = []
    h["ops"].test_connection(lambda: calls.append("w") or _Caps(True), lambda r: None)
    h["ops"].test_connection(lambda: calls.append("w") or _Caps(True), lambda r: None)
    assert len(h["deferred"]) == 1               # 2nd invocation ignored
    _drain(h["deferred"])
    assert calls == ["w"]


def test_cross_operation_exclusion_while_prepare_in_flight():
    h = _harness()
    ran = []
    h["ops"].prepare_cloud(lambda: ran.append("prepare") or {"success": True}, lambda r: None)
    # programmatic invocations of the other two while prepare "in flight"
    h["ops"].test_connection(lambda: ran.append("test"), lambda r: None)
    h["ops"].smoke_test(lambda: ran.append("smoke"), lambda r: None)
    assert len(h["deferred"]) == 1
    _drain(h["deferred"])
    assert ran == ["prepare"]


def test_guard_releases_so_the_next_operation_can_run():
    h = _harness()
    h["ops"].prepare_cloud(lambda: {"success": True}, lambda r: None)
    _drain(h["deferred"])
    assert not h["ops"].is_busy()
    ran = []
    h["ops"].test_connection(lambda: ran.append("test") or _Caps(True), lambda r: None)
    _drain(h["deferred"])
    assert ran == ["test"]


def test_reentrancy_with_a_real_background_loop_and_a_blocking_worker():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        started, release = threading.Event(), threading.Event()
        calls = []

        def worker():
            calls.append(1)
            started.set()
            release.wait(2)
            return _Caps(True)

        rows_widgets = {k: _HtmlW() for k in ("account", "storage", "registry", "compute")}
        buttons = {"test": _Btn("t"), "prepare": _Btn("p"), "smoke": _Btn("s")}
        futs = []
        ops = build_cloud_environment_ops(
            buttons=buttons, rows=rows_widgets, set_row=lambda *a, **k: None,
            set_chip=lambda _k: None, log_output=_Out(),
            to_thread=asyncio.to_thread,
            spawn=lambda coro: futs.append(
                asyncio.run_coroutine_threadsafe(coro, loop)),
        )
        ops.test_connection(worker, lambda r: None)
        assert started.wait(2)
        assert ops.is_busy()
        ops.test_connection(worker, lambda r: None)      # rejected while running
        assert len(futs) == 1
        release.set()
        futs[0].result(3)
        assert calls == [1] and not ops.is_busy()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(3)
        loop.close()


# ── 13: worker never touches a widget ─────────────────────────────────
def test_worker_return_value_is_only_touched_outside_the_worker():
    """The coordinator awaits to_thread(worker) and passes the *return value*
    to on_success; the worker signature takes no widgets."""
    import inspect

    from cryostack_src.frontend.cryolauncher import cloud_runtime as mod
    src = inspect.getsource(mod.build_cloud_environment_ops)
    # the only await of the worker is `await to_thread(worker)`
    assert "await to_thread(worker)" in src
    # busy UI + restore happen around it, not inside a thread
    assert "_apply_busy(op)" in src and "_restore_buttons()" in src
    h = _harness()
    seen = []
    h["ops"].smoke_test(lambda: _Report(True), lambda r: seen.append(r))
    _drain(h["deferred"])
    assert len(seen) == 1 and seen[0].infrastructure_ready


# ── 15: account id vs profile invariant ──────────────────────────────
def test_account_id_never_becomes_an_aws_cli_profile():
    from cryostack_src.cloud.config import resolve_cloud_config
    cfg = resolve_cloud_config(provider="aws", region="us-east-2",
                               bucket="cryostack-runs-713938953301", profile="")
    assert cfg.profile is None                    # blank -> ambient chain
    # nothing turns the account id into --profile 713938953301
    assert cfg.bucket == "cryostack-runs-713938953301"
