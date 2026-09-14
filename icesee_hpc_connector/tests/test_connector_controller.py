"""macOS-ANR follow-up: the connector controller keeps all I/O off the caller.

The GUI thread (Cocoa / pystray) must never block on the network; the worker
thread must stop promptly; lifecycle logs carry only fixed event names.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import icesee_hpc_connector.connector_core as cc
from icesee_hpc_connector.connector_controller import (
    LIFECYCLE_EVENTS,
    ConnectorController,
    ConnectorState,
)
from icesee_hpc_connector.single_instance import SingleInstance


# ── start() never blocks; the worker runs off-thread ──────────────────────
def test_start_returns_immediately_and_runs_off_thread(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def fake_run_connector(*_a, stop_event=None, on_event=None, **_k):
        entered.set()
        release.wait(2)

    monkeypatch.setattr(cc, "run_connector", fake_run_connector)
    monkeypatch.setattr(
        "icesee_hpc_connector.connector_controller.run_connector", fake_run_connector
    )
    ctrl = ConnectorController("https://relay.example")

    t0 = time.monotonic()
    assert ctrl.start("ABCDE-FGHIJ") is True
    assert time.monotonic() - t0 < 0.3           # did not wait on the worker
    assert entered.wait(1)
    assert ctrl.is_running()
    assert ctrl.start("XXXXX-YYYYY") is False     # single worker

    release.set()
    ctrl.stop(timeout=2)
    assert not ctrl.is_running()


def test_pairing_http_does_not_run_inline_from_start(monkeypatch):
    calls: list = []

    def slow_post(*a, **k):
        calls.append(time.monotonic())
        time.sleep(1.0)
        raise RuntimeError("no network")

    monkeypatch.setattr(cc.requests, "post", slow_post)
    ctrl = ConnectorController("https://relay.example")

    t0 = time.monotonic()
    ctrl.start("ABCDE-FGHIJ")
    # start() returned without waiting for the (slow) pairing POST
    assert time.monotonic() - t0 < 0.3
    ctrl.stop(timeout=3)


# ── stop() signals + joins the worker ───────────────────────────────────
def test_stop_signals_and_joins(monkeypatch):
    saw_stop = threading.Event()

    def fake_run_connector(*_a, stop_event=None, on_event=None, **_k):
        while not stop_event.is_set():
            stop_event.wait(0.05)
        saw_stop.set()

    monkeypatch.setattr(
        "icesee_hpc_connector.connector_controller.run_connector", fake_run_connector
    )
    ctrl = ConnectorController("https://relay.example")
    ctrl.start(None)
    time.sleep(0.1)
    ctrl.stop(timeout=2)
    assert saw_stop.is_set()
    assert not ctrl.is_running()
    assert ctrl.status() == ConnectorState.STOPPED


def test_repeated_start_stop_is_safe(monkeypatch):
    monkeypatch.setattr(
        "icesee_hpc_connector.connector_controller.run_connector",
        lambda *_a, stop_event=None, on_event=None, **_k: stop_event.wait(5),
    )
    ctrl = ConnectorController("https://relay.example")
    for _ in range(4):
        assert ctrl.start(None) is True
        ctrl.stop(timeout=2)
        assert not ctrl.is_running()


# ── reconnect wait is interruptible (no bare time.sleep in the loop) ─────
def test_reconnect_wait_is_interruptible(monkeypatch):
    monkeypatch.setattr(
        cc, "pair_session",
        lambda relay, code: {"session_id": "s", "session_secret": "x"},
    )

    def boom(coro=None, *_a, **_k):
        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError("relay down")

    monkeypatch.setattr(cc.asyncio, "run", boom)

    stop = threading.Event()
    threading.Timer(0.15, stop.set).start()

    t0 = time.monotonic()
    cc.run_connector(
        relay="https://relay.example", pairing_code="ABCDE-FGHIJ",
        poll=True, poll_seconds=30, stop_event=stop,
    )
    # despite poll_seconds=30, stop_event ends the loop in well under a second
    assert time.monotonic() - t0 < 2.0


# ── lifecycle logging: fixed names only, no secrets ─────────────────────
def test_lifecycle_log_is_name_only_and_allowlisted():
    lines: list[str] = []
    ctrl = ConnectorController("https://relay.example", log=lines.append)

    for ev in ("app-start", "pairing-request-start", "websocket-connected",
               "ssh-command-start", "app-shutdown"):
        ctrl.emit(ev)
    ctrl.emit("SECRET pairing code ABCDE-FGHIJ")      # not an allowlisted name
    ctrl.emit("session_secret=deadbeef")

    assert len(lines) == 5
    for line in lines:
        assert line.startswith("[lifecycle] ")
        name = line.split()[-1]
        assert name in LIFECYCLE_EVENTS
    blob = "\n".join(lines)
    for leak in ("ABCDE-FGHIJ", "deadbeef", "session_secret", "SECRET"):
        assert leak not in blob


def test_worker_never_forwards_secrets_to_the_logger(monkeypatch):
    lines: list[str] = []

    def fake_run_connector(*_a, stop_event=None, on_event=None, **_k):
        # the real run_connector only ever calls on_event(<name>)
        on_event("pairing-request-start")
        on_event("pairing-request-complete")
        on_event("websocket-thread-start")
        stop_event.wait(1)

    monkeypatch.setattr(
        "icesee_hpc_connector.connector_controller.run_connector", fake_run_connector
    )
    ctrl = ConnectorController("https://relay.example", log=lines.append)
    ctrl.start("SUPER-SECRET-CODE")
    time.sleep(0.2)
    ctrl.stop(timeout=2)
    assert "SUPER-SECRET-CODE" not in "\n".join(lines)


# ── single instance ───────────────────────────────────────────────────
def test_single_instance_blocks_a_second_holder(tmp_path):
    lock_path = tmp_path / "connector.lock"
    a = SingleInstance(lock_path)
    b = SingleInstance(lock_path)
    assert a.acquire() is True
    assert b.acquire() is False           # a still holds it
    a.release()
    assert b.acquire() is True
    b.release()


# ── source guards ─────────────────────────────────────────────────────
def test_no_global_latest_and_bounded_connect():
    core = (_REPO / "icesee_hpc_connector" / "connector_core.py").read_text()
    ctl = (_REPO / "icesee_hpc_connector" / "connector_controller.py").read_text()
    menu = (_REPO / "icesee_hpc_connector" / "connector_menubar_app.py").read_text()
    for src in (core, ctl, menu):
        assert "/connector/latest" not in src
    # bounded WebSocket connect, and an interruptible reconnect wait
    assert "open_timeout=" in core and "asyncio.wait_for(" in core
    assert "stop_event.wait(poll_seconds)" in core
    # no dead/fragile import
    assert "from click import" not in core


def test_no_second_gui_loop_on_macos():
    menu = (_REPO / "icesee_hpc_connector" / "connector_menubar_app.py").read_text()
    # tkinter is referenced only in the Linux/Windows prompt helper
    assert "_prompt_pairing_code_tk" in menu
    darwin_block = menu.split('if sys.platform == "darwin":')[1].split("# ====")[0]
    assert "tkinter" not in darwin_block
    assert "rumps.Timer" in darwin_block          # main-thread status polling


def test_menubar_quit_stops_the_controller():
    menu = (_REPO / "icesee_hpc_connector" / "connector_menubar_app.py").read_text()
    assert "def quit_app" in menu and "self.controller.stop()" in menu
    assert "controller.stop()" in menu.split("finally:")[1]   # also on any exit
