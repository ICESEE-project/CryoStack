"""cryostack_src.cloud.license_tunnel_client -- unit-level tests for the
selfcheck/serve/listen CLI split, the scientist-facing message mapping, and
argument wiring. The genuine end-to-end (real relay + real Connector + real
local echo server) path is covered separately in
test_license_tunnel_integration.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import cryostack_src.cloud.license_tunnel_client as ltc


def test_scientist_facing_messages_never_mention_jargon():
    for code in ("relay_unreachable", "relay_no_response", "connector_refused", "unknown-code"):
        msg = ltc.scientist_facing_connectivity_error(code)
        low = msg.lower()
        for banned in ("websocket", "relay", "arn", "secrets manager", "iam", "flexnet",
                       "mlm_license_file", "connector session", "tunnel_id"):
            assert banned not in low, f"{banned!r} leaked into: {msg!r}"
        assert "MATLAB license" in msg


# ── selfcheck subcommand (diagnostics/testing) ───────────────────────────
def test_selfcheck_failure_writes_the_scientist_message_and_exits_nonzero(tmp_path, monkeypatch):
    async def fake_selfcheck(**kw):
        return False, "connector_refused"

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    status_file = tmp_path / "status.txt"
    rc = ltc.main([
        "selfcheck", "--relay", "https://relay.example", "--session", "sid",
        "--token", "tok", "--purpose", "matlab-license", "--endpoint", "primary",
        "--status", str(status_file),
    ])
    assert rc == 1
    written = status_file.read_text()
    assert written == ltc.scientist_facing_connectivity_error("connector_refused")
    assert "arn:aws" not in written and "tok" not in written


def test_selfcheck_success_writes_ok_and_exits_zero(tmp_path, monkeypatch):
    async def fake_selfcheck(**kw):
        return True, ""

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    status_file = tmp_path / "status.txt"
    rc = ltc.main([
        "selfcheck", "--relay", "https://relay.example", "--session", "sid",
        "--token", "tok", "--purpose", "matlab-license", "--endpoint", "primary",
        "--status", str(status_file),
    ])
    assert rc == 0
    assert status_file.read_text() == "OK"


def test_selfcheck_never_writes_the_raw_token_anywhere(tmp_path, monkeypatch):
    seen = {}

    async def fake_selfcheck(**kw):
        seen.update(kw)
        return False, "relay_unreachable"

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    status_file = tmp_path / "status.txt"
    ltc.main([
        "selfcheck", "--relay", "https://relay.example", "--session", "sid",
        "--token", "super-secret-tunnel-token", "--purpose", "matlab-license",
        "--endpoint", "primary", "--status", str(status_file),
    ])
    assert seen["token"] == "super-secret-tunnel-token"   # passed through internally...
    assert "super-secret-tunnel-token" not in status_file.read_text()  # ...never surfaced


# ── env-var fallback: the Batch runner invokes `listen` with NO flags ──
def test_listen_reads_everything_from_the_environment_with_no_flags(monkeypatch):
    """The exact shape the runner script actually uses: `listen` with
    zero CLI flags, everything resolved from CRYOSTACK_LT_* env vars."""
    monkeypatch.setenv("CRYOSTACK_LT_RELAY", "https://relay.example")
    monkeypatch.setenv("CRYOSTACK_LT_SESSION", "sid-env")
    monkeypatch.setenv("CRYOSTACK_LT_TOKEN", "tok-env")
    monkeypatch.setenv("CRYOSTACK_LT_PURPOSE", "matlab-license")
    monkeypatch.setenv("CRYOSTACK_LT_ENDPOINT", "primary")
    monkeypatch.setenv("CRYOSTACK_LT_PORT", "1711")

    seen = {}

    async def fake_selfcheck(**kw):
        seen.update(kw)
        return True, ""

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: None)
    monkeypatch.setattr(ltc, "_wait_for_local_port", lambda host, port, timeout: True)

    rc = ltc.main(["listen"])   # <-- no flags at all

    assert rc == 0
    assert seen["relay_url"] == "https://relay.example"
    assert seen["session_id"] == "sid-env"
    assert seen["token"] == "tok-env"
    assert seen["purpose"] == "matlab-license"
    assert seen["endpoint"] == "primary"


def test_a_flag_overrides_the_environment_variable(monkeypatch):
    monkeypatch.setenv("CRYOSTACK_LT_RELAY", "https://from-env.example")
    monkeypatch.setenv("CRYOSTACK_LT_SESSION", "sid-env")
    monkeypatch.setenv("CRYOSTACK_LT_TOKEN", "tok-env")
    monkeypatch.setenv("CRYOSTACK_LT_PURPOSE", "matlab-license")
    monkeypatch.setenv("CRYOSTACK_LT_ENDPOINT", "primary")

    seen = {}

    async def fake_selfcheck(**kw):
        seen.update(kw)
        return True, ""

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    status_file_holder: dict = {}

    def fake_write(path, message):
        status_file_holder["message"] = message

    monkeypatch.setattr(ltc, "_write_status", fake_write)

    rc = ltc.main(["selfcheck", "--relay", "https://from-flag.example"])

    assert rc == 0
    assert seen["relay_url"] == "https://from-flag.example"   # flag wins
    assert seen["session_id"] == "sid-env"                    # env fills the rest


def test_missing_required_value_fails_closed_with_a_clear_message(monkeypatch):
    for name in ("CRYOSTACK_LT_RELAY", "CRYOSTACK_LT_SESSION", "CRYOSTACK_LT_TOKEN",
                 "CRYOSTACK_LT_PURPOSE", "CRYOSTACK_LT_ENDPOINT", "CRYOSTACK_LT_PORT"):
        monkeypatch.delenv(name, raising=False)

    rc = ltc.main(["listen"])
    assert rc == 2   # never guesses, never proceeds to a network call


def test_missing_required_value_never_calls_selfcheck(monkeypatch):
    called = []
    monkeypatch.setattr(ltc, "selfcheck", lambda **kw: called.append(kw))
    for name in ("CRYOSTACK_LT_RELAY", "CRYOSTACK_LT_SESSION", "CRYOSTACK_LT_TOKEN",
                 "CRYOSTACK_LT_PURPOSE", "CRYOSTACK_LT_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)

    ltc.main(["selfcheck"])
    assert called == []


# ── serve subcommand (the detached, long-running half) ──────────────────
def test_serve_invokes_run_local_listener_with_the_given_arguments(monkeypatch):
    seen = {}

    async def fake_run_local_listener(**kw):
        seen.update(kw)
        cb = kw.get("ready_callback")
        if cb:
            cb()

    monkeypatch.setattr(ltc, "run_local_listener", fake_run_local_listener)
    rc = ltc.main([
        "serve", "--relay", "https://relay.example", "--session", "sid",
        "--token", "tok", "--purpose", "matlab-license", "--endpoint", "primary",
        "--host", "127.0.0.1", "--port", "1711",
    ])
    assert rc == 0
    assert seen["listen_host"] == "127.0.0.1"
    assert seen["listen_port"] == 1711
    assert seen["session_id"] == "sid"
    assert seen["token"] == "tok"


# ── listen subcommand: selfcheck (foreground) + detach serve + wait ─────
def test_listen_fails_fast_without_spawning_anything_when_selfcheck_fails(monkeypatch, capsys):
    async def fake_selfcheck(**kw):
        return False, "connector_refused"

    spawned = []
    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: spawned.append((a, k)))

    rc = ltc.main([
        "listen", "--relay", "https://relay.example", "--session", "sid",
        "--token", "tok", "--purpose", "matlab-license", "--endpoint", "primary",
        "--port", "1711",
    ])
    assert rc == 1
    assert spawned == []
    out = capsys.readouterr().out
    assert out.strip() == ltc.scientist_facing_connectivity_error("connector_refused")


def test_listen_spawns_a_detached_serve_process_and_waits_for_the_port(monkeypatch):
    async def fake_selfcheck(**kw):
        return True, ""

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)

    popen_calls = []

    class _FakePopen:
        def __init__(self, args, **kw):
            popen_calls.append((args, kw))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    monkeypatch.setattr(ltc, "_wait_for_local_port", lambda host, port, timeout: True)

    rc = ltc.main([
        "listen", "--relay", "https://relay.example", "--session", "sid",
        "--token", "tok", "--purpose", "matlab-license", "--endpoint", "primary",
        "--port", "1711",
    ])
    assert rc == 0
    assert len(popen_calls) == 1
    args, kw = popen_calls[0]
    assert "serve" in args
    # NO flags passed to the detached child -- it reads everything from
    # its environment (see _ENV_FALLBACK); `listen` re-asserts what IT
    # resolved into that child's env explicitly, rather than relying on
    # ambient inheritance alone.
    assert "--port" not in args and "--relay" not in args
    assert kw.get("start_new_session") is True
    env = kw.get("env") or {}
    assert env.get("CRYOSTACK_LT_RELAY") == "https://relay.example"
    assert env.get("CRYOSTACK_LT_SESSION") == "sid"
    assert env.get("CRYOSTACK_LT_TOKEN") == "tok"
    assert env.get("CRYOSTACK_LT_PURPOSE") == "matlab-license"
    assert env.get("CRYOSTACK_LT_ENDPOINT") == "primary"
    assert env.get("CRYOSTACK_LT_PORT") == "1711"


def test_listen_fails_if_the_detached_serve_never_binds_the_port(monkeypatch):
    async def fake_selfcheck(**kw):
        return True, ""

    monkeypatch.setattr(ltc, "selfcheck", fake_selfcheck)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: None)
    monkeypatch.setattr(ltc, "_wait_for_local_port", lambda host, port, timeout: False)

    rc = ltc.main([
        "listen", "--relay", "https://relay.example", "--session", "sid",
        "--token", "tok", "--purpose", "matlab-license", "--endpoint", "primary",
        "--port", "1711",
    ])
    assert rc == 1


def test_wait_for_local_port_detects_a_real_open_port():
    import socket
    import threading

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert ltc._wait_for_local_port("127.0.0.1", port, timeout=2) is True
    finally:
        srv.close()


def test_wait_for_local_port_times_out_when_nothing_listens():
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # bound then released -- nothing listening on it
    assert ltc._wait_for_local_port("127.0.0.1", port, timeout=0.3) is False


def test_relay_ws_url_converts_scheme_and_appends_path():
    assert ltc._relay_ws_url("https://cryostack.eas.gatech.edu", "sid-1") == (
        "wss://cryostack.eas.gatech.edu/connector/tunnel/sid-1"
    )
    assert ltc._relay_ws_url("http://127.0.0.1:8000/", "sid-2") == (
        "ws://127.0.0.1:8000/connector/tunnel/sid-2"
    )
